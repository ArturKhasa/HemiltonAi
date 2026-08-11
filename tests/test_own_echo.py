"""Собственное эхо не должно приниматься за сообщение живого оператора.

11 августа так замолчали 92 диалога. ВК присылает message_reply о нашей же
отправке через одну-две секунды, а отметки о доставке жили только в памяти до
конца хода — между репликами связки есть пауза. Эхо не опознавалось, писалось в
базу как сообщение оператора, забирало себе VK id, и наш коммит падал на
уникальном индексе (dialog_id, external_message_id) и откатывался вместе с
отметками. Диалог вставал на паузу сам от себя.

В переписке ВК при этом было ОДНО сообщение, а в панели — два: своё и «чужое».
"""
import pytest
from sqlalchemy import func, select

from app.ai.runner import ReplyPart
from app.ai.schemas import AgentOutput
from app.db.models import Client, Dialog, DialogType, Message, MessageRole, VkGroup
from app.vk import sender
from app.vk.outgoing import is_our_echo
from app.vk.sender import SentMessage
from app.vk.webhook import handle_message_new, handle_message_reply, parse_message_event


@pytest.fixture
async def vk_group(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    g = VkGroup(group_id=111222, name="Магазин", access_token="tok", confirmation_code="c")
    db.add(g)
    await db.commit()
    return g


def _event(kind="message_new", text="Начать", message_id=1, random_id=0):
    return {
        "type": kind,
        "group_id": 111222,
        "object": {"message": {
            "from_id": 555 if kind == "message_new" else -111222,
            "peer_id": 555, "text": text, "id": message_id, "random_id": random_id,
        }},
    }


class TestInProcessMemory:
    async def test_random_id_is_remembered_before_the_api_call(self, db, monkeypatch):
        """Ключевой момент: к моменту ответа ВК id уже должен быть наш, иначе
        эхо успевает прийти раньше, чем мы узнаем, чем отправляли."""
        seen: list[bool] = []

        async def _fake_api(token, method, params):
            # Внутри вызова к ВК random_id обязан уже числиться нашим.
            seen.append(sender.is_own_random_id(params["random_id"]))
            return 800

        monkeypatch.setattr(sender, "vk_api_call", _fake_api)

        await sender.send_message("tok", 42, "Здравствуйте!", vk_group_id=1)

        assert seen == [True]

    async def test_our_echo_is_recognised_without_any_database_state(self, db, vk_group):
        """Именно этого не хватало: в базе отметок ещё нет, а решение нужно уже."""
        c = Client(vk_user_id=555, vk_group_id=vk_group.id)
        db.add(c)
        await db.flush()
        d = Dialog(client_id=c.id, type_id=1)
        db.add(d)
        await db.commit()

        sender.remember_random_id(1716504693)

        assert await is_our_echo(db, d.id, 1716504693, "162188") is True
        assert await is_our_echo(db, d.id, 1741129106, "162188") is False

    def test_memory_is_bounded(self):
        """Множество не должно расти бесконечно в долгоживущем процессе."""
        limit = sender._OUR_RANDOM_IDS.maxlen
        for i in range(limit + 50):
            sender.remember_random_id(10_000_000 + i)

        assert len(sender._OUR_RANDOM_IDS_SET) <= limit
        assert sender.is_own_random_id(10_000_000 + limit + 49)


@pytest.fixture
def offline_ai(monkeypatch):
    """Прогон модели подменяем целиком.

    Настоящий run_ai открывает СВОЮ сессию к базе из DATABASE_URL (инструменты
    агента ходят мимо тестовой сессии), и на чистой машине без постгреса тест
    падает с OSError вместо проверки того, ради чего написан.
    """
    async def _fake_run_ai(db_, dialog, client_message):
        m = Message(dialog_id=dialog.id, role=MessageRole.ai, text="Здравствуйте!")
        db_.add(m)
        await db_.flush()
        await db_.commit()
        return (
            AgentOutput(reply_text="Здравствуйте!", confidence_score=1.0),
            None,
            [ReplyPart(text="Здравствуйте!", image_urls=[], message=m)],
        )

    monkeypatch.setattr("app.ai.runner.run_ai", _fake_run_ai)


@pytest.fixture
def offline_vk(monkeypatch):
    """ВК тоже наружу не ходит: возвращаем фиксированный id сообщения."""
    async def _fake_api(token, method, params):
        return 162188

    monkeypatch.setattr(sender, "vk_api_call", _fake_api)


class TestEndToEnd:
    async def test_greeting_echo_does_not_pause_the_dialog(
        self, db, vk_group, offline_ai, offline_vk,
    ):
        """Диалог 221, 11 августа: клиенту ушло приветствие, ВК вернул его эхом,
        и бот замолчал сам от себя, а в панели появился фантомный «менеджер»."""
        await handle_message_new(db, vk_group, parse_message_event(_event()))

        # ВК возвращает наше же сообщение как исходящее сообщества.
        our_rid = sender._OUR_RANDOM_IDS[-1]
        echo = parse_message_event(_event(
            "message_reply", text="Здравствуйте!", message_id=162188, random_id=our_rid,
        ))
        echo.peer_id = 555
        await handle_message_reply(db, vk_group, echo)

        dialog = (await db.execute(select(Dialog))).scalars().first()
        assert dialog.ai_paused is False
        n_curator = await db.scalar(
            select(func.count()).select_from(Message).where(Message.role == MessageRole.curator)
        )
        assert n_curator == 0

    async def test_a_real_operator_still_pauses_the_dialog(
        self, db, vk_group, offline_ai, offline_vk,
    ):
        """Проверка, что лекарство не убило само лечение."""
        await handle_message_new(db, vk_group, parse_message_event(_event()))

        foreign = parse_message_event(_event(
            "message_reply", text="Здравствуйте, я подключилась",
            message_id=999, random_id=1741129106,
        ))
        foreign.peer_id = 555
        await handle_message_reply(db, vk_group, foreign)

        dialog = (await db.execute(select(Dialog))).scalars().first()
        assert dialog.ai_paused is True
