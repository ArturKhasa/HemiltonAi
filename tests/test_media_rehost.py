"""Картинки скриптов должны лежать у нас, а не ссылками на чужой CDN.

Ссылка на sun9-….vkuserphoto.ru умирает молча: перезалитый по ней объект ВК
перестаёт существовать, messages.send принимает его без ошибки и не кладёт в
сообщение. С 8 августа так ушли 85 сообщений с ценой и 28 с оформлением — все
без картинок. Картинки приветствия лежат у нас и не потерялись ни разу.
"""
import pytest

from app.storage import rehost as rehost_module
from app.storage.rehost import external_photo_urls, rehost_external_photos

VK_URL = "https://sun9-82.vkuserphoto.ru/s/v1/ig2/ZwRSxwv.jpg?quality=95&as=32x43"
OUR_URL = "https://ai.hemilton.ru/media/greeting/a3eb.jpg"


@pytest.fixture
def stored(monkeypatch):
    """Хранилище подменяем: тест не должен ни ходить в сеть, ни писать на диск."""
    saved: list[str] = []

    async def _fake_client_get(url):
        saved.append(url)
        return b"\xff\xd8\xff\xdb" + b"0" * 100

    async def _fetch(url):
        await _fake_client_get(url)
        return f"https://ai.hemilton.ru/media/scripts/{len(saved)}.jpg"

    monkeypatch.setattr(rehost_module, "fetch_and_store", _fetch)
    return saved


class TestDetection:
    def test_foreign_links_found(self):
        text = f"Стоимость - 5 990 ₽\n\n[photo-{VK_URL}]"
        assert external_photo_urls(text) == [VK_URL]

    def test_our_own_links_left_alone(self):
        assert external_photo_urls(f"Здравствуйте!\n\n[photo-{OUR_URL}]") == []

    def test_same_link_twice_counted_once(self):
        text = f"[photo-{VK_URL}] [photo-{VK_URL}]"
        assert external_photo_urls(text) == [VK_URL]


class TestRehost:
    async def test_token_rewritten_to_our_url(self, stored):
        result = await rehost_external_photos(f"Цена 5 990 ₽\n\n[photo-{VK_URL}]")

        assert VK_URL not in result
        assert "[photo-https://ai.hemilton.ru/media/scripts/1.jpg]" in result
        assert result.startswith("Цена 5 990 ₽")
        assert stored == [VK_URL]

    async def test_text_without_photos_untouched(self, stored):
        text = "Отлично, тогда подскажите ФИО и телефон получателя"
        assert await rehost_external_photos(text) == text
        assert stored == []

    async def test_our_links_are_not_downloaded_again(self, stored):
        text = f"Здравствуйте!\n\n[photo-{OUR_URL}]"
        assert await rehost_external_photos(text) == text
        assert stored == []

    async def test_shared_cache_downloads_once_per_link(self, stored):
        cache: dict[str, str] = {}
        first = await rehost_external_photos(f"Скрипт 1 [photo-{VK_URL}]", cache)
        second = await rehost_external_photos(f"Скрипт 2 [photo-{VK_URL}]", cache)

        assert stored == [VK_URL]
        assert first.endswith(second[second.index("[photo-"):])

    async def test_failed_download_keeps_the_original_link(self, monkeypatch):
        async def _fails(url):
            return None

        monkeypatch.setattr(rehost_module, "fetch_and_store", _fails)
        text = f"Цена 5 990 ₽ [photo-{VK_URL}]"

        # По ссылке картинка, возможно, ещё живёт — выбросить её значит
        # потерять наверняка.
        assert await rehost_external_photos(text) == text
