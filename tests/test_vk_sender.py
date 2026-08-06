"""VK sender: разрезание длинных текстов, random_id, обработка error-тела."""
import pytest

from app.vk import sender
from app.vk.sender import (
    MAX_MESSAGE_LEN,
    _DEAD_ATTACHMENT_TOKEN_RE,
    VkApiError,
    VkMessagesForbiddenError,
    check_vk_response,
    extract_and_resolve_attachments,
    make_random_id,
    send_message,
    split_text,
)


def test_split_text_short_is_single_part():
    assert split_text("привет") == ["привет"]


def test_split_text_empty():
    assert split_text("") == []
    assert split_text("   ") == []


def test_split_text_long_respects_limit_and_keeps_content():
    words = ["слово" + str(i) for i in range(2000)]
    text = " ".join(words)
    parts = split_text(text)
    assert len(parts) > 1
    assert all(len(p) <= MAX_MESSAGE_LEN for p in parts)
    # Контент не теряется: склейка частей по словам эквивалентна исходнику.
    assert " ".join(parts).split() == text.split()


def test_split_text_prefers_paragraph_boundary():
    text = "a" * 4000 + "\n\n" + "b" * 4000
    parts = split_text(text)
    assert parts == ["a" * 4000, "b" * 4000]


def test_check_vk_response_ok():
    assert check_vk_response({"response": 123}) == 123


def test_check_vk_response_error_body_raises():
    # HTTP 200 с error в теле — не успех.
    with pytest.raises(VkApiError) as exc_info:
        check_vk_response({"error": {"error_code": 14, "error_msg": "Captcha needed"}})
    assert exc_info.value.code == 14
    assert not isinstance(exc_info.value, VkMessagesForbiddenError)


@pytest.mark.parametrize("code", [900, 901, 902])
def test_check_vk_response_forbidden_codes(code):
    with pytest.raises(VkMessagesForbiddenError):
        check_vk_response({"error": {"error_code": code, "error_msg": "Can't send messages"}})


async def test_send_message_passes_random_id_and_chunks(monkeypatch):
    calls = []

    async def fake_api_call(token, method, params):
        calls.append((token, method, params))
        return 1000 + len(calls)

    monkeypatch.setattr(sender, "vk_api_call", fake_api_call)

    text = "x" * (MAX_MESSAGE_LEN * 2 + 10)
    last_id = await send_message("tok", 42, text, vk_group_id=1)

    assert len(calls) == 3  # текст порезан на 3 части
    assert last_id == 1003
    random_ids = set()
    for token, method, params in calls:
        assert token == "tok"
        assert method == "messages.send"
        assert params["peer_id"] == 42
        assert len(params["message"]) <= MAX_MESSAGE_LEN
        assert params["random_id"]  # random_id обязателен и ненулевой
        random_ids.add(params["random_id"])
    assert len(random_ids) == 3  # у каждой части свой random_id


def test_make_random_id_positive_int32():
    for _ in range(100):
        rid = make_random_id()
        assert 0 < rid <= 0x7FFF_FFFF


class TestDeadTokens:
    """Мёртвый media-id — тот, что ВК молча выбрасывает. Проверено отправкой:
    фото чужого сообщества и голосовое не прикрепились, видео — прикрепилось,
    поэтому video и clip из этого списка ушли (см. TestVideoAttachment)."""

    @pytest.mark.parametrize("token", [
        "[photo-44440184_457423829]",
        "[audio_message569993513_687712211]",
    ])
    def test_dead_tokens_stripped(self, token):
        assert _DEAD_ATTACHMENT_TOKEN_RE.sub("", f"Текст {token}").strip() == "Текст"

    @pytest.mark.parametrize("token", [
        "[video-44440184_456240651]",
        "[clip-228420497_456239100]",
    ])
    def test_video_is_not_dead_anymore(self, token):
        assert _DEAD_ATTACHMENT_TOKEN_RE.sub("", f"Текст {token}") == f"Текст {token}"

    def test_url_token_is_not_a_dead_id(self):
        """Ссылку трогать нельзя — её перезаливает resolve_attachment."""
        text = "Текст [photo-https://sun9-29.vkuserphoto.ru/a.jpg]"
        assert _DEAD_ATTACHMENT_TOKEN_RE.sub("", text) == text


