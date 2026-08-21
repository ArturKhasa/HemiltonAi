"""Заказ на двоих: две надписи — значит два изделия.

Лена, 21.08: «Клиент пишет 2 имени/фамилии = пришел за парными изделиями,
соответственно, цену нужно отправлять на парные».

Диалог 75853: клиент ответил «Шишкин Кирилл и Виктория Шишкина», прислал два
роста с весом, прямо написал «Два свитшота» — и получил расчёт на одно изделие,
а следом сумму заказа 5 990 ₽ за оба.
"""
import pytest

from app.ai.tools import tagged_variant
from app.db.models import Script
from app.sales.order_slots import collect_slots, names_two_people, wants_two_items

COND = "2.2 Стоимость (свитшот)"
ASKS = "Кирилл, какое имя или фамилию напишем на Вашей кофте?"


class TestTwoNames:
    @pytest.mark.parametrize("text", [
        "Шишкин Кирилл и Виктория Шишкина",
        "Кирилл, Виктория",
        "Маша + Петя",
        "Анна и Мария",
    ])
    def test_two_people_recognised(self, text):
        assert names_two_people(text)

    @pytest.mark.parametrize("text", [
        "Михаил",
        "Шишкин Кирилл",
        "Иванов Иван Иванович",   # ФИО одного человека, а не двое
        "россия",
        "Имя Михаил будет",
    ])
    def test_one_person_or_a_phrase_is_not_a_pair(self, text):
        assert not names_two_people(text)


class TestSaidTwoItems:
    @pytest.mark.parametrize("text", [
        "Два свитшота",
        "парные толстовки",
        "две штуки",
        "мне и жене",
        "на двоих",
    ])
    def test_direct_statement(self, text):
        assert wants_two_items(text)

    @pytest.mark.parametrize("text", ["Чёрный", "Два имени будет", "Рост 183, вес 93"])
    def test_other_replies(self, text):
        assert not wants_two_items(text)


class TestSlot:
    def test_two_names_fill_the_pair_slot(self):
        slots = collect_slots([("ai", ASKS), ("client", "Шишкин Кирилл и Виктория Шишкина")])

        assert slots["pair"] == "два изделия"
        # Пять слов в короткий ответ не укладывались, и надпись терялась целиком.
        assert slots["inscription"] == "Шишкин Кирилл и Виктория Шишкина"

    def test_one_name_leaves_it_empty(self):
        slots = collect_slots([("ai", ASKS), ("client", "Михаил")])

        assert "pair" not in slots
        assert slots["inscription"] == "Михаил"

    def test_said_two_items_later_in_the_dialog(self):
        slots = collect_slots([
            ("ai", ASKS),
            ("client", "Михаил"),
            ("ai", "На белом свитшоте разместим имя. Всё верно?"),
            ("client", "Два свитшота"),
        ])

        assert slots["pair"] == "два изделия"


@pytest.fixture
async def scripts(db):
    db.add_all([
        Script(id=367, is_active=True, type_id=1, funnel_stage="pricing",
               condition=COND, phrase_text="Стоимость - 5 990 ₽"),
        Script(id=390, is_active=True, type_id=1, funnel_stage="pricing",
               condition="2.2 Стоимость — ПАРНЫЕ", variant_of_script_id=367,
               is_pair_variant=True, phrase_text="Два изделия со скидкой - 9 990 ₽"),
        Script(id=368, is_active=True, type_id=1, funnel_stage="pricing",
               condition=COND, marketing_tag="hood141",
               phrase_text="Комплект свитшот + жилетка - 8 980 ₽"),
    ])
    await db.flush()
    return db


