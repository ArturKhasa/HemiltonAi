"""Просьбу показать изделие закрывает картинка, а не текст.

Диалог 362, 18.08: на «как она будет выглядеть» ушёл скрипт
«Преимущества/возражение: что получается клиент» — «мы не маркетплейс и не
магазин готовой одежды» и ни одной фотографии.
"""
import pytest

from app.sales.product_photo import asks_to_see_product, reply_shows_photo

PHOTO = "[photo-https://ai.hemilton.ru/media/scripts/a1.jpg]"


class TestAsksToSee:
    @pytest.mark.parametrize("text", [
        "как она будет выглядеть",
        "А как выглядит?",
        "Покажите примеры работ",
        "покажите фото",
        "есть фото?",
        "скиньте фотки пожалуйста",
        "можно посмотреть",
        "хочу посмотреть на изделие",
    ])
    def test_request_detected(self, text):
        assert asks_to_see_product(text) is True

    @pytest.mark.parametrize("text", [
        "Дорого",
        "А сколько стоит?",
        "Чёрный",
        "Отправьте каталог",
        "Как оплатить?",
        "Когда придёт заказ?",
    ])
    def test_other_messages_ignored(self, text):
        assert asks_to_see_product(text) is False


class TestReplyShowsPhoto:
    def test_token_counts(self):
        assert reply_shows_photo(f"Вот наши работы: {PHOTO}") is True

    def test_parsed_urls_count(self):
        assert reply_shows_photo("Вот наши работы", ["https://ai.hemilton.ru/x.jpg"]) is True

    def test_text_only_reply_does_not(self):
        assert reply_shows_photo(
            "Мы не маркетплейс и не магазин готовой одежды. Какой цвет свитшота выберем?"
        ) is False
