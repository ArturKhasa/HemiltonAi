"""Пока клиент не назвал товар, разговор идёт про линейку воронки.

Диалог 1847, 20 августа: клиент нажал «Начать», назвал имя и спросил «мне просто
интересно как визуально будет это». В ответ ушёл скрипт 406 — «Этот костюм мы
отшиваем в 4-х цветах» с фотографиями костюма. Товар клиент не называл, поэтому
фильтр по семейству не работал вовсе, и костюм был для модели таким же
кандидатом, как кофта.
"""
from types import SimpleNamespace

from app.ai.tools import format_scripts_list


def _script(id, condition, phrase_text):
    return SimpleNamespace(
        id=id, condition=condition, phrase_text=phrase_text,
        marketing_tag=None, funnel_stage=None,
    )


SUIT_PHOTOS = _script(406, "Дополнительные фотографии изделий для клиентов",
                      "Этот костюм мы отшиваем в 4-х цветах: черный, серый, синий и зеленый")
HOODIE_PHOTOS = _script(407, "Дополнительные фотографии изделий для клиентов",
                        "Свитшот с принтом выглядит так")
CATALOG = _script(409, "Клиент просит прислать весь каталог",
                  "Костюмы, свитшоты, худи, футболки — выбирайте")
NEUTRAL = _script(410, "Дополнительные способы оплаты", "Можно оплатить частями")


def test_suit_script_hidden_until_the_client_asks_for_a_suit():
    out = format_scripts_list([SUIT_PHOTOS, HOODIE_PHOTOS], client_tags=None, client_product=None)
    assert "406" not in out
    assert "407" in out


def test_client_who_named_a_suit_sees_it():
    out = format_scripts_list([SUIT_PHOTOS, HOODIE_PHOTOS], client_tags=None, client_product="костюм")
    assert "406" in out


def test_catalog_survives_the_default():
    """В каталоге перечислены все товары — он про линейку в том числе."""
    out = format_scripts_list([CATALOG], client_tags=None, client_product=None)
    assert "409" in out


def test_script_about_no_product_survives():
    out = format_scripts_list([NEUTRAL], client_tags=None, client_product=None)
    assert "410" in out
