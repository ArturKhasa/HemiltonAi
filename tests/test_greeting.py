"""Приветствие отдаётся кодом дословно, а не пересказывается моделью.

Диалог 13 на проде: модель получила скрипт #358 со всеми токенами [photo-...] и
отправила собственный пересказ — без фото, без строчки про любовь к родине, зато
с вклеенным вопросом из другого скрипта. И поздоровалась ещё раз на третьем ходу.
"""
import pytest

from app.ai.greeting import pick_greeting_script, resolve_greeting
from app.db.models import Client, Dialog, DialogType, Message, MessageRole, Script
from app.utils.text import strip_repeated_greeting

GREETING_CONDITION = "Первое приветственное сообщение, отправляем всем новым клиентом"
GREETING_TEXT = "[Имя], здравствуйте! Меня зовут София\n\n[photo-https://ex.test/a.jpg]"


@pytest.fixture
async def setup(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    scripts = {}
    for sid, tag in [(358, None), (359, None), (400, "sweetgold")]:
        s = Script(id=sid, condition=GREETING_CONDITION, phrase_text=GREETING_TEXT,
                   marketing_tag=tag, funnel_stage="greeting", type_id=1)
        db.add(s)
        scripts[sid] = s
    db.add(Script(id=500, condition="Отработка возражения дорого",
                  phrase_text="Понимаю", type_id=1))
    client = Client(vk_user_id=1, name="Лена")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=1)
    db.add(dialog)
    await db.commit()
    return {"scripts": scripts, "client": client, "dialog": dialog}


class TestPickGreeting:
    async def test_untagged_client_gets_lowest_id(self, db, setup):
        """В выгрузке несколько одинаковых приветствий без тега — выбор обязан
        быть воспроизводимым, а не «какое модель захотела»."""
        s = await pick_greeting_script(db, 1, setup["client"])
        assert s.id == 358

    async def test_tag_wins_over_untagged(self, db, setup):
        setup["client"].marketing_tags = ["sweetgold"]
        await db.commit()
        s = await pick_greeting_script(db, 1, setup["client"])
        assert s.id == 400

    async def test_unknown_tag_falls_back_to_untagged(self, db, setup):
        setup["client"].marketing_tags = ["несуществующий"]
        await db.commit()
        s = await pick_greeting_script(db, 1, setup["client"])
        assert s.id == 358

    async def test_inactive_greeting_ignored(self, db, setup):
        for s in setup["scripts"].values():
            s.is_active = False
        await db.commit()
        assert await pick_greeting_script(db, 1, setup["client"]) is None

    async def test_non_greeting_script_never_picked(self, db, setup):
        for s in setup["scripts"].values():
            s.is_active = False
        await db.commit()
        assert await pick_greeting_script(db, 1, setup["client"]) is None


class TestResolveGreeting:
    async def test_first_turn_uses_script(self, db, setup):
        assert (await resolve_greeting(db, setup["dialog"], setup["client"], 1)).id == 358

    async def test_second_turn_goes_to_model(self, db, setup):
        db.add(Message(dialog_id=setup["dialog"].id, role=MessageRole.ai, text="Здравствуйте!"))
        await db.commit()
        assert await resolve_greeting(db, setup["dialog"], setup["client"], 1) is None

    async def test_curator_message_also_counts_as_outgoing(self, db, setup):
        db.add(Message(dialog_id=setup["dialog"].id, role=MessageRole.curator, text="Привет"))
        await db.commit()
        assert await resolve_greeting(db, setup["dialog"], setup["client"], 1) is None

    async def test_client_message_does_not_count(self, db, setup):
        db.add(Message(dialog_id=setup["dialog"].id, role=MessageRole.client, text="Начать"))
        await db.commit()
        assert (await resolve_greeting(db, setup["dialog"], setup["client"], 1)) is not None


class TestStripRepeatedGreeting:
    def test_prod_regression_dialog_13(self):
        """Ровно то, что пришло клиенту третьим сообщением."""
        got = strip_repeated_greeting(
            "Здравствуйте! Меня зовут София, я Ваш персональный менеджер. "
            "Свитшот или худи с термопринтом сегодня стоит 4 990 ₽."
        )
        assert got == "Свитшот или худи с термопринтом сегодня стоит 4 990 ₽."

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Добрый день! Цена 4990₽", "Цена 4990₽"),
            ("Привет, записала размер", "Записала размер"),
            ("Здравствуйте. Какой цвет?", "Какой цвет?"),
        ],
    )
    def test_variants(self, text, expected):
        assert strip_repeated_greeting(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Записала размер, всё верно?",
            "Свитшот стоит 4990₽",
            "Передайте привет мужу",          # приветствие не в начале — не трогаем
        ],
    )
    def test_untouched(self, text):
        assert strip_repeated_greeting(text) == text

    def test_greeting_only_message_kept(self):
        """Срезать всё — значит отправить пустоту; лишнее «здравствуйте» меньшее зло."""
        assert strip_repeated_greeting("Здравствуйте!") == "Здравствуйте!"
