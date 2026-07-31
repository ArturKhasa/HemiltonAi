"""Связка скриптов: приветствие + вопрос вторым сообщением.

Регламент ОП описывает пару прямо в условиях скриптов — «1. Приветствие» само
вопросом не заканчивается, а «1.2 Вопрос после приветствия» помечен как
«Отправляем сразу после первого скрипта с приветствием». Агент отдаёт за ход одну
реплику, поэтому диалог висел, пока клиент не напишет сам (диалог 9 на проде).
"""
import pytest

from app.ai.runner import _build_follow_up_parts
from app.db.models import Client, Dialog, DialogType, MessageRole, Script
from app.utils.text import render_name_placeholder

GREETING = "[Имя], здравствуйте! Меня зовут София, я Ваш персональный менеджер"
QUESTION = "[Имя], какое имя или фамилию напишем на Вашей кофте?"


@pytest.fixture
async def chain(db):
    """Приветствие со связкой на вопрос + клиент с диалогом."""
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    question = Script(condition="Отправляем сразу после приветствия", phrase_text=QUESTION, type_id=1)
    db.add(question)
    await db.flush()
    greeting = Script(
        condition="Первое приветственное сообщение",
        phrase_text=GREETING,
        type_id=1,
        follow_up_script_id=question.id,
    )
    db.add(greeting)
    client = Client(vk_user_id=650453, name="Лена")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=1)
    db.add(dialog)
    await db.commit()
    return {"greeting": greeting, "question": question, "client": client, "dialog": dialog}


class TestNamePlaceholder:
    def test_cyrillic_name_substituted(self):
        """Уменьшительное разворачивается в полное — см. test_client_name."""
        assert render_name_placeholder(QUESTION, "Лена").startswith("Елена, какое имя")

    def test_latin_name_dropped(self):
        """Латиница/ник — обращаемся без имени, как и требует системный промпт."""
        assert render_name_placeholder(QUESTION, "Max") == "Какое имя или фамилию напишем на Вашей кофте?"

    @pytest.mark.parametrize("name", [None, "", "   ", "xxx123", "🙂"])
    def test_no_usable_name(self, name):
        assert render_name_placeholder(QUESTION, name) == "Какое имя или фамилию напишем на Вашей кофте?"

    def test_text_without_placeholder_untouched(self):
        assert render_name_placeholder("Супер, зафиксировала", "Лена") == "Супер, зафиксировала"


class TestFollowUpPart:
    async def test_chained_script_produces_second_reply(self, db, chain):
        parts = await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        )
        assert len(parts) == 1
        part = parts[0]
        assert part.text == "Елена, какое имя или фамилию напишем на Вашей кофте?"
        assert part.message.role == MessageRole.ai
        assert part.message.msg_metadata["source_script_id"] == chain["question"].id

    async def test_no_chain_no_second_reply(self, db, chain):
        """У вопроса связки нет — разворачивать нечего."""
        assert await _build_follow_up_parts(
            db, chain["dialog"], chain["question"].id, chain["client"], "test"
        ) == []

    async def test_free_form_reply_has_no_follow_up(self, db, chain):
        """Модель ответила без скрипта (source_script_id=None) — связки нет."""
        assert await _build_follow_up_parts(
            db, chain["dialog"], None, chain["client"], "test"
        ) == []

    async def test_deactivated_follow_up_skipped(self, db, chain):
        chain["question"].is_active = False
        await db.commit()
        assert await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        ) == []

    async def test_dangling_reference_skipped(self, db, chain):
        """Скрипт удалили — FK ставит NULL, но подстрахуемся и от битой ссылки."""
        chain["greeting"].follow_up_script_id = 99999
        await db.commit()
        assert await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        ) == []


class TestChainDepth:
    """Воронка ОП — лестница: похвала → стоимость → доставка, каждый шаг помечен
    «отправляем сразу после …». Разворачиваем всю цепочку, но не бесконечно."""

    async def test_multi_link_chain_expanded(self, db, chain):
        third = Script(condition="2.3 Доставка", phrase_text="В какой город доставка?", type_id=1)
        db.add(third)
        await db.flush()
        chain["question"].follow_up_script_id = third.id
        await db.commit()

        parts = await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        )
        assert [p.text for p in parts] == [
            "Елена, какое имя или фамилию напишем на Вашей кофте?",
            "В какой город доставка?",
        ]

    async def test_known_city_link_skipped_chain_continues(self, db, chain):
        """Диалог 52: город назван в 01:11, скрипт доставки спросил его в 01:13.
        Звено с вопросом про город пропускаем, но следующее за ним — отправляем."""
        delivery = Script(condition="2.3 Доставка", phrase_text="В какой город доставка?", type_id=1)
        db.add(delivery)
        await db.flush()
        colour = Script(condition="3. Цвет", phrase_text="Какой цвет выберем?", type_id=1)
        db.add(colour)
        await db.flush()
        chain["question"].follow_up_script_id = delivery.id
        delivery.follow_up_script_id = colour.id
        await db.commit()

        parts = await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test",
            skip_city_question=True,
        )
        assert [p.text for p in parts] == [
            "Елена, какое имя или фамилию напишем на Вашей кофте?",
            "Какой цвет выберем?",
        ]

    async def test_city_link_sent_when_city_unknown(self, db, chain):
        delivery = Script(condition="2.3 Доставка", phrase_text="В какой город доставка?", type_id=1)
        db.add(delivery)
        await db.flush()
        chain["question"].follow_up_script_id = delivery.id
        await db.commit()

        parts = await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test",
            skip_city_question=False,
        )
        assert parts[-1].text == "В какой город доставка?"

    async def test_circular_chain_stops(self, db, chain):
        """Кольцевую ссылку в админке выставить легко — клиент не должен получить
        бесконечную простыню."""
        chain["question"].follow_up_script_id = chain["greeting"].id
        await db.commit()
        parts = await _build_follow_up_parts(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        )
        assert len(parts) <= 4