class TestPairVariant:
    async def test_pair_order_gets_the_pair_price(self, scripts):
        base = await scripts.get(Script, 367)
        picked = await tagged_variant(scripts, base, set(), pair=True)
        assert picked.id == 390

    async def test_single_order_never_gets_it(self, scripts):
        base = await scripts.get(Script, 367)
        picked = await tagged_variant(scripts, base, set(), pair=False)
        assert picked.id == 367

    async def test_pair_wins_over_the_tag_variant(self, scripts):
        base = await scripts.get(Script, 367)
        picked = await tagged_variant(scripts, base, {"hood141"}, pair=True)
        assert picked.id == 390

    async def test_tag_variant_still_works_without_a_pair_script(self, scripts):
        """Парного расчёта в панели ещё нет — клиент получает расчёт под метку,
        а не общий: иначе комплект с жилеткой потерялся бы."""
        pair = await scripts.get(Script, 390)
        pair.is_active = False
        await scripts.flush()
        base = await scripts.get(Script, 367)

        picked = await tagged_variant(scripts, base, {"hood141"}, pair=True)

        assert picked.id == 368

    async def test_the_rule_is_in_the_prompt(self):
        from app.ai.prompts import _SALES_PROMPT_FALLBACK

        assert "## Заказ на двоих" in _SALES_PROMPT_FALLBACK


@pytest.fixture
async def funnel(db):
    """Связка «похвала → стоимость → доставка» и парный расчёт рядом с обычным."""
    from app.db.models import (
        Client, Dialog, DialogType, Message, MessageRole, VkGroup,
    )

    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add_all([
        Script(id=363, is_active=True, type_id=1, funnel_stage="greeting",
               condition="ОБЯЗАТЕЛЬНЫЙ шаг воронки «2. Похвала»",
               phrase_text="Супер, зафиксировала\nСделаем всё как Вы хотите!",
               follow_up_script_id=367),
        Script(id=367, is_active=True, type_id=1, funnel_stage="pricing",
               condition=COND, follow_up_script_id=372,
               phrase_text="Стоимость толстовки - 5 990 ₽"),
        Script(id=372, is_active=True, type_id=1, funnel_stage="pricing",
               condition="2.3 Доставка",
               phrase_text="Шьём по Вашим меркам.\n\nВ какой город нужна будет доставка?"),
        Script(id=390, is_active=True, type_id=1, funnel_stage="pricing",
               condition="2.2 Стоимость — ПАРНЫЕ", variant_of_script_id=367,
               is_pair_variant=True,
               phrase_text="Два изделия со скидкой - 9 990 ₽ (вместо 11 980 ₽)"),
    ])
    group = VkGroup(group_id=44440184, name="Hemilton", access_token="t", confirmation_code="c")
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=90309045, vk_group_id=group.id, name="Кирилл")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=1, funnel_stage="greeting")
    db.add(dialog)
    await db.flush()
    db.add_all([
        Message(dialog_id=dialog.id, role=MessageRole.ai, text=ASKS),
        Message(dialog_id=dialog.id, role=MessageRole.client,
                text="Шишкин Кирилл и Виктория Шишкина"),
    ])
    await db.flush()
    return db, dialog, client


class TestChainSendsThePairPrice:
    async def test_two_names_get_the_pair_calculation(self, funnel):
        from app.ai.runner import build_script_parts

        db, dialog, client = funnel
        praise = await db.get(Script, 363)

        texts = [p.text for p in await build_script_parts(db, dialog, praise, client)]

        assert texts[0].startswith("Супер, зафиксировала")
        assert "9 990 ₽" in texts[1]
        # Доставка идёт следом по общей цепочке: у парного расчёта своего
        # продолжения нет, и без этого звено потерялось бы.
        assert texts[2].endswith("В какой город нужна будет доставка?")

    async def test_one_name_gets_the_usual_calculation(self, funnel):
        from app.ai.runner import build_script_parts
        from app.db.models import Client, Dialog, Message, MessageRole

        db, _first, first_client = funnel
        # Свой клиент: диалог у пары «клиент + направление» может быть только один.
        client = Client(vk_user_id=90309046, vk_group_id=first_client.vk_group_id,
                        name="Михаил")
        db.add(client)
        await db.flush()
        dialog = Dialog(client_id=client.id, type_id=1, funnel_stage="greeting")
        db.add(dialog)
        await db.flush()
        db.add_all([
            Message(dialog_id=dialog.id, role=MessageRole.ai, text=ASKS),
            Message(dialog_id=dialog.id, role=MessageRole.client, text="Михаил"),
        ])
        await db.flush()
        praise = await db.get(Script, 363)

        texts = [p.text for p in await build_script_parts(db, dialog, praise, client)]

        assert "5 990 ₽" in texts[1]
