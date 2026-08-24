"""Отправка в MAX: вложения по ссылке, разбивка длинного текста, диспетчер платформ."""
import pytest

from app.db.models import Client, Dialog, DialogType, VkGroup
from app.max import client as max_api
from app.max import sender as max_sender
from app.max.client import MaxMessagesForbiddenError, MaxSentMessage
from app.messaging import MessagesForbiddenError, send_to_dialog
from app.vk.sender import VkMessagesForbiddenError


# --- Вложения -----------------------------------------------------------------


def test_photo_token_becomes_url_attachment():
    """MAX забирает картинку по ссылке сам — перезаливать, как в ВК, не нужно."""
    text, attachments = max_sender.build_attachments(
        "Вот наш свитшот [photo-https://cdn/1.jpg] — нравится?"
    )
    assert attachments == [
        {"type": "image", "payload": {"url": "https://cdn/1.jpg"}},
    ]
    assert "[photo-" not in text and "https://cdn/1.jpg" not in text


def test_doc_and_video_tokens_get_their_types():
    _, attachments = max_sender.build_attachments(
        "[video-https://cdn/clip.mp4][doc-https://cdn/size.pdf]"
    )
    assert [a["type"] for a in attachments] == ["video", "file"]


def test_token_without_url_is_stripped():
    """Мёртвый VK-id и выдумка модели прикрепить нечем — клиент не должен их видеть."""
    text, attachments = max_sender.build_attachments(
        "Смотрите: [photo-44440184_457423551] и [photo-фиолетовый свитшот]"
    )
    assert attachments == []
    assert "[photo" not in text


def test_attachments_capped_at_platform_limit():
    text = " ".join(f"[photo-https://cdn/{i}.jpg]" for i in range(20))
    _, attachments = max_sender.build_attachments(text)
    assert len(attachments) == 12


# --- Отправка -----------------------------------------------------------------


async def test_long_text_is_split_by_max_limit(monkeypatch):
    calls = []

    async def _fake_send_one(token, user_id, body):
        calls.append(body)
        return {"message": {"body": {"mid": f"mid-{len(calls)}"}}}

    monkeypatch.setattr(max_api, "_send_one", _fake_send_one)
    monkeypatch.setattr(max_api, "_PER_DIALOG_DELAY", 0)

    sent = await max_api.send_message("tok", 555, "а" * 9000)
    assert len(calls) == 3
    assert all(len(c["text"]) <= max_api.MAX_MESSAGE_LEN for c in calls)
    # Вложения уходят с последней частью — фраза ими и заканчивается.
    assert sent.message_id == "mid-3"


async def test_attachments_ride_with_last_chunk(monkeypatch):
    calls = []

    async def _fake_send_one(token, user_id, body):
        calls.append(body)
        return {"message": {"body": {"mid": "m"}}}

    monkeypatch.setattr(max_api, "_send_one", _fake_send_one)
    monkeypatch.setattr(max_api, "_PER_DIALOG_DELAY", 0)

    await max_api.send_message(
        "tok", 555, "б" * 5000,
        attachments=[{"type": "image", "payload": {"url": "https://cdn/1.jpg"}}],
    )
    assert "attachments" not in calls[0]
    assert calls[-1]["attachments"]


# --- Диспетчер платформ -------------------------------------------------------


@pytest.fixture
async def max_dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    bot = VkGroup(
        platform="max", group_id=777001, name="Бот", access_token="max-token",
    )
    db.add(bot)
    await db.flush()
    c = Client(vk_user_id=555, vk_group_id=bot.id)
    db.add(c)
    await db.flush()
    d = Dialog(client_id=c.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


@pytest.fixture
async def vk_dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    group = VkGroup(
        platform="vk", group_id=111222, name="Группа",
        access_token="vk-token", confirmation_code="c",
    )
    db.add(group)
    await db.flush()
    c = Client(vk_user_id=777, vk_group_id=group.id)
    db.add(c)
    await db.flush()
    d = Dialog(client_id=c.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


async def test_dispatch_sends_max_dialog_to_max(db, max_dialog, monkeypatch):
    calls = []

    async def _fake_send(token, user_id, text, bot_pk=None, attachments=None):
        calls.append((token, user_id, text, attachments))
        return MaxSentMessage(message_id="mid-1")

    monkeypatch.setattr(max_sender, "send_message", _fake_send)
    result = await send_to_dialog(db, max_dialog, "Здравствуйте!")
    assert calls == [("max-token", 555, "Здравствуйте!", None)]
    assert result.message_id == "mid-1"


async def test_dispatch_keeps_vk_dialog_in_vk(db, vk_dialog, monkeypatch):
    calls = []

    async def _fake_vk_send(db_, dialog, text):
        calls.append(text)
        return object()

    monkeypatch.setattr("app.vk.sender.send_to_dialog", _fake_vk_send)
    await send_to_dialog(db, vk_dialog, "Здравствуйте!")
    assert calls == ["Здравствуйте!"]


async def test_forbidden_marks_dialog_blocked(db, max_dialog, monkeypatch):
    async def _boom(token, user_id, text, bot_pk=None, attachments=None):
        raise MaxMessagesForbiddenError(403, "user.blocked", "нельзя")

    monkeypatch.setattr(max_sender, "send_message", _boom)
    with pytest.raises(MessagesForbiddenError):
        await send_to_dialog(db, max_dialog, "Здравствуйте!")
    assert max_dialog.vk_blocked is True


def test_both_platforms_share_one_forbidden_exception():
    """Пинги, приветствие и панель ловят одно исключение на оба мессенджера."""
    assert issubclass(MaxMessagesForbiddenError, MessagesForbiddenError)
    assert issubclass(VkMessagesForbiddenError, MessagesForbiddenError)
