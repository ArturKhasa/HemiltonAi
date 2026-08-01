"""Первое сообщение редактируется у самой метки.

Заказчик: «их проставляют и редактируют постоянно + редактирование первых
сообщений». Приветствия из выгрузки ОП разделены между метками, поэтому правка
«под одну метку» не должна молча менять текст остальным.
"""
import pytest

from app.db.models import DialogType, RefTag, Script
from app.sales.ref_tags import RefTagService

GREETING_CONDITION = "Первое приветственное сообщение, отправляем всем новым клиентам"


@pytest.fixture
async def tags(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    question = Script(condition="Вопрос после приветствия", phrase_text="[Имя], какое имя?", type_id=1)
    db.add(question)
    await db.flush()
    shared = Script(
        condition=GREETING_CONDITION,
        phrase_text="Общее приветствие",
        type_id=1,
        follow_up_script_id=question.id,
    )
    db.add(shared)
    await db.flush()
    first = RefTag(tag="rusover449", type_id=1, greeting_script_id=shared.id)
    second = RefTag(tag="rusover450", type_id=1, greeting_script_id=shared.id)
    lonely = RefTag(tag="solo", type_id=1)
    db.add_all([first, second, lonely])
    await db.commit()
    return {"shared": shared, "question": question, "first": first, "second": second, "lonely": lonely}


class TestSetGreetingText:
    async def test_own_script_edited_in_place(self, db, tags):
        """У метки свой скрипт — правим его, лишних копий не плодим."""
        svc = RefTagService(db)
        await svc.set_greeting_text(tags["lonely"], "Первый текст")
        await db.commit()
        script_id = tags["lonely"].greeting_script_id

        await svc.set_greeting_text(tags["lonely"], "Второй текст")
        await db.commit()
        assert tags["lonely"].greeting_script_id == script_id
        assert (await db.get(Script, script_id)).phrase_text == "Второй текст"

    async def test_shared_script_is_copied_not_mutated(self, db, tags):
        svc = RefTagService(db)
        await svc.set_greeting_text(tags["first"], "Только для rusover449")
        await db.commit()

        assert tags["first"].greeting_script_id != tags["shared"].id
        assert (await db.get(Script, tags["shared"].id)).phrase_text == "Общее приветствие"
        assert tags["second"].greeting_script_id == tags["shared"].id

    async def test_copy_keeps_the_follow_up_question(self, db, tags):
        """За приветствием связкой уходит вопрос про имя — копия не должна его потерять."""
        svc = RefTagService(db)
        await svc.set_greeting_text(tags["lonely"], "Своё приветствие")
        await db.commit()
        script = await db.get(Script, tags["lonely"].greeting_script_id)
        assert script.follow_up_script_id == tags["question"].id

    async def test_new_script_is_findable_as_a_greeting(self, db, tags):
        """Условие должно содержать маркер: по нему приветствие ищет
        app.ai.greeting.pick_greeting_script, если метка отвяжется."""
        svc = RefTagService(db)
        await svc.set_greeting_text(tags["lonely"], "Своё приветствие")
        await db.commit()
        script = await db.get(Script, tags["lonely"].greeting_script_id)
        assert "первое приветственное" in script.condition.lower()
        assert script.is_active and script.type_id == 1

    async def test_empty_text_falls_back_to_common_greeting(self, db, tags):
        svc = RefTagService(db)
        await svc.set_greeting_text(tags["first"], "")
        await db.commit()
        assert tags["first"].greeting_script_id is None

    async def test_reported_text_matches_the_script(self, db, tags):
        svc = RefTagService(db)
        assert await svc.greeting_text(tags["first"]) == "Общее приветствие"
        assert await svc.greeting_text(tags["lonely"]) is None


class TestSharedCount:
    async def test_counts_only_other_tags(self, db, tags):
        svc = RefTagService(db)
        assert await svc.greeting_shared_with(tags["first"]) == 1
        assert await svc.greeting_shared_with(tags["lonely"]) == 0

    async def test_zero_after_getting_an_own_copy(self, db, tags):
        svc = RefTagService(db)
        await svc.set_greeting_text(tags["first"], "Своё")
        await db.commit()
        assert await svc.greeting_shared_with(tags["first"]) == 0
        assert await svc.greeting_shared_with(tags["second"]) == 0
