"""Вложение, которого ВК не отправил, не должно оставаться в кэше.

Картинки к скриптам «2.2 Стоимость» и «5. Оформление» перезалили 5 августа, а
8-го объекты в ВК умерли. `messages.send` продолжал принимать их без ошибки и
молча выбрасывать: 85 сообщений с ценой и 28 с оформлением ушли без единой
картинки, и ни одна проверка в коде этого не заметила.
"""
import pytest

from app.db.models import VkAttachmentCache, VkGroup
from app.vk.sender import verify_attachments_delivered

ATT = ["photo-238878717_456243004", "photo-238878717_456243005"]


@pytest.fixture
async def group(db):
    grp = VkGroup(
        id=2, group_id=238878717, name="Hemilton", access_token="t",
        confirmation_code="ok",
    )
    db.add(grp)
    db.add_all([
        VkAttachmentCache(vk_group_id=2, source_url=f"https://sun9.vk/{i}.jpg", attachment=a)
        for i, a in enumerate(ATT)
    ])
    await db.flush()
    return grp


def _vk_returning(attachment_count: int, calls: list):
    async def _call(access_token, method, params):
        calls.append((method, params))
        return {"items": [{"attachments": [{"type": "photo"}] * attachment_count}]}
    return _call


async def test_missing_attachments_dropped_from_cache(db, group, monkeypatch):
    calls: list = []
    monkeypatch.setattr("app.vk.sender.vk_api_call", _vk_returning(0, calls))

    ok = await verify_attachments_delivered(db, group, 165103, ",".join(ATT))

    assert ok is False
    left = (await db.execute(
        VkAttachmentCache.__table__.select().where(VkAttachmentCache.vk_group_id == 2)
    )).fetchall()
    assert left == []
    assert calls[0][0] == "messages.getById"


async def test_delivered_attachments_keep_the_cache(db, group, monkeypatch):
    monkeypatch.setattr("app.vk.sender.vk_api_call", _vk_returning(len(ATT), []))

    assert await verify_attachments_delivered(db, group, 165103, ",".join(ATT)) is True

    left = (await db.execute(
        VkAttachmentCache.__table__.select().where(VkAttachmentCache.vk_group_id == 2)
    )).fetchall()
    assert len(left) == len(ATT)


async def test_vk_error_does_not_drop_anything(db, group, monkeypatch):
    """Сообщение клиент уже получил — упавшая проверка не повод чистить кэш."""
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("VK unavailable")

    monkeypatch.setattr("app.vk.sender.vk_api_call", _boom)

    assert await verify_attachments_delivered(db, group, 165103, ",".join(ATT)) is True
    left = (await db.execute(
        VkAttachmentCache.__table__.select().where(VkAttachmentCache.vk_group_id == 2)
    )).fetchall()
    assert len(left) == len(ATT)


class TestResend:
    """Проверка срабатывает уже после отправки — этому клиенту картинки нужно
    дослать, иначе он останется без них совсем."""

    async def test_photos_are_reuploaded_and_sent_again(self, db, group, monkeypatch):
        from app.vk.sender import resend_lost_photos

        uploaded: list[str] = []
        sent: list[dict] = []

        async def _resolve(db_, group_, url):
            uploaded.append(url)
            return f"photo-238878717_99{len(uploaded)}"

        async def _send(token, peer_id, text, vk_group_id=None, attachment=None):
            sent.append({"peer_id": peer_id, "text": text, "attachment": attachment})
            return None

        monkeypatch.setattr("app.vk.photo_upload.resolve_attachment", _resolve)
        monkeypatch.setattr("app.vk.sender.send_message", _send)

        ok = await resend_lost_photos(
            db, group, 555, ["https://sun9.vk/0.jpg", "https://sun9.vk/1.jpg"],
        )

        assert ok is True
        assert uploaded == ["https://sun9.vk/0.jpg", "https://sun9.vk/1.jpg"]
        # Текст клиент уже прочитал — досылаем только вложения.
        assert sent == [{
            "peer_id": 555, "text": "",
            "attachment": "photo-238878717_991,photo-238878717_992",
        }]

    async def test_failed_reupload_is_reported_not_raised(self, db, group, monkeypatch):
        from app.vk.sender import resend_lost_photos

        async def _resolve(db_, group_, url):
            return None

        async def _send(*_args, **_kwargs):
            raise AssertionError("отправлять нечего")

        monkeypatch.setattr("app.vk.photo_upload.resolve_attachment", _resolve)
        monkeypatch.setattr("app.vk.sender.send_message", _send)

        assert await resend_lost_photos(db, group, 555, ["https://sun9.vk/0.jpg"]) is False


async def test_no_message_id_skips_the_check(db, group, monkeypatch):
    async def _boom(*_args, **_kwargs):
        raise AssertionError("проверять нечего — вызова быть не должно")

    monkeypatch.setattr("app.vk.sender.vk_api_call", _boom)
    assert await verify_attachments_delivered(db, group, None, ",".join(ATT)) is True
