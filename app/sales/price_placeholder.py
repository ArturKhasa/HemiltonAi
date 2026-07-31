"""Плейсхолдер цены в текстах скриптов: «[цена:свитшот]» → «4 990 ₽».

Скрипты, отправляемые связкой (follow_up_script_id), уходят клиенту дословно —
модель их не переписывает, и это ровно то, что нужно для расчёта сразу после
похвалы. Но цену внутрь такого скрипта нельзя вписывать руками: восемь ценовых
скриптов из выгрузки ОП именно так и протухли — они до сих пор обещают 5 990 ₽
и 6 680 ₽, тогда как в товарной матрице свитшот стоит 4 990 ₽ по акции.

Поэтому цена в тексте скрипта — ссылка на товарную матрицу, а не число.
Матрица остаётся единственным источником правды, редактировать её достаточно в
одном месте.
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.products import ProductService

logger = logging.getLogger(__name__)

# «[цена:свитшот]» — акционная (то, что клиент платит сегодня),
# «[цена-до-скидки:свитшот]» — обычная, та самая «вместо N рублей».
_PRICE_PLACEHOLDER_RE = re.compile(
    r"\[цена(-до-скидки)?:([^\]]+)\]", re.IGNORECASE
)


def format_price(value) -> str:
    """4990 → «4 990 ₽». Неразрывный пробел, чтобы сумма не рвалась переносом."""
    return f"{int(value):,}".replace(",", " ") + " ₽"


async def render_price_placeholders(
    db: AsyncSession, text: str, type_id: int | None = None,
) -> str:
    """Подставить акционные цены товаров вместо «[цена:запрос]».

    Товар не нашёлся — плейсхолдер убираем вместе со скобками, оставив запрос
    как обычное слово: лучше фраза без цифры, чем «[цена:свитшот]» у клиента.
    """
    matches = list(_PRICE_PLACEHOLDER_RE.finditer(text or ""))
    if not matches:
        return text

    svc = ProductService(db)
    result = text
    for m in matches:
        before_discount = bool(m.group(1))
        query = m.group(2).strip()
        products = await svc.search(query, type_id=type_id, limit=1)
        price = None
        if products:
            p = products[0]
            price = p.price if before_discount else (p.min_price if p.min_price is not None else p.price)
        if price is None:
            logger.warning("price placeholder %r: товар не найден, убираю плейсхолдер", query)
            result = result.replace(m.group(0), query)
        else:
            result = result.replace(m.group(0), format_price(price))
    return result
