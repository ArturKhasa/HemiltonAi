"""Приветствие под рекламную метку без текста берёт текст общего.

В админку под метку загружают её картинки, а поле текста оставляют пустым —
«текст же есть по умолчанию». Клиент с метки aigerb1 получил три фото и сразу
вопрос про имя, без единой строчки приветствия (21:33).
"""
import pytest

from app.ai.greeting import greeting_text
from app.db.models import Script

DEFAULT = (
    "Здравствуйте! Меня зовут София, я Ваш персональный менеджер\n\n"
    "У нас Вы можете создать толстовку с любым дизайном.\n\n"
    "[photo-https://example.ru/media/greeting/default.jpg]"
)


@pytest.fixture
async def default_greeting(db):
    s = Script(
        type_id=1, is_active=True, funnel_stage="greeting",
        condition="Первое приветственное сообщение", phrase_text=DEFAULT,
    )
    db.add(s)
    await db.commit()
    return s


async def _add(db, **fields):
    s = Script(type_id=1, is_active=True, funnel_stage="greeting", **fields)
    db.add(s)
    await db.commit()
    return s


class TestGreetingText:
    async def test_pictures_only_greeting_borrows_the_default_text(self, db, default_greeting):
        tagged = await _add(
            db,
            condition="Первое приветственное сообщение, реф-метка aigerb1",
            phrase_text="[photo-https://ai.example.ru/media/greeting/a.jpg]\n"
                        "[photo-https://ai.example.ru/media/greeting/b.jpg]",
        )
        got = await greeting_text(db, tagged, 1)
        assert got.startswith("Здравствуйте! Меня зовут София")
        # Картинки — меткины, чужую из общего приветствия не тащим.
        assert "media/greeting/a.jpg" in got and "media/greeting/b.jpg" in got
        assert "default.jpg" not in got

    async def test_greeting_with_its_own_text_is_untouched(self, db, default_greeting):
        tagged = await _add(
            db,
            condition="Первое приветственное сообщение, реф-метка aigerb2",
            phrase_text="Свой текст под рекламу\n\n[photo-https://ai.example.ru/x.jpg]",
        )
        assert await greeting_text(db, tagged, 1) == tagged.phrase_text

    async def test_default_itself_is_returned_as_is(self, db, default_greeting):
        assert await greeting_text(db, default_greeting, 1) == DEFAULT

    async def test_without_a_default_the_pictures_go_alone(self, db):
        """Общего приветствия нет — отправляем что есть, молча не пропадаем."""
        tagged = await _add(
            db,
            condition="Первое приветственное сообщение, реф-метка aigerb3",
            phrase_text="[photo-https://ai.example.ru/y.jpg]",
        )
        assert await greeting_text(db, tagged, 1) == "[photo-https://ai.example.ru/y.jpg]"

    async def test_default_without_words_is_not_used_as_a_source(self, db):
        """Общее приветствие само из одних картинок — подставлять нечего."""
        await _add(
            db,
            condition="Первое приветственное сообщение",
            phrase_text="[photo-https://example.ru/only-picture.jpg]",
        )
        tagged = await _add(
            db,
            condition="Первое приветственное сообщение, реф-метка aigerb4",
            phrase_text="[photo-https://ai.example.ru/z.jpg]",
        )
        got = await greeting_text(db, tagged, 1)
        assert got == "[photo-https://ai.example.ru/z.jpg]"
