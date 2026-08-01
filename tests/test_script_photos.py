"""Вложения не должны теряться, когда текст переписывает модель.

Продающий агент: скрипт «5. Оформление» заканчивается словами «Прикрепляю наши
отзывы!» и тремя токенами фото — в диалогах 59 и 64 фраза уехала, картинки нет.

Пинговый агент: он ВСЕГДА переписывает фразу (custom_text) — из 70 отправленных
пингов с медиа 33 ушли без единого вложения.
"""
import pytest

from app.utils.media import carry_over_attachments

P1 = "[photo-https://sun9-69.vkuserphoto.ru/s/v1/ig2/Wf0Uabc.jpg?quality=95&as=32x51]"
P2 = "[photo-https://sun9-22.vkuserphoto.ru/s/v1/ig2/_dqHBra.jpg?quality=95&as=32x43]"
SCRIPT = f"Получается сумма заказа - 4 990 ₽\n\nПрикрепляю наши отзывы!\n\n{P1}\n{P2}"


class TestCarryOverAttachments:
    def test_dropped_photos_are_restored(self):
        reply = "Получается сумма заказа - 4 990 ₽. Прикрепляю наши отзывы! Как удобнее оплатить?"
        result = carry_over_attachments(reply, SCRIPT)
        assert result.startswith(reply)
        assert P1 in result and P2 in result

    def test_photos_go_after_the_text_as_one_block(self):
        """ВК показывает вложения отдельно — токены внутри строк ломают текст."""
        result = carry_over_attachments("Сумма - 4 990 ₽. Оплатим?", SCRIPT)
        text_part, _, tail = result.partition(P1)
        assert "[photo-" not in text_part
        assert tail.strip() == P2

    def test_already_copied_photos_not_duplicated(self):
        reply = f"Сумма - 4 990 ₽. Оплатим?\n\n{P1}\n{P2}"
        assert carry_over_attachments(reply, SCRIPT) == reply

    def test_partially_copied_photos_completed(self):
        reply = f"Сумма - 4 990 ₽. Оплатим?\n\n{P1}"
        result = carry_over_attachments(reply, SCRIPT)
        assert result.count(P1) == 1
        assert P2 in result

    def test_script_without_attachments_leaves_reply_untouched(self):
        reply = "Отлично, тогда подскажите ФИО и номер телефона получателя"
        assert carry_over_attachments(reply, "Скрипт без картинок") == reply

    @pytest.mark.parametrize("token", [
        "[photo-228420497_456240496]",
        "[video-44440184_456240651]",
        "[clip-228420497_456239100]",
        "[audio_message569993513_687712211]",
        "[video-https://vkvideo.ru/video-44440184_456240651]",
    ])
    def test_every_attachment_kind_is_carried(self, token):
        """Пинги несут не только фото: у шага 2 клип, у шага 7 видео-отзыв."""
        assert token in carry_over_attachments("Переписанный текст", f"Исходный {token}")

    def test_ping_rewrite_keeps_its_photo(self):
        """Реальный случай: агент переписал фразу шага 5 и выбросил картинку."""
        rule = (
            "У нас всё сделано так, чтобы Вам было спокойно и удобно оформить заказ\n\n"
            "Не нужно оплачивать всю сумму сразу - сначала вносите всего 500₽\n\n"
            "[photo-https://sun9-29.vkuserphoto.ru/a.jpg]"
        )
        rewritten = "У нас всё предусмотрено, чтобы Вам было удобно оформить заказ. Начнём с 500 ₽?"
        result = carry_over_attachments(rewritten, rule)
        assert result.startswith(rewritten)
        assert "[photo-https://sun9-29.vkuserphoto.ru/a.jpg]" in result
