"""VK Callback API: confirmation, secret, message_new (дедуп), message_reply (пауза ИИ)."""
import pytest
from sqlalchemy import func, select

from app.ai.runner import ReplyPart
from app.ai.schemas import AgentOutput
from app.db.models import AIRun, Client, Dialog, DialogType, Message, MessageRole, VkGroup
from app.vk.sender import SentMessage
from app.vk.webhook import (
    handle_message_new,
    handle_message_reply,
    parse_message_event,
)


@pytest.fixture
async def vk_group(db):
    dt = DialogType(name="clothes", display_name="Одежда")
    db.add(dt)
    await db.flush()
    group = VkGroup(
        group_id=111222,
        name="Магазин одежды",
        access_token="vk1.a.test-token",
        confirmation_code="confirm123",
        secret_key="s3cret",
        dialog_type_id=dt.id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


def _event(event_type="message_new", *, group_id=111222, secret="s3cret",
           from_id=555, text="Здравствуйте, есть размер M?", message_id=42,
           random_id=0, attachments=None):
    return {
        "type": event_type,
        "group_id": group_id,
        "secret": secret,
        "object": {
            "message": {
                "id": message_id,
                "from_id": from_id,
                "peer_id": from_id,
                "text": text,
                "random_id": random_id,
                "attachments": attachments or [],
            }
        },
    }


# --- Эндпоинт -----------------------------------------------------------------


async def test_confirmation_returns_code(client, vk_group):
    resp = await client.post("/webhook/vk", json={"type": "confirmation", "group_id": 111222})
    assert resp.status_code == 200
    assert resp.text == "confirm123"


async def test_unknown_group_404(client, db):
    resp = await client.post("/webhook/vk", json={"type": "confirmation", "group_id": 999})
    assert resp.status_code == 404


async def test_bad_secret_403(client, vk_group):
    resp = await client.post("/webhook/vk", json=_event(secret="wrong"))
    assert resp.status_code == 403


async def test_message_new_acks_and_schedules(client, vk_group, monkeypatch):
    scheduled = []
    monkeypatch.setattr("app.api.vk.schedule_event", lambda pk, payload: scheduled.append((pk, payload)))
    resp = await client.post("/webhook/vk", json=_event())
    assert resp.status_code == 200
    assert resp.text == "ok"
    assert len(scheduled) == 1
    assert scheduled[0][0] == vk_group.id


# --- Обработчики --------------------------------------------------------------


@pytest.fixture
def fake_ai(monkeypatch):
    """run_ai создаёт реальный AIRun (нужен дедупу) и возвращает готовый ответ."""
    calls = []

    async def _fake_run_ai(db, dialog, client_message):
        calls.append(client_message.id)
        run = AIRun(
            dialog_id=dialog.id,
            input_message_id=client_message.id,
            provider="test",
            model="test",
        )
        db.add(run)
        reply = Message(dialog_id=dialog.id, role=MessageRole.ai, text="Да, есть в наличии!")
        db.add(reply)
        await db.commit()
        run.output_message_id = reply.id
        output = AgentOutput(reply_text="Да, есть в наличии!", confidence_score=0.95)
        return output, run, [ReplyPart(text=reply.text, image_urls=[], message=reply)]

    monkeypatch.setattr("app.ai.runner.run_ai", _fake_run_ai)
    return calls


@pytest.fixture
def fake_sender(monkeypatch):
    sent = []

    async def _fake_send(db, dialog, text):
        sent.append((dialog.id, text))
        # Настоящий ВК выдаёт каждому сообщению свой id; на повторяющемся падает
        # уникальный индекс (dialog_id, external_message_id), которым дедуплицируются
        # вебхуки, — так что счётчик тут не украшение.
        return SentMessage(message_id=800 + len(sent), random_ids=[900 + len(sent)])

    monkeypatch.setattr("app.messaging.send_to_dialog", _fake_send)
    return sent


async def test_message_new_creates_entities_and_sends(db, vk_group, fake_ai, fake_sender):
    msg = parse_message_event(_event())
    await handle_message_new(db, vk_group, msg)

    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert client is not None
    assert client.vk_group_id == vk_group.id

    dialog = await db.scalar(select(Dialog).where(Dialog.client_id == client.id))
    assert dialog is not None
    assert dialog.type_id == vk_group.dialog_type_id

    messages = (await db.execute(
        select(Message).where(Message.dialog_id == dialog.id).order_by(Message.id)
    )).scalars().all()
    assert messages[0].role == MessageRole.client
    assert messages[0].external_message_id == "42"

    assert fake_ai == [messages[0].id]
    assert fake_sender == [(dialog.id, "Да, есть в наличии!")]


async def test_message_new_sends_every_reply_part(db, vk_group, fake_sender, monkeypatch):
    """Связка скриптов (приветствие + вопрос) уходит двумя сообщениями подряд,
    каждое со своим VK id — иначе message_reply о нашей же отправке не отличить
    от сообщения живого оператора."""
    monkeypatch.setattr("app.vk.webhook.FOLLOW_UP_DELAY_SECONDS", 0)

    async def _two_part_run_ai(db_, dialog, client_message):
        run = AIRun(dialog_id=dialog.id, input_message_id=client_message.id,
                    provider="test", model="test")
        db_.add(run)
        parts = []
        for text in ("Здравствуйте! Меня зовут София", "Какое имя напишем на кофте?"):
            m = Message(dialog_id=dialog.id, role=MessageRole.ai, text=text)
            db_.add(m)
            parts.append(m)
        await db_.commit()
        run.output_message_id = parts[0].id
        output = AgentOutput(reply_text=parts[0].text, confidence_score=0.95)
        return output, run, [ReplyPart(text=m.text, image_urls=[], message=m) for m in parts]

    monkeypatch.setattr("app.ai.runner.run_ai", _two_part_run_ai)
    await handle_message_new(db, vk_group, parse_message_event(_event()))

    dialog = (await db.execute(select(Dialog))).scalars().first()
    assert fake_sender == [
        (dialog.id, "Здравствуйте! Меня зовут София"),
        (dialog.id, "Какое имя напишем на кофте?"),
    ]
    ai_msgs = (await db.execute(
        select(Message).where(Message.role == MessageRole.ai).order_by(Message.id)
    )).scalars().all()
    assert [m.external_message_id for m in ai_msgs] == ["801", "802"]


async def test_ref_link_tags_new_client(db, vk_group, fake_ai, fake_sender):
    """Тег рекламной ссылки = marketing_tag скриптов: по нему list_scripts выбирает
    приветствие под конкретную рекламу. Раньше теги не проставлялись никогда, и
    все клиенты шли как безтеговые."""
    event = _event()
    event["object"]["message"]["ref"] = "sweetgold"
    await handle_message_new(db, vk_group, parse_message_event(event))

    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert client.marketing_tags == ["sweetgold"]


async def test_ref_backfilled_on_existing_untagged_client(db, vk_group, fake_ai, fake_sender):
    """ВК присылает ref только в первом сообщении; если клиент уже заведён без
    тега, проставляем задним числом."""
    await handle_message_new(db, vk_group, parse_message_event(_event()))
    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert client.marketing_tags is None

    event = _event(message_id=43, text="а сколько стоит?")
    event["object"]["message"]["ref"] = "ПАВЕЛ_ПАТРИОТ_1"
    await handle_message_new(db, vk_group, parse_message_event(event))

    await db.refresh(client)
    assert client.marketing_tags == ["ПАВЕЛ_ПАТРИОТ_1"]


async def test_existing_tag_not_overwritten(db, vk_group, fake_ai, fake_sender):
    """Клиент закреплён за первой рекламой, по которой пришёл."""
    first = _event()
    first["object"]["message"]["ref"] = "sweetgold"
    await handle_message_new(db, vk_group, parse_message_event(first))

    second = _event(message_id=43, text="ещё вопрос")
    second["object"]["message"]["ref"] = "sweetwhite"
    await handle_message_new(db, vk_group, parse_message_event(second))

    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert client.marketing_tags == ["sweetgold"]


def test_ref_absent_parses_as_none():
    assert parse_message_event(_event()).ref is None


async def test_message_new_dedup_skips_retry(db, vk_group, fake_ai, fake_sender):
    msg = parse_message_event(_event())
    await handle_message_new(db, vk_group, msg)
    # ВК ретраит то же событие — второй прогон не должен породить второй AIRun.
    await handle_message_new(db, vk_group, parse_message_event(_event()))

    assert len(fake_ai) == 1
    n_client_msgs = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.client)
    )
    assert n_client_msgs == 1


