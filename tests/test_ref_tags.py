"""Белый список ref-меток.

Заказчик: «админка, где указываются реф метки, на которые ИИ будет отвечать» —
трафик с неизвестной метки ведёт человек. Ссылка выглядит как
?ref=adb_r&ref_source=rusover449, кампания во втором параметре.
"""
import pytest

from app.ai.greeting import pick_greeting_script
from app.db.models import Client, DialogType, RefTag, Script
from app.sales.ref_tags import RefTagService
from app.vk.webhook import parse_message_event


@pytest.fixture
async def svc(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    await db.commit()
    return RefTagService(db)


class TestWhitelistBootstrap:
    async def test_empty_list_allows_everyone(self, db, svc):
        """Пока меток не завели, список не применяется — иначе выкатка разом
        оборвала бы все живые диалоги."""
        assert await svc.ai_allowed("rusover449", 1) is True
        assert await svc.ai_allowed(None, 1) is True

    async def test_list_starts_working_after_first_tag(self, db, svc):
        await svc.create("rusover449", type_id=1)
        await db.commit()
        assert await svc.ai_allowed("rusover449", 1) is True
        assert await svc.ai_allowed("другая", 1) is False
        # Приход без метки — отдельный случай, см. TestUntaggedSwitch.
        assert await svc.ai_allowed(None, 1) is True

    async def test_disabled_tag_blocks_ai(self, db, svc):
        await svc.create("rusover449", type_id=1, is_active=False)
        await db.commit()
        assert await svc.ai_allowed("rusover449", 1) is False


class TestGreetingBinding:
    @pytest.fixture
    async def scripts(self, db, svc):
        default = Script(id=10, condition="Первое приветственное сообщение",
                         phrase_text="Общее приветствие", type_id=1)
        campaign = Script(id=11, condition="Первое приветственное сообщение",
                          phrase_text="Приветствие кампании", type_id=1)
        db.add_all([default, campaign])
        await db.commit()
        return {"default": default, "campaign": campaign}

    async def test_bound_greeting_wins(self, db, svc, scripts):
        await svc.create("rusover449", type_id=1, greeting_script_id=11)
        client = Client(vk_user_id=1, name="Ирина", marketing_tags=["rusover449"])
        db.add(client)
        await db.commit()
        assert (await pick_greeting_script(db, 1, client)).id == 11

    async def test_falls_back_when_binding_inactive(self, db, svc, scripts):
        """Привязанное приветствие выключили — клиент получает общее, а не тишину."""
        scripts["campaign"].is_active = False
        await svc.create("rusover449", type_id=1, greeting_script_id=11)
        client = Client(vk_user_id=2, name="Ирина", marketing_tags=["rusover449"])
        db.add(client)
        await db.commit()
        assert (await pick_greeting_script(db, 1, client)).id == 10

    async def test_unbound_tag_uses_general_rule(self, db, svc, scripts):
        await svc.create("rusover449", type_id=1)
        client = Client(vk_user_id=3, name="Ирина", marketing_tags=["rusover449"])
        db.add(client)
        await db.commit()
        assert (await pick_greeting_script(db, 1, client)).id == 10


class TestRefParsing:
    def test_campaign_read_from_ref_source(self):
        """В ?ref=adb_r&ref_source=rusover449 кампания — во втором параметре;
        ref несёт тип площадки, общий для всей рекламы."""
        event = {
            "type": "message_new", "group_id": 1, "secret": "s",
            "object": {"message": {"id": 1, "from_id": 5, "peer_id": 5, "text": "привет",
                                   "random_id": 0, "attachments": [],
                                   "ref": "adb_r", "ref_source": "rusover449"}},
        }
        assert parse_message_event(event).ref == "rusover449"

    def test_falls_back_to_ref(self):
        event = {
            "type": "message_new", "group_id": 1, "secret": "s",
            "object": {"message": {"id": 1, "from_id": 5, "peer_id": 5, "text": "привет",
                                   "random_id": 0, "attachments": [], "ref": "adb_r"}},
        }
        assert parse_message_event(event).ref == "adb_r"


class TestUntaggedSwitch:
    """ВК присылает ref только в первом сообщении, поэтому без метки приходят и
    живые клиенты — из поиска по группе, по ссылке без параметров, старые. Их
    судьбу решает настройка направления, а не белый список."""

    @pytest.fixture
    async def with_tag(self, db, svc):
        await svc.create("rusover449", type_id=1)
        await db.commit()
        return svc

    async def test_untagged_served_by_default(self, db, with_tag):
        assert await with_tag.ai_allowed(None, 1) is True

    async def test_untagged_blocked_when_switched_off(self, db, with_tag):
        dt = await db.get(DialogType, 1)
        dt.answer_untagged = False
        await db.commit()
        assert await with_tag.ai_allowed(None, 1) is False

    async def test_foreign_tag_blocked_regardless(self, db, with_tag):
        """Чужая реклама блокируется всегда — галка её не касается."""
        dt = await db.get(DialogType, 1)
        dt.answer_untagged = True
        await db.commit()
        assert await with_tag.ai_allowed("чужая-кампания", 1) is False
