FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
WORKDIR /app

ENV PYTHONPATH=/app

# Корневые сертификаты Минцифры: по ним работает MAX (platform-api2.max.ru и
# их хранилище медиа), в общемировых хранилищах этого корня нет. Ставим и в
# системное хранилище (для curl и прочих утилит), и в связку certifi — по ней
# проверяют сертификаты httpx и клиенты моделей, системное хранилище они не
# читают. Без этого запросы к MAX падают на проверке сертификата.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY certs/ /usr/local/share/ca-certificates/hemilton/
RUN cd /usr/local/share/ca-certificates/hemilton \
    && for f in *.pem; do mv "$f" "${f%.pem}.crt"; done \
    && update-ca-certificates

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system --no-build-isolation \
    fastapi uvicorn[standard] sqlalchemy[asyncio] alembic asyncpg \
    pydantic[email] pydantic-settings bcrypt python-jose[cryptography] \
    openai-agents litellm openai anthropic tiktoken \
    python-multipart websockets pgvector

# Дописываем через printf с переводом строки: без него последний сертификат
# связки склеивается с первым нашим, и OpenSSL перестаёт читать файл целиком
# («X509 PEM lib»), то есть отваливается проверка ВСЕХ сертификатов, не только
# российских.
RUN B="$(python -c 'import certifi; print(certifi.where())')" \
    && printf '\n' >> "$B" \
    && cat /usr/local/share/ca-certificates/hemilton/*.crt >> "$B" \
    && python -c "import ssl, certifi; ssl.create_default_context(cafile=certifi.where())"

COPY . .
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["sh", "-c", "\
  echo '[startup] Running migrations...' && \
  until alembic upgrade head; do \
    echo '[startup] DB not ready or migration failed, retrying in 3s...'; \
    sleep 3; \
  done && \
  echo '[startup] Migrations OK. Running seed...' && \
  python -m app.commands.seed && \
  echo '[startup] Starting uvicorn...' && \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
