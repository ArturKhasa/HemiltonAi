"""Доверие к корневым сертификатам Минцифры.

Российские сервисы (в том числе Bot API мессенджера MAX и его хранилище медиа)
работают по сертификатам «Russian Trusted CA». В общемировых хранилищах этого
корня нет: без него любой запрос к MAX падает с
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`, а бот молча
перестаёт отвечать.

httpx проверяет сертификаты по связке `certifi`, а не по системному хранилищу,
поэтому одной установки сертификатов в образ мало — контекст ниже собирает
обычный набор доверенных корней ПЛЮС сертификаты Минцифры из каталога `certs/`.
Само доверие только добавляется: всё, что работало раньше, продолжает работать.
"""
import logging
import ssl
from functools import lru_cache
from pathlib import Path

import certifi
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _certs_dir() -> Path:
    path = Path(settings.RU_TRUSTED_CA_DIR)
    return path if path.is_absolute() else Path(__file__).parent.parent / path


@lru_cache
def ru_trusted_context() -> ssl.SSLContext:
    """SSL-контекст: обычные корни + Минцифры."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    directory = _certs_dir()
    loaded = 0
    for pem in sorted(directory.glob("*.pem")):
        try:
            ctx.load_verify_locations(cafile=str(pem))
            loaded += 1
        except Exception as exc:
            logger.warning("сертификат %s не загрузился: %s", pem.name, exc)
    if not loaded:
        # Не падаем: без российских корней перестаёт работать только MAX, а
        # диагностируется это иначе — по ошибке проверки сертификата.
        logger.warning(
            "сертификаты Минцифры не найдены в %s — запросы к MAX не пройдут проверку",
            directory,
        )
    return ctx


def async_client(**kwargs) -> httpx.AsyncClient:
    """httpx-клиент, доверяющий в том числе сертификатам Минцифры."""
    kwargs.setdefault("verify", ru_trusted_context())
    return httpx.AsyncClient(**kwargs)
