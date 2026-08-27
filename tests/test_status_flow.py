"""Лестница статусов: ступень ставится по факту, а не по мнению модели.

До 27.08 статус в системе умел менять только SalesAgent полем next_status. На
проде это дало 834 диалога с тремя и более сообщениями клиента, застрявших в
«Поинтересовался», против 89 в «Есть расчет»: половину пути клиент проходит без
модели вовсе (скриптовое приветствие → связка со стоимостью → пинги), а там, где
она работает, next_status заполнен в 45 % ходов.

Здесь проверяется код, который считает ступень сам: app.sales.status_flow.
"""
import pytest
from sqlalchemy import select

from app.db.models import (
    Client, Dialog, DialogPingState, DialogStatusConfig, Message, MessageRole,
)
from app.sales.status_flow import earned_status, sync_status
from app.sales.status_names import (
    AWAITING_DATA, AWAITING_PREPAY, CALCULATED, CLARIFYING, HOT, INTERESTED,
    LADDER, NEEDS_CURATOR, ORDER_CREATED,
)

# Тексты — из боевых скриптов (id 367, 380, 381, 382 на проде): лестница читает
# именно их, и подменять их выдуманными значит проверять не то.
PRICE_TEXT = "Стоимость толстовки с термо-принтами со скидкой СЕГОДНЯ - 5 990 ₽ (вместо 7 990 ₽)"
DELIVERY_QUESTION = "В какой город нужна будет доставка?"
CHECKOUT_TEXT = "Получается сумма заказа - 5 990 ₽\n\nА по оплате у нас есть 2 удобных варианта:"
CONTACTS_TEXT = (
    "Отлично, тогда подскажите, пожалуйста, ФИО и номер телефона получателя посылки, "
    "выставлю счет на предоплату"
)
PAYMENT_LINK_TEXT = "Вот счет-ссылка на 500 рублей: https://monro-book-payment.online/pay/500"


@pytest.fixture
async def statuses(db):
    """Лестница в базе — как её заводит миграция 054."""
    for order, name in enumerate(LADDER, start=1):
        db.add(DialogStatusConfig(name=name, pattern="", is_active=True, sort_order=order * 10))
    db.add(DialogStatusConfig(name=NEEDS_CURATOR, pattern="", is_active=True, sort_order=800))
    await db.commit()


@pytest.fixture
async def dialog(db):
    client = Client(vk_user_id=555, name="Алексей")
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=None, is_test=False)
    db.add(d)
    await db.flush()
    await db.commit()
    return d


async def _say(db, dialog, role, text, delivered=True):
    meta = None if delivered else {"delivery_failed": True}
    db.add(Message(dialog_id=dialog.id, role=role, text=text, msg_metadata=meta))
    await db.commit()


async def ours(db, dialog, text, delivered=True):
    await _say(db, dialog, MessageRole.ai, text, delivered)


async def manager(db, dialog, text):
    await _say(db, dialog, MessageRole.curator, text)


async def client_says(db, dialog, text):
    await _say(db, dialog, MessageRole.client, text)