class TestVideoAttachment:
    """Видео чужого сообщества ВК принимает вложением — проверено отправкой:
    оба ролика из выгрузки ОП дошли, messages.getById показал их в attachments.
    Раньше id вырезался как мёртвый, а ссылка уезжала голым текстом, прилипая к
    вопросу: «…важнее качество или итоговая цена? https://vkvideo.ru/clip-…».

    db и group не нужны: перезаливка вызывается только для фото-токенов.
    """

    async def test_bare_video_id_becomes_attachment(self):
        cleaned, att = await extract_and_resolve_attachments(
            None, None, "Вот наше производство [video-44440184_456240651]")
        assert cleaned == "Вот наше производство"
        assert att == "video-44440184_456240651"

    async def test_clip_token_becomes_attachment(self):
        cleaned, att = await extract_and_resolve_attachments(
            None, None, "Качество или цена? [clip-228420497_456239100]")
        assert cleaned == "Качество или цена?"
        assert att == "video-228420497_456239100"

    async def test_vkvideo_link_becomes_attachment(self):
        cleaned, att = await extract_and_resolve_attachments(
            None, None, "Смотрите [video-https://vkvideo.ru/video-44440184_456240651]")
        assert cleaned == "Смотрите"
        assert att == "video-44440184_456240651"

    async def test_foreign_host_link_stays_text_at_the_end(self):
        """Не vkvideo — id не вытащить, вложением не сделать."""
        cleaned, att = await extract_and_resolve_attachments(
            None, None, "Вопрос? [video-https://example.org/reel.mp4]")
        assert cleaned == "Вопрос?\n\nhttps://example.org/reel.mp4"
        assert att is None

    async def test_dead_photo_and_voice_ids_still_stripped(self):
        """Их ВК выбрасывает молча — проверено той же отправкой."""
        cleaned, att = await extract_and_resolve_attachments(
            None, None, "Текст [photo-44440184_457423829] [audio_message569993513_687712211]")
        assert cleaned == "Текст"
        assert att is None


class TestJunkAttachmentToken:
    """«Фиолетовый свитшот выглядит так: [photo-фиолетовый свитшот]» ушло клиенту
    как есть (прогон 1369): инструмент ответил «Фото не найдено» — такого цвета в
    матрице нет, — а модель всё равно сослалась на картинку."""

    async def test_made_up_token_is_cut(self, db):
        from app.db.models import VkGroup
        from app.vk.sender import extract_and_resolve_attachments

        group = VkGroup(group_id=1, name="g", access_token="t", confirmation_code="c")
        db.add(group)
        await db.commit()

        text, attachment = await extract_and_resolve_attachments(
            db, group, "Фиолетовый свитшот выглядит так: [photo-фиолетовый свитшот]",
        )
        assert "[photo-" not in text
        assert attachment is None

    async def test_real_token_survives(self, db, monkeypatch):
        from app.db.models import VkGroup
        from app.vk import sender

        group = VkGroup(group_id=1, name="g", access_token="t", confirmation_code="c")
        db.add(group)
        await db.commit()

        async def fake_resolve(_db, _group, url):
            return "photo1_2"

        monkeypatch.setattr("app.vk.photo_upload.resolve_attachment", fake_resolve)
        text, attachment = await sender.extract_and_resolve_attachments(
            db, group, "Вот наши цвета [photo-https://example.ru/a.jpg]",
        )
        assert attachment == "photo1_2"
        assert text == "Вот наши цвета"
