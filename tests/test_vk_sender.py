"""VK sender: разрезание длинных текстов, random_id, обработка error-тела."""
import pytest

from app.vk import sender
from app.vk.sender import (
    MAX_MESSAGE_LEN,
    _DEAD_ATTACHMENT_TOKEN_RE,
    VkApiError,
    VkMessagesForbiddenError,
    check_vk_response,
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


class TestClipToken:
    """«[clip-<id>_<id>]» — тот же мёртвый VK-ID, что photo/video, только для
    клипов. Его не было в списке вырезаемых, и токен уезжал клиенту голым
    текстом в конце пинга «эта толстовка стоит каждого рубля»."""

    def test_clip_id_token_is_stripped(self):
        assert _DEAD_ATTACHMENT_TOKEN_RE.sub("", "Текст [clip-228420497_456239100]").strip() == "Текст"

    @pytest.mark.parametrize("token", [
        "[photo-228420497_456240496]",
        "[video-44440184_456240651]",
        "[audio_message569993513_687712211]",
    ])
    def test_other_dead_tokens_still_stripped(self, token):
        assert _DEAD_ATTACHMENT_TOKEN_RE.sub("", f"Текст {token}").strip() == "Текст"

    def test_url_token_is_not_a_dead_id(self):
        """Ссылку трогать нельзя — её перезаливает resolve_attachment."""
        text = "Текст [photo-https://sun9-29.vkuserphoto.ru/a.jpg]"
        assert _DEAD_ATTACHMENT_TOKEN_RE.sub("", text) == text