async def test_message_new_ai_paused_saves_but_no_ai(db, vk_group, fake_ai, fake_sender):
    first = parse_message_event(_event())
    await handle_message_new(db, vk_group, first)
    dialog = (await db.execute(select(Dialog))).scalars().first()
    dialog.ai_paused = True
    await db.commit()

    second = parse_message_event(_event(message_id=43, text="А доставка есть?"))
    await handle_message_new(db, vk_group, second)

    assert len(fake_ai) == 1  # второй ран не запускался
    n_client_msgs = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.client)
    )
    assert n_client_msgs == 2  # но сообщение сохранено


async def test_message_reply_operator_pauses_ai(db, vk_group, fake_ai, fake_sender):
    # Клиент написал — диалог существует.
    await handle_message_new(db, vk_group, parse_message_event(_event()))
    # Живой оператор ответил из интерфейса ВК. random_id у него НЕнулевой —
    # его проставляет клиент ВК, а не только мы; раньше по этому признаку
    # сообщение отбрасывалось и роль curator не появлялась никогда.
    reply = parse_message_event(_event(
        "message_reply", from_id=-111222, text="Оператор на связи", message_id=99,
        random_id=777001,
    ))
    reply.peer_id = 555
    await handle_message_reply(db, vk_group, reply)

    dialog = (await db.execute(select(Dialog))).scalars().first()
    assert dialog.ai_paused is True
    curator_msg = await db.scalar(select(Message).where(Message.role == MessageRole.curator))
    assert curator_msg is not None
    assert curator_msg.text == "Оператор на связи"