class TestRungs:
    async def test_greeting_only_is_the_starting_rung(self, db, dialog):
        await ours(db, dialog, "Здравствуйте! Какое имя или фамилию напишем на кофте?")
        await client_says(db, dialog, "Смирнов")
        assert await earned_status(db, dialog) == INTERESTED

    async def test_delivered_price_earns_calculated(self, db, dialog):
        await ours(db, dialog, PRICE_TEXT)
        assert await earned_status(db, dialog) == CALCULATED

    async def test_undelivered_price_earns_nothing(self, db, dialog):
        """Диалог 78880, 24.08: связка с ценой не доехала, а сумму за диалогом
        уже закрепили — и следующий ход решил, что клиент цену видел."""
        await ours(db, dialog, PRICE_TEXT, delivered=False)
        assert await earned_status(db, dialog) == INTERESTED

    async def test_silence_after_the_price_stays_on_calculated(self, db, dialog):
        """Ровно случай со скриншота ОП: расчёт ушёл, задан вопрос про город,
        клиент молчит — дальше работают пинги."""
        await ours(db, dialog, PRICE_TEXT)
        await ours(db, dialog, DELIVERY_QUESTION)
        assert await earned_status(db, dialog) == CALCULATED

    async def test_city_after_the_price_earns_clarifying(self, db, dialog):
        await ours(db, dialog, PRICE_TEXT)
        await ours(db, dialog, DELIVERY_QUESTION)
        await client_says(db, dialog, "Казань")
        assert await earned_status(db, dialog) == CLARIFYING

    async def test_size_also_counts_as_clarifying(self, db, dialog):
        await ours(db, dialog, PRICE_TEXT)
        await client_says(db, dialog, "180 90")
        assert await earned_status(db, dialog) == CLARIFYING

    async def test_payment_options_earn_hot(self, db, dialog):
        """Новый смысл «Горячего» от 27.08: отправили способы оплаты."""
        await ours(db, dialog, PRICE_TEXT)
        await client_says(db, dialog, "Казань")
        await ours(db, dialog, CHECKOUT_TEXT)
        assert await earned_status(db, dialog) == HOT

    async def test_price_script_alone_is_not_hot(self, db, dialog):
        """В скрипте стоимости есть строка «Всю сумму сразу вносить не нужно» —
        способом оплаты она не считается, иначе расчёт сразу давал бы «Горячий»."""
        await ours(db, dialog, PRICE_TEXT + "\n\n✅Всю сумму сразу вносить не нужно, есть оплата частями")
        assert await earned_status(db, dialog) == CALCULATED

    async def test_contacts_request_earns_awaiting_data(self, db, dialog):
        await ours(db, dialog, CHECKOUT_TEXT)
        await ours(db, dialog, CONTACTS_TEXT)
        assert await earned_status(db, dialog) == AWAITING_DATA

    async def test_payment_link_earns_awaiting_prepay(self, db, dialog):
        await ours(db, dialog, CONTACTS_TEXT)
        await ours(db, dialog, PAYMENT_LINK_TEXT)
        assert await earned_status(db, dialog) == AWAITING_PREPAY

    async def test_confirmed_payment_earns_order_created(self, db, dialog):
        from app.utils.time import msk_now

        await ours(db, dialog, PAYMENT_LINK_TEXT)
        dialog.payment_confirmed_at = msk_now()
        assert await earned_status(db, dialog) == ORDER_CREATED

    async def test_manager_messages_count_too(self, db, dialog):
        """665 диалогов ведёт живой оператор при выключенном ИИ — им ступени
        нужны ровно так же. Реплика менеджера засчитывается там, где клиент
        заговорил: иначе это рассылка, а не работа с лидом."""
        await client_says(db, dialog, "здравствуйте")
        await manager(db, dialog, CHECKOUT_TEXT)
        assert await earned_status(db, dialog) == HOT

    async def test_client_own_words_never_earn_a_rung(self, db, dialog):
        """Клиент написал сумму сам («видел за 3000 руб») — расчётом это не
        является: считаем только НАШИ доставленные сообщения."""
        await client_says(db, dialog, "на маркетплейсе видел такое же за 3000 руб")
        assert await earned_status(db, dialog) == INTERESTED


class TestSync:
    async def _name(self, db, dialog):
        if not dialog.current_status_id:
            return None
        return (await db.get(DialogStatusConfig, dialog.current_status_id)).name

    async def test_moves_the_dialog_up(self, db, dialog, statuses):
        await ours(db, dialog, PRICE_TEXT)
        assert await sync_status(db, dialog) == CALCULATED
        assert await self._name(db, dialog) == CALCULATED

    async def test_never_moves_back(self, db, dialog, statuses):
        """«Горячий» → «Есть расчет» → «Горячий» в диалоге 142 — именно то, чего
        лестница делать не должна."""
        hot = await db.scalar(
            select(DialogStatusConfig).where(DialogStatusConfig.name == HOT)
        )
        dialog.current_status_id = hot.id
        await ours(db, dialog, PRICE_TEXT)
        assert await sync_status(db, dialog) is None
        assert await self._name(db, dialog) == HOT

    async def test_does_not_touch_side_statuses(self, db, dialog, statuses):
        """Диалог, переданный человеку, обязан остаться переданным."""
        curator = await db.scalar(
            select(DialogStatusConfig).where(DialogStatusConfig.name == NEEDS_CURATOR)
        )
        dialog.current_status_id = curator.id
        await ours(db, dialog, PAYMENT_LINK_TEXT)
        assert await sync_status(db, dialog) is None
        assert await self._name(db, dialog) == NEEDS_CURATOR

    async def test_missing_status_row_is_not_an_error(self, db, dialog):
        """Имена статусов заводят руками. Нет строки в базе — ход не падает."""
        await ours(db, dialog, PRICE_TEXT)
        assert await sync_status(db, dialog) is None
        assert dialog.current_status_id is None

    async def test_order_created_stops_the_pings(self, db, dialog, statuses):
        from app.utils.time import msk_now

        db.add(DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=1, is_completed=False,
        ))
        await ours(db, dialog, PAYMENT_LINK_TEXT)
        dialog.payment_confirmed_at = msk_now()
        assert await sync_status(db, dialog) == ORDER_CREATED
        state = await db.scalar(
            select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
        )
        assert state.is_completed is True

    async def test_repeated_call_is_a_no_op(self, db, dialog, statuses):
        await ours(db, dialog, PRICE_TEXT)
        assert await sync_status(db, dialog) == CALCULATED
        assert await sync_status(db, dialog) is None


