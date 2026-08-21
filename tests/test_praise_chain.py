"""Ответ на надпись — связка скриптов, а не пересказ модели.

Требование ОП от 17.08: «сообщение с ценой надо отправлять жёстче в формате
полноценного скрипта, а не ответа ИИ». В диалоге 351 модель сжала всю связку в
одну строку — «Супер, зафиксировала фамилию Шаманский! Свитшот … стоит 5 990 ₽.
В какой город планируете доставку?» — и клиент не увидел ни условий, ни картинок.
"""
import pytest

from app.ai.runner import _is_praise_only, build_script_parts
from app.db.models import Client, Dialog, DialogType, Script, VkGroup
from app.sales.funnel_steps import find_praise_script

PRICE_PHOTO = "[photo-https://sun9-82.vkuserphoto.ru/s/v1/ig2/ZwRSxwv.jpg?quality=95]"


@pytest.fixture
async def funnel(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add_all([
        Script(
            id=363, is_active=True, type_id=1, funnel_stage="greeting",
            condition="ОБЯЗАТЕЛЬНЫЙ шаг воронки «2. Похвала»",
            phrase_text="Супер, зафиксировала\nСделаем всё как Вы хотите!",
            follow_up_script_id=367,
        ),
        Script(
            id=367, is_active=True, type_id=1, funnel_stage="pricing",
            condition="2.2 Стоимость (свитшот)",
            phrase_text=(
                "Стоимость толстовки с термо-принтами со скидкой СЕГОДНЯ - 5 990 ₽ "
                "(вместо 7 990 ₽)\n\n"
                "✅Всю сумму сразу вносить не нужно, есть удобная оплата частями\n\n"
                f"{PRICE_PHOTO}"
            ),
            follow_up_script_id=372,
        ),
        Script(
            id=372, is_active=True, type_id=1, funnel_stage="pricing",
            condition="2.3 Доставка",
            phrase_text="Одежду шьем индивидуально.\n\nВ какой город нужна будет доставка?",
        ),
    ])
    group = VkGroup(group_id=111222, name="Магазин", access_token="t", confirmation_code="c")
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=555, vk_group_id=group.id, name="Виктор")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=1, funnel_stage="greeting")
    db.add(dialog)
    await db.flush()
    return db, dialog, client


async def test_praise_unrolls_into_price_and_delivery(funnel):
    db, dialog, client = funnel
    praise = await find_praise_script(db, type_id=1)

    parts = await build_script_parts(db, dialog, praise, client)

    texts = [p.text for p in parts]
    assert len(texts) == 3
    assert texts[0].startswith("Супер, зафиксировала")
    # Цена уходит текстом скрипта целиком, а не одной строкой от модели.
    assert "5 990 ₽" in texts[1] and "вместо 7 990 ₽" in texts[1]
    assert "оплата частями" in texts[1]
    assert PRICE_PHOTO in texts[1]
    # Ход заканчивается вопросом про город — это последнее звено связки.
    assert texts[2].endswith("В какой город нужна будет доставка?")


class TestPraiseDroppedWhenTheClientAsked:
    """«Супер, зафиксировала» на «Сколько будет стоить?» — присоединение не в тему.

    Лена, 21.08: «Если после первого приветственного сообщения клиент сразу
    спрашивает про цену, то её нужно отправить без присоединения "Супер,
    зафиксировала"». Диалог 75854, 08:39 — ушло именно оно, и следом прайс.
    """

    PRAISE = "Супер, зафиксировала\nСделаем всё как Вы хотите!"

    def test_reply_by_script_id_is_praise_only(self):
        assert _is_praise_only(self.PRAISE, self.PRAISE, 363, 363)

    def test_retold_praise_without_script_id_is_praise_only(self):
        assert _is_praise_only("Супер, зафиксировала!", self.PRAISE, None, 363)

    def test_answer_to_the_question_is_kept(self):
        reply = "Состав наших изделий: вискоза/хлопок 85%. Что напишем на кофте?"
        assert not _is_praise_only(reply, self.PRAISE, None, 363)

    def test_another_script_is_kept(self):
        reply = "Стоимость толстовки - 5 990 ₽"
        assert not _is_praise_only(reply, self.PRAISE, 367, 363)

    def test_reply_of_pictures_alone_is_not_praise(self):
        assert not _is_praise_only(PRICE_PHOTO, self.PRAISE, None, 363)
