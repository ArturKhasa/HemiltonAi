"""Шаги воронки ОП1, которые обязаны уйти клиенту независимо от решения модели.

Регламент ОП описывает воронку как лестницу: «2. Похвала» уходит связкой вместе
с «2.2 Стоимость» и «2.3 Доставка», ссылка на оплату — сразу после того, как
клиент дал ФИО и телефон. Связки разворачивает runner по follow_up_script_id,
но точка входа в связку до сих пор зависела от того, поставит ли модель
source_script_id.

На проде она его не поставила (диалог 52, ai_run 565): вместо скрипта «2. Похвала»
модель написала свой пересказ «Супер, зафиксировала «Соколова»», связка не
развернулась, цена не ушла — и дальше семь ходов подряд она спрашивала «какой
дизайн нанесём на кофту?», потому что без цены в истории стадия зажата в greeting.
Промптом это чинить бессмысленно: пропущенный шаг воронки — не вопрос
формулировки, а вопрос того, ушло сообщение или нет.
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole, Script

logger = logging.getLogger(__name__)

# «2. Похвала» — присоединение после ответа на вопрос про имя/фамилию. Именно с
# него начинается связка «похвала → стоимость → доставка».
_PRAISE_CONDITION_RE = re.compile(r"похвал", re.I)

# «4.2 Зафиксировали дизайн» — начало связки «фиксация → оформление → данные».
# В выгрузке ОП условие записано как «информируем, что всю информацию по дизайну
# зафиксировали», поэтому ловим оба порядка слов.
_DESIGN_FIXED_CONDITION_RE = re.compile(
    r"зафиксировали\s+дизайн|по\s+дизайну\s+зафиксировал", re.I
)

# «5.2 Ссылка на оплату» — единственный скрипт стадии payment_link со ссылкой.
_PAYMENT_LINK_CONDITION_RE = re.compile(r"ссылк\w*\s+на\s+оплату", re.I)

# Наш вопрос-сверка в конце шага «дизайн»: «…Всё верно?».
_ASKS_CONFIRMATION_RE = re.compile(r"вс[её]\s+верно", re.I)

# Согласие клиента. Отрицание («нет», «не верно») сюда не попадает — там шаг
# ещё не закрыт и связку разворачивать рано.
_AFFIRMATIVE_RE = re.compile(
    r"^\W*(да|ага|угу|верно|вс[её]\s+верно|да[, ]+вс[её]\s+верно|точно|именно|"
    r"подтверждаю|подходит|согласн\w+|оформляем|давайте)\b[\s\S]{0,20}$",
    re.I,
)

# Шаг «5. Оформление» показан: названа сумма заказа и способы оплаты. Тем же
# шаблоном проверяем и свежий ответ модели — если она рассказала про оплату сама,
# слать следом скрипт нельзя, клиент получит одно и то же дважды.
CHECKOUT_PRESENTED_RE = re.compile(
    r"сумма заказа|по оплате у нас|способ\w*\s+оплат|оплатить всю сумму|"
    r"внести\s+(?:всю сумму|бронь)", re.I,
)

# «5.1 Данные перед оформлением» — запрос ФИО и телефона получателя.
_CONTACTS_CONDITION_RE = re.compile(r"данные\s+перед\s+оформлением", re.I)

# Вопрос из «5. Оформление»: «Удобно оплатить всю сумму сразу с подарком или
# сначала 500 рублей?».
_ASKS_PAYMENT_CHOICE_RE = re.compile(
    r"всю сумму сразу|сначала 500|вс[её]\s+сразу\s+или", re.I
)

# Клиент выбрал вариант оплаты. Список закрытый: на «дорого» или «а можно
# дешевле» шаг не закрыт, и данные получателя запрашивать рано.
_PAYMENT_CHOICE_RE = re.compile(
    r"\b(500|пятьсот|частями|част\w+|рассрочк\w+|всю\s+сумму|полность\w+|сразу|"
    r"перв\w+|втор\w+|подарок|да|давайте|хорошо|ок|окей)\b",
    re.I,
)

# Все платёжные ссылки проекта содержат «pay» в URL (monro-book-payment.online,
# параметр ?pay=1000, заглушка example.com/pay/500); фото и CDN-ссылки — нет.
PAYMENT_LINK_RE = re.compile(r"https?://\S*pay", re.IGNORECASE)


async def _pick(db: AsyncSession, type_id: int | None, pattern: re.Pattern) -> Script | None:
    """Наименьший по id активный скрипт, чьё условие совпало с шаблоном.
    Наименьший — чтобы выбор был воспроизводимым: в выгрузке ОП условия
    дублируются под разные варианты товара."""
    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    rows = (await db.execute(q.order_by(Script.id))).scalars().all()
    for s in rows:
        if pattern.search(s.condition or "") and (s.phrase_text or "").strip():
            return s
    return None


async def find_praise_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _PRAISE_CONDITION_RE)


async def find_design_fixed_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _DESIGN_FIXED_CONDITION_RE)


async def find_payment_link_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _PAYMENT_LINK_CONDITION_RE)


async def _last_outgoing(db: AsyncSession, dialog_id: int) -> str | None:
    return await db.scalar(
        select(Message.text)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.id.desc())
        .limit(1)
    )


async def design_just_confirmed(db: AsyncSession, dialog_id: int, client_text: str) -> bool:
    """Клиент подтвердил сверку дизайна — по регламенту следом идут фиксация,
    сумма заказа со способами оплаты и запрос данных получателя.

    Без этого воронка вставала на месте: в прогоне на «да всё верно» модель
    прислала ту же сверку ещё раз, и клиент до оформления не доехал.
    """
    if not _AFFIRMATIVE_RE.match((client_text or "").strip()):
        return False
    last = await _last_outgoing(db, dialog_id)
    return bool(last and _ASKS_CONFIRMATION_RE.search(last))


async def find_contacts_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _CONTACTS_CONDITION_RE)


async def payment_option_chosen(db: AsyncSession, dialog_id: int, client_text: str) -> bool:
    """Клиент ответил на вопрос «всю сумму сразу или сначала 500 рублей?».

    Только теперь по регламенту уместно «Отлично, тогда подскажите ФИО и номер
    телефона»: и само «тогда», и сумма в счёте зависят от этого ответа. Раньше
    оба сообщения уходили одним ходом, и вопрос про способ оплаты оставался без
    ответа — клиент читал реакцию на выбор, которого не делал.
    """
    text = (client_text or "").strip()
    if not text or "?" in text or not _PAYMENT_CHOICE_RE.search(text):
        return False
    last = await _last_outgoing(db, dialog_id)
    return bool(last and _ASKS_PAYMENT_CHOICE_RE.search(last))


async def checkout_presented(db: AsyncSession, dialog_id: int) -> bool:
    """Сумма заказа и способы оплаты уже показаны — счёт выставлять можно."""
    rows = await db.execute(
        select(Message.text).where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
    )
    return any(CHECKOUT_PRESENTED_RE.search(t or "") for (t,) in rows.all())


async def dialog_has_payment_link(db: AsyncSession, dialog_id: int) -> bool:
    """Ссылка на оплату уже уходила клиенту в этом диалоге.

    Сверяем в Python, а не regexp-оператором СУБД: шаблон один и тот же и для
    истории, и для свежего ответа модели, а диалог короткий.
    """
    rows = await db.execute(
        select(Message.text).where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
    )
    return any(PAYMENT_LINK_RE.search(t or "") for (t,) in rows.all())


async def answered_inscription_question(db: AsyncSession, dialog_id: int) -> bool:
    """Последнее наше сообщение — вопрос воронки про имя/фамилию для нанесения.

    Значит текущая реплика клиента и есть ответ на него, а следом по регламенту
    обязаны уйти похвала, стоимость и доставка.
    """
    from app.sales.order_slots import ASKS_INSCRIPTION_RE

    last = await db.scalar(
        select(Message.text)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    return bool(last and ASKS_INSCRIPTION_RE.search(last))
