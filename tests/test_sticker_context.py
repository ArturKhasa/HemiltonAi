"""Стикер доходит до модели как стикер: с картинкой, но с явной подписью.

Пометка «[Стикер]» одинакова для пальца вверх, сердечка и «ну не знаю» —
настроение по ней не прочитать, поэтому следом идёт само превью. Подпись перед
ним нужна, чтобы модель не приняла стикер за присланное клиентом фото дизайна.

Раньше пометка бралась, лишь когда текста в сообщении нет: «спасибо 🙂» со
стикером приходило голым текстом, и вложения для модели не существовало.
"""
from app.ai.runner import _attachment_content
from app.vk.webhook import parse_message_event

STICKER = {"type": "sticker", "sticker": {
    "product_id": 1, "sticker_id": 12,
    "images": [
        {"url": "https://vk.com/sticker/1-12-64", "width": 64, "height": 64},
        {"url": "https://vk.com/sticker/1-12-128", "width": 128, "height": 128},
        {"url": "https://vk.com/sticker/1-12-512", "width": 512, "height": 512},
    ],
}}


def _event(text: str, attachments: list[dict]) -> dict:
    return {"object": {"message": {
        "from_id": 42, "peer_id": 42, "text": text,
        "conversation_message_id": 1, "date": 0, "attachments": attachments,
    }}}


class TestStickerParsing:
    def test_sticker_alone_becomes_a_marker(self):
        msg = parse_message_event(_event("", [STICKER]))
        assert msg.text == "[Стикер]"

    def test_sticker_image_is_not_stored_as_a_photo(self):
        msg = parse_message_event(_event("", [STICKER]))
        assert msg.files == []
        assert msg.sticker_files == ["https://vk.com/sticker/1-12-128"]

    def test_smallest_readable_preview_is_taken(self):
        """Настроение видно и на мелком, а картинка едет в модель каждый ход."""
        sticker = {"type": "sticker", "sticker": {"images": [
            {"url": "https://vk.com/sticker/1-12-256", "width": 256, "height": 256},
            {"url": "https://vk.com/sticker/1-12-512", "width": 512, "height": 512},
        ]}}
        msg = parse_message_event(_event("", [sticker]))
        assert msg.sticker_files == ["https://vk.com/sticker/1-12-256"]

    def test_tiny_only_preview_is_better_than_nothing(self):
        sticker = {"type": "sticker", "sticker": {"images": [
            {"url": "https://vk.com/sticker/1-12-64", "width": 64, "height": 64},
        ]}}
        msg = parse_message_event(_event("", [sticker]))
        assert msg.sticker_files == ["https://vk.com/sticker/1-12-64"]

    def test_sticker_without_images_still_parses(self):
        msg = parse_message_event(_event("", [{"type": "sticker", "sticker": {}}]))
        assert msg.text == "[Стикер]"
        assert msg.sticker_files == []

    def test_sticker_with_text_keeps_both(self):
        msg = parse_message_event(_event("спасибо", [STICKER]))
        assert msg.text == "спасибо\n[Стикер]"

    def test_video_with_text_keeps_both(self):
        msg = parse_message_event(_event("вот", [{"type": "video", "video": {}}]))
        assert msg.text == "вот\n[видео]"

    def test_plain_text_is_untouched(self):
        assert parse_message_event(_event("Казань", [])).text == "Казань"

    def test_photo_with_text_stays_text_plus_file(self):
        """У фото своя дорога — оно уходит в модель картинкой, пометка не нужна."""
        event = _event("вот мой дизайн", [{
            "type": "photo",
            "photo": {"sizes": [{"width": 800, "height": 600, "url": "http://img/big.jpg"}]},
        }])
        msg = parse_message_event(event)
        assert msg.text == "вот мой дизайн"
        assert msg.files == ["http://img/big.jpg"]


class TestStickerInModelContext:
    def test_sticker_goes_to_the_model_as_a_labelled_image(self):
        content = _attachment_content(
            "спасибо\n[Стикер]", [], ["https://vk.com/sticker/1-12-128"],
        )
        assert content[0] == {"type": "input_text", "text": "спасибо\n[Стикер]"}
        assert content[1]["type"] == "input_text"
        assert "не фото клиента" in content[1]["text"]
        assert content[2] == {
            "type": "input_image",
            "image_url": "https://vk.com/sticker/1-12-128",
            "detail": "low",
        }

    def test_old_sticker_url_in_files_stays_a_marker(self):
        """Стикеры из истории до этой правки: картинки нет, только пометка."""
        content = _attachment_content("спасибо", ["https://vk.com/sticker/1-12-512"])
        assert content == [
            {"type": "input_text", "text": "спасибо"},
            {"type": "input_text", "text": "[Стикер]"},
        ]

    def test_photo_url_stays_an_image(self):
        content = _attachment_content("вот", ["http://img/big.jpg"])
        assert content[1]["type"] == "input_image"

    def test_marker_is_not_duplicated(self):
        content = _attachment_content("[Стикер]", ["https://vk.com/sticker/1-12-512"])
        assert content == [{"type": "input_text", "text": "[Стикер]"}]