async def test_broadcast_reply_is_marked_in_the_message(db, vk_group, fake_ai, fake_sender):
    """Рассылку помечаем в базе: в её тексте бывает цена, и лестница статусов
    иначе прочитает рекламное письмо как отправленный клиенту расчёт
    («ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА» ушла в 58 238 диалогов)."""
    from app.vk.broadcast import reset

    reset()
    await handle_message_new(db, vk_group, parse_message_event(_event()))
    mailing = "💥ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА"
    # Тот же текст уже разлетелся по другим диалогам — с этого момента он
    # опознаётся как рассылка (порог — 10 диалогов).
    from app.vk.broadcast import is_broadcast

    for other in range(1000, 1015):
        is_broadcast(mailing, other)

    reply = parse_message_event(_event(
        "message_reply", from_id=-111222, text=mailing, message_id=98, random_id=777002,
    ))
    reply.peer_id = 555
    await handle_message_reply(db, vk_group, reply)

    dialog = (await db.execute(select(Dialog))).scalars().first()
    # Рассылка не забирает диалог у ИИ — это проверялось и раньше.
    assert dialog.ai_paused is False
    msg = await db.scalar(select(Message).where(Message.role == MessageRole.curator))
    assert msg is not None and msg.msg_metadata.get("broadcast") is True
    reset()


async def test_message_reply_own_api_send_ignored(db, vk_group, fake_ai, fake_sender):
    await handle_message_new(db, vk_group, parse_message_event(_event()))
    # Эхо нашей же отправки: random_id совпадает с тем, которым мы отправляли
    # (fake_sender вернул 901 на первую отправку).
    reply = parse_message_event(_event(
        "message_reply", from_id=-111222, text="Да, есть в наличии!", message_id=100,
        random_id=901,
    ))
    reply.peer_id = 555
    await handle_message_reply(db, vk_group, reply)

    dialog = (await db.execute(select(Dialog))).scalars().first()
    assert dialog.ai_paused is False
    n_curator = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.curator)
    )
    assert n_curator == 0


# --- Парсинг ------------------------------------------------------------------


def test_parse_message_event_photo_attachment():
    event = _event(text="", attachments=[{
        "type": "photo",
        "photo": {"sizes": [
            {"width": 100, "height": 100, "url": "http://img/small.jpg"},
            {"width": 800, "height": 600, "url": "http://img/big.jpg"},
        ]},
    }])
    msg = parse_message_event(event)
    assert msg.files == ["http://img/big.jpg"]
    assert msg.text == "[фото]"


def test_parse_message_event_empty_returns_none():
    assert parse_message_event(_event(text="")) is None
