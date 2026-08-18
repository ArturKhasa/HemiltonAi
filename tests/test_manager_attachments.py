"""Файл из панели уходит клиенту вложением, а не ссылкой в тексте.

Просьба ОП от 18.08: «отправку фото и видео из панельки тоже добавить».
Раньше `body.files` дописывались к тексту голыми ссылками — клиент видел набор
символов вместо картинки.
"""
import pytest

from app.utils.media import attachment_token

BASE = "https://ai.hemilton.ru/media/chat/12"


class TestAttachmentToken:
    @pytest.mark.parametrize("name", ["a.jpg", "b.JPEG", "c.png", "d.gif", "e.webp", "f.heic"])
    def test_images_go_as_photo(self, name):
        assert attachment_token(f"{BASE}/{name}") == f"[photo-{BASE}/{name}]"

    @pytest.mark.parametrize("name", ["clip.mp4", "clip.MOV", "doc.pdf", "voice.ogg"])
    def test_everything_else_goes_as_doc(self, name):
        """ВК принимает видео во вложение только документом."""
        assert attachment_token(f"{BASE}/{name}") == f"[doc-{BASE}/{name}]"

    def test_query_string_does_not_confuse_the_extension(self):
        url = f"{BASE}/a.jpg?v=2"
        assert attachment_token(url) == f"[photo-{url}]"

    def test_extensionless_url_goes_as_doc(self):
        assert attachment_token(f"{BASE}/file") == f"[doc-{BASE}/file]"
