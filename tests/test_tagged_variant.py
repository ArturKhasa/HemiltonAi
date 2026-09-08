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


async def test_explicit_binding_replaces_the_step(db):
    """Условие у варианта своё — связывает их поле «заменяет шаг».

    Скрипт «свитшот + жилетка, 8980 ₽» завели с другим условием, и клиент с
    меткой получал общий расчёт «Стоимость толстовки — 5 990 ₽» (диалог 731).
    """
    db.add_all([
        Script(id=367, is_active=True, type_id=1, funnel_stage="pricing",
               condition=COND, phrase_text="Стоимость толстовки - 5 990 ₽"),
        Script(id=519, is_active=True, type_id=1,
               condition="Отправляем сразу после похвалы, рассказываем про стоимость",
               marketing_tag="hood141", variant_of_script_id=367,
               phrase_text="Толстовка + жилетка - 8 980 ₽"),
    ])
    await db.flush()
    picked = await tagged_variant(db, await db.get(Script, 367), {"hood141"})
    assert picked.id == 519


async def test_binding_does_not_leak_to_other_tags(db):
    db.add_all([
        Script(id=367, is_active=True, type_id=1, condition=COND,
               phrase_text="Стоимость толстовки - 5 990 ₽"),
        Script(id=519, is_active=True, type_id=1, condition="своё условие",
               marketing_tag="hood141", variant_of_script_id=367,
               phrase_text="Толстовка + жилетка - 8 980 ₽"),
    ])
    await db.flush()
    picked = await tagged_variant(db, await db.get(Script, 367), {"aigerb1"})
    assert picked.id == 367


async def test_tag_matches_regardless_of_case_and_hash(db):
    """В скрипте метку пишет человек, к клиенту она приезжает из ссылки."""
    db.add_all([
        Script(id=10, is_active=True, type_id=1, condition=COND, phrase_text="общий"),
        Script(id=11, is_active=True, type_id=1, condition=COND,
               marketing_tag="#SweetGold", phrase_text="под метку"),
    ])
    await db.flush()
    picked = await tagged_variant(db, await db.get(Script, 10), {"sweetgold"})
    assert picked.id == 11


async def test_other_dialog_type_is_not_borrowed(db):
    db.add_all([
        Script(id=1, is_active=True, type_id=1, condition=COND, phrase_text="наш"),
        Script(id=2, is_active=True, type_id=2, condition=COND,
               marketing_tag="sweetgold", phrase_text="чужой тип"),
    ])
    await db.flush()
    picked = await tagged_variant(db, await db.get(Script, 1), {"sweetgold"})
    assert picked.id == 1


class TestPriceGateKeepsTheKitPrice:
    """Гейт «первая цена — всегда полным прайс-скриптом» (правка ОП от 04.09,
    пункт B) обязан брать расчёт под метку, а не общий.

    08.09 06:31 на проде он этого не делал: клиенту с меткой комплекта
    `hood141` подменил расчёт 519 (свитшот + жилетка, 8 980 ₽) на общий 367
    (5 990 ₽). Цены разошлись, защита от смены цены сняла реплику целиком, и
    клиент остался без ответа на ходу (диалог 60937). Это ровно та жалоба РОП
    от 03.09 — «клиент пришёл за комплектом, ИИ отправляет ему цену на один
    свитшот», — которую гейт едва не вернул.
    """

    @pytest.fixture
    async def kit(self, db):
        db.add_all([
            Script(id=367, is_active=True, type_id=1, funnel_stage="pricing",
                   condition=COND, phrase_text="Стоимость - 5 990 ₽"),
            Script(id=519, is_active=True, type_id=1, funnel_stage="pricing",
                   condition="Комплект", marketing_tag="hood141",
                   variant_of_script_id=367,
                   phrase_text="Комплект из двух изделий со скидкой - 8 980 ₽"),
        ])
        await db.flush()
        return db

    async def test_kit_client_keeps_the_kit_calculation(self, kit):
        """То, что подставит гейт клиенту с меткой комплекта."""
        picked = await tagged_variant(kit, await kit.get(Script, 367), {"hood141"})

        assert picked.id == 519
        assert "8 980" in picked.phrase_text

    async def test_model_choosing_the_kit_script_is_left_alone(self, kit):
        """Модель выбрала 519 сама — гейт обязан отступить: 519 это вариант
        расчёта (variant_of_script_id=367), а не посторонний скрипт."""
        picked = await tagged_variant(kit, await kit.get(Script, 367), {"hood141"})
        already_price = 519 in {picked.id, picked.variant_of_script_id}

        assert already_price is True

    async def test_client_without_the_tag_still_gets_the_plain_price(self, kit):
        picked = await tagged_variant(kit, await kit.get(Script, 367), set())

        assert picked.id == 367
