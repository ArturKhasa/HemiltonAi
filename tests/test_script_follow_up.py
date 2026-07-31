"""Связка скриптов: приветствие + вопрос вторым сообщением.

Регламент ОП описывает пару прямо в условиях скриптов — «1. Приветствие» само
вопросом не заканчивается, а «1.2 Вопрос после приветствия» помечен как
«Отправляем сразу после первого скрипта с приветствием». Агент отдаёт за ход одну
реплику, поэтому диалог висел, пока клиент не напишет сам (диалог 9 на проде).
"""
import pytest

from app.ai.runner import _build_follow_up_part
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
        part = await _build_follow_up_part(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        )
        assert part is not None
        assert part.text == "Елена, какое имя или фамилию напишем на Вашей кофте?"
        assert part.message.role == MessageRole.ai
        assert part.message.msg_metadata["follow_up_script_id"] == chain["question"].id

    async def test_no_chain_no_second_reply(self, db, chain):
        """У вопроса связки нет — цепочка однозвенная, дальше не разворачиваем."""
        assert await _build_follow_up_part(
            db, chain["dialog"], chain["question"].id, chain["client"], "test"
        ) is None

    async def test_free_form_reply_has_no_follow_up(self, db, chain):
        """Модель ответила без скрипта (source_script_id=None) — связки нет."""
        assert await _build_follow_up_part(
            db, chain["dialog"], None, chain["client"], "test"
        ) is None

    async def test_deactivated_follow_up_skipped(self, db, chain):
        chain["question"].is_active = False
        await db.commit()
        assert await _build_follow_up_part(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        ) is None

    async def test_dangling_reference_skipped(self, db, chain):
        """Скрипт удалили — FK ставит NULL, но подстрахуемся и от битой ссылки."""
        chain["greeting"].follow_up_script_id = 99999
        await db.commit()
        assert await _build_follow_up_part(
            db, chain["dialog"], chain["greeting"].id, chain["client"], "test"
        ) is None