class TestBroadcasts:
    """Рассылка — не шаг воронки, даже если в ней есть цена.

    Рассылки лежат в тех же строках с ролью curator: 604 604 сообщения из
    667 561. «ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА» ушла в 58 238 диалогов. Без этого
    различия расчётом считался бы каждый, кому пришло рекламное письмо.
    """

    async def test_broadcast_with_a_price_earns_nothing(self, db, dialog):
        db.add(Message(
            dialog_id=dialog.id, role=MessageRole.curator,
            text="💥ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА",
            msg_metadata={"broadcast": True},
        ))
        await db.commit()
        assert await earned_status(db, dialog) == INTERESTED

    async def test_same_text_without_the_mark_counts_in_a_live_dialog(self, db, dialog):
        """Пометку ставит вебхук по разлёту текста. Нет пометки, а клиент в
        диалоге разговаривает — это ответ менеджера, и цена в нём настоящая."""
        await client_says(db, dialog, "а сколько стоит?")
        await manager(db, dialog, "💥ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА")
        assert await earned_status(db, dialog) == CALCULATED

    async def test_marked_broadcast_ignored_even_in_a_live_dialog(self, db, dialog):
        """Клиент заговорил — но рассылка всё равно не шаг воронки."""
        await client_says(db, dialog, "а сколько стоит?")
        db.add(Message(
            dialog_id=dialog.id, role=MessageRole.curator,
            text="💥ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА", msg_metadata={"broadcast": True},
        ))
        await db.commit()
        assert await earned_status(db, dialog) == INTERESTED

    async def test_broadcast_does_not_hide_a_real_price(self, db, dialog):
        db.add(Message(
            dialog_id=dialog.id, role=MessageRole.curator,
            text="💥ТОЛСТОВКА ЗА 4 990₽", msg_metadata={"broadcast": True},
        ))
        await db.commit()
        await ours(db, dialog, PRICE_TEXT)
        assert await earned_status(db, dialog) == CALCULATED

    async def test_mailing_only_dialog_stays_on_the_first_rung(self, db, dialog):
        """Персонализированную рассылку («⏰ Андрей, осталась всего неделя… Один
        свитшот — 4 790 руб.») по тексту от менеджерской реплики не отличить:
        имя стоит в середине, порог по разлёту она не набирает. Отличает её то,
        что клиент в диалоге не написал ни слова — отвечать там некому.
        Диалог 383 на проде: двенадцать рекламных писем, ноль сообщений клиента.
        """
        await manager(db, dialog, "⏰ Андрей, осталась всего неделя! Один свитшот — 4 790 руб.")
        await manager(db, dialog, "💥ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА")
        assert await earned_status(db, dialog) == INTERESTED

    async def test_manager_price_counts_once_the_client_spoke(self, db, dialog):
        await client_says(db, dialog, "здравствуйте, а сколько стоит?")
        await manager(db, dialog, "Остаток: 3980 руб. Внести: https://pay.tbank.ru/QoKBoGjq")
        assert await earned_status(db, dialog) == AWAITING_PREPAY

    async def test_our_own_price_counts_without_a_client_message(self, db, dialog):
        """В MAX клиент нажимает «Начать» и получает приветствие и цену, не
        написав ни строчки. Наши собственные сообщения — всегда шаг воронки."""
        await ours(db, dialog, PRICE_TEXT)
        assert await earned_status(db, dialog) == CALCULATED


class TestSideEffectsRespectTheManager:
    async def test_prepay_does_not_restart_pings_on_a_paused_dialog(self, db, dialog, statuses):
        """Счёт выставил менеджер, забравший диалог: лестницу зовёт его же ответ,
        и пинги там только что погашены. Заводить воронку заново — писать поверх
        живого разговора."""
        dialog.ai_paused = True
        await client_says(db, dialog, "а как оплатить?")
        await manager(db, dialog, PAYMENT_LINK_TEXT)
        assert await sync_status(db, dialog) == AWAITING_PREPAY
        state = await db.scalar(
            select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
        )
        assert state is None
