"""К вопросу про цвет всегда прикладывается палитра.

Требование ОП от 17.08. Из 65 вопросов про цвет за неделю 33 ушли без картинки:
скрипт цвета модель пересказывает своими словами и токен фото теряет.
"""
import pytest

from app.db.models import Script
from app.sales.color_palette import asks_color, palette_token, with_palette

SWEATSHIRT_PHOTO = "[photo-https://sun9-23.vkuserphoto.ru/s/v1/ig2/GsUPGBO.jpg?quality=95]"
HOODIE_PHOTO = "[photo-https://sun9-29.vkuserphoto.ru/s/v1/ig2/WXqKVF.jpg?quality=95]"


@pytest.fixture
async def color_scripts(db):
    db.add_all([
        Script(
            id=373, is_active=True, type_id=1, funnel_stage="options",
            condition="3. Цвет ХУДИ. Только если клиент САМ сказал «худи»",
            phrase_text=f"А цвет для худи выберем белый, чёрный или бежевый?\n\n{HOODIE_PHOTO}",
        ),
        Script(
            id=374, is_active=True, type_id=1, funnel_stage="options",
            condition="3. Цвет СВИТШОТА. Вариант ПО УМОЛЧАНИЮ",
            phrase_text=f"А цвет для свитшота какой выберем?\n\n{SWEATSHIRT_PHOTO}",
        ),
    ])
    await db.flush()
    return db


class TestAsksColor:
    @pytest.mark.parametrize("reply", [
        "В Заринск отправляем СДЭКом. Какой цвет свитшота выберем?",
        "Оплата доставки при получении. А цвет для свитшота какой выберем?",
        "Какой цвет выбираете?",
        "Цвет белый или чёрный?",
        # Повторный вопрос своими словами — из живых диалогов за неделю.
        "Свитшот - 5 990 ₽, сейчас по акции 4 990 ₽. Какой цвет Вам подобрать?",
        "Стоимость я уже отправила, но ответа пока нет 🙂 Подскажите, "
        "пожалуйста, какой цвет берём?",
        "Герб разместим вместе с надписью «Сидельников». Какой цвет свитшота выбираете?",
        "В каком цвете шьём?",
    ])
    def test_color_question_detected(self, reply):
        assert asks_color(reply) is True

    @pytest.mark.parametrize("reply", [
        "Чёрный цвет зафиксировала. Назовите, пожалуйста, Ваш вес и рост?",
        "Отправим СДЭКом. В какой город доставка?",
        "Приняла: рост 178 см, вес 67 кг. Какой дизайн разместим на свитшоте?",
        "Приняла: толстовка серого цвета, надпись «Дмитрий», герб на спине. Всё верно?",
        "Синий цвет есть! Пожалуйста, назовите вес и рост, чтобы подобрать размер?",
    ])
    def test_other_questions_ignored(self, reply):
        assert asks_color(reply) is False

    def test_repeat_question_still_gets_the_rack(self):
        """Клиент «слился» на цвете, спрашиваем второй раз — палитра нужна снова."""
        assert asks_color("Подскажите, пожалуйста, какой цвет берём?") is True


class TestPalette:
    async def test_question_without_photo_gets_the_rack(self, color_scripts):
        result = await with_palette(
            color_scripts, "Какой цвет свитшота выберем?", type_id=1, product=None,
        )
        assert SWEATSHIRT_PHOTO in result
        assert result.startswith("Какой цвет свитшота выберем?")

    async def test_hoodie_client_gets_the_hoodie_rack(self, color_scripts):
        result = await with_palette(
            color_scripts, "А цвет какой выберем?", type_id=1, product="худи",
        )
        assert HOODIE_PHOTO in result
        assert SWEATSHIRT_PHOTO not in result

    async def test_photo_already_in_reply_is_not_doubled(self, color_scripts):
        reply = f"Какой цвет свитшота выберем?\n\n{SWEATSHIRT_PHOTO}"
        assert await with_palette(color_scripts, reply, type_id=1, product=None) == reply

    async def test_reply_without_color_question_untouched(self, color_scripts):
        reply = "Приняла размер. Какой дизайн разместим на свитшоте?"
        assert await with_palette(color_scripts, reply, type_id=1, product=None) == reply

    async def test_no_color_script_leaves_reply_as_is(self, db):
        reply = "Какой цвет свитшота выберем?"
        assert await with_palette(db, reply, type_id=1, product=None) == reply

    async def test_token_picked_per_product(self, color_scripts):
        assert await palette_token(color_scripts, 1, "свитшот") == SWEATSHIRT_PHOTO
        assert await palette_token(color_scripts, 1, "худи") == HOODIE_PHOTO

    async def test_hoodie_palette_only_when_the_client_said_hoodie(self, color_scripts):
        """«Толстовка» — это свитшот.

        Так это слово стоит в скриптах ОП («Стоимость толстовки — 5 990 ₽»), и так
        сказано в условии самого скрипта палитры худи. Лена, 21.08: «В этом диалоге
        на выбор цвета ИИ отправила худи, хотя изначально разговор велся про
        свитшот» — клиент до этого спросил «А из какого материала толстовка?».
        """
        assert await palette_token(color_scripts, 1, "толстовка") == SWEATSHIRT_PHOTO
        assert await palette_token(color_scripts, 1, "толстовка с капюшоном") == HOODIE_PHOTO
