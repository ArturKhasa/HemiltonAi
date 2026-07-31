"""Фото скрипта не должны теряться, когда ответ пишет модель.

Скрипт «5. Оформление» заканчивается словами «Прикрепляю наши отзывы!» и тремя
токенами фото. В диалогах 59 и 64 на проде сообщение ушло с этой фразой и нулём
вложений: модель взяла текст скрипта, а токены выбросила.
"""
from app.ai.runner import _carry_over_script_photos

P1 = "[photo-https://sun9-69.vkuserphoto.ru/s/v1/ig2/Wf0Uabc.jpg?quality=95&as=32x51]"
P2 = "[photo-https://sun9-22.vkuserphoto.ru/s/v1/ig2/_dqHBra.jpg?quality=95&as=32x43]"
SCRIPT = f"Получается сумма заказа - 4 990 ₽\n\nПрикрепляю наши отзывы!\n\n{P1}\n{P2}"


class TestCarryOverPhotos:
    def test_dropped_photos_are_restored(self):
        reply = "Получается сумма заказа - 4 990 ₽. Прикрепляю наши отзывы! Как удобнее оплатить?"
        result = _carry_over_script_photos(reply, SCRIPT)
        assert result.startswith(reply)
        assert P1 in result and P2 in result

    def test_photos_go_after_the_text_as_one_block(self):
        """ВК показывает вложения отдельно — токены внутри строк ломают текст."""
        result = _carry_over_script_photos("Сумма - 4 990 ₽. Оплатим?", SCRIPT)
        text_part, _, tail = result.partition(P1)
        assert "[photo-" not in text_part
        assert tail.strip() == P2

    def test_already_copied_photos_not_duplicated(self):
        reply = f"Сумма - 4 990 ₽. Оплатим?\n\n{P1}\n{P2}"
        assert _carry_over_script_photos(reply, SCRIPT) == reply

    def test_partially_copied_photos_completed(self):
        reply = f"Сумма - 4 990 ₽. Оплатим?\n\n{P1}"
        result = _carry_over_script_photos(reply, SCRIPT)
        assert result.count(P1) == 1
        assert P2 in result

    def test_script_without_photos_leaves_reply_untouched(self):
        reply = "Отлично, тогда подскажите ФИО и номер телефона получателя"
        assert _carry_over_script_photos(reply, "Скрипт без картинок") == reply

    def test_vk_id_token_format_also_carried(self):
        """В архивных скриптах ОП вложения записаны айдишником, а не ссылкой."""
        token = "[photo-228420497_456240496]"
        result = _carry_over_script_photos("Вот отзывы!", f"Прикрепляю отзывы {token}")
        assert token in result
