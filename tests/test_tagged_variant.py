"""Свой расчёт под свою рекламную метку.

Скрипты воронки связаны фиксированным follow_up_script_id, а расчёт под разные
метки бывает разный: «а если на разные метки разный расчёт будет» — вопрос
заказчика от 20.08. Модель подменяет скрипт по метке сама, связка шла по id и
всегда отправляла общий вариант.
"""
import pytest

from app.ai.tools import tagged_variant
from app.db.models import Script

COND = "2.2 Стоимость (свитшот)"


@pytest.fixture
async def scripts(db):
    db.add_all([
        Script(id=367, is_active=True, type_id=1, funnel_stage="pricing",
               condition=COND, phrase_text="Стоимость - 5 990 ₽"),
        Script(id=368, is_active=True, type_id=1, funnel_stage="pricing",
               condition=COND, marketing_tag="sweetgold",
               phrase_text="Стоимость - 6 990 ₽"),
        Script(id=369, is_active=False, type_id=1, funnel_stage="pricing",
               condition=COND, marketing_tag="sweetrussia",
               phrase_text="Стоимость - 4 990 ₽ (выключен)"),
    ])
    await db.flush()
    return db


async def _base(db):
    return await db.get(Script, 367)


async def test_client_with_the_tag_gets_its_own_price(scripts):
    picked = await tagged_variant(scripts, await _base(scripts), {"sweetgold"})
    assert picked.id == 368


async def test_client_without_tags_gets_the_common_one(scripts):
    picked = await tagged_variant(scripts, await _base(scripts), set())
    assert picked.id == 367


async def test_foreign_tag_falls_back_to_the_common_one(scripts):
    picked = await tagged_variant(scripts, await _base(scripts), {"sweetwhite"})
    assert picked.id == 367


async def test_disabled_variant_is_not_used(scripts):
    """Выключенный в админке скрипт не должен вернуться в воронку через метку."""
    picked = await tagged_variant(scripts, await _base(scripts), {"sweetrussia"})
    assert picked.id == 367


async def test_other_dialog_type_is_not_borrowed(db):
    db.add_all([
        Script(id=1, is_active=True, type_id=1, condition=COND, phrase_text="наш"),
        Script(id=2, is_active=True, type_id=2, condition=COND,
               marketing_tag="sweetgold", phrase_text="чужой тип"),
    ])
    await db.flush()
    picked = await tagged_variant(db, await db.get(Script, 1), {"sweetgold"})
    assert picked.id == 1
