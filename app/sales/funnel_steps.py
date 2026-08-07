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
from app.sales.order_slots import asked_slot, has_size

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

# «5. Оформление» — сумма заказа и способы оплаты.
_CHECKOUT_CONDITION_RE = re.compile(r"5\.\s*Оформление", re.I)

# «4.1 Согласовываем дизайн» — сверка раскладки нанесений перед фиксацией.
# В выгрузке ОП условие записано с опечаткой («Предвратильно»), поэтому ловим
# только по «согласовываем дизайн».
_DESIGN_REVIEW_CONDITION_RE = re.compile(r"согласовываем\s+дизайн", re.I)

# Пример надписи в тексте скрипта: «На груди по центру - надпись "РОССИЯ"».
# Печатаем на изделии то, что заказал клиент, — подставляем его надпись сюда.
_DESIGN_INSCRIPTION_RE = re.compile(r"надпись\s*[«\"„][^»\"“]*[»\"“]", re.I)

# Ответ двигает заказ к оплате. Проверяем и текст, не только source_script_id:
# фразу шага модель пишет и своими словами, без ссылки на скрипт.
_FUNNEL_ADVANCE_TEXT_RE = re.compile(
    r"фиксирую\s+под\s+вас|ставлю\s+(?:его\s+)?в\s+работу|передаю\s+(?:его\s+)?в\s+работу|"
    r"зафиксировал\w*\s+дизайн|фио\s+и\s+(?:номер\s+)?телефон", re.I,
)


def render_design_inscription(text: str, inscription: str | None) -> str:
    """Подставить надпись клиента в строку раскладки вместо примера «РОССИЯ»."""
    if not inscription:
        return text
    return _DESIGN_INSCRIPTION_RE.sub(lambda _: f"надпись «{inscription}»", text, count=1)


# Элементы раскладки. В скрипте она записана под патриотическую линейку — герб,
# флаг и надпись «РОССИЯ», — но это пример, а не то, что заказал клиент: на
# «Чебурек» ему пришло «На груди слева - герб РФ / На спине - герб РФ», хотя
# герба он не просил. Строку оставляем, только если её элемент клиент называл.
_DESIGN_ELEMENT_RES = {
    "герб": re.compile(r"герб|орёл|орел", re.I),
    "флаг": re.compile(r"флаг|триколор", re.I),
    "надпись": re.compile(r"надпись", re.I),
}


def render_design_review(
    text: str, inscription: str | None, client_texts: list[str],
) -> str | None:
    """Раскладка из скрипта, обрезанная до того, что заказал клиент.

    Возвращает None, когда согласовывать нечего: ни надписи, ни герба, ни флага
    клиент не называл — тогда шаг ведёт модель, ей есть что спросить.
    """
    requested = {
        name for name, rx in _DESIGN_ELEMENT_RES.items()
        if any(rx.search(t or "") for t in client_texts)
    }
    if inscription:
        requested.add("надпись")
    else:
        requested.discard("надпись")
    if not requested:
        return None

    kept: list[str] = []
    layout_lines = 0
    for line in (text or "").split("\n"):
        elements = {name for name, rx in _DESIGN_ELEMENT_RES.items() if rx.search(line)}
        if elements:
            if not elements & requested:
                continue
            layout_lines += 1
        kept.append(line)
    if not layout_lines:
        return None
    return render_design_inscription(
        re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), inscription,
    )


def reply_advances_funnel(reply_text: str, source_script_id: int | None,
                          advancing_ids: set[int]) -> bool:
    """Ответ фиксирует дизайн, называет сумму, просит контакты или счёт."""
    if source_script_id is not None and source_script_id in advancing_ids:
        return True
    text = reply_text or ""
    return bool(CHECKOUT_PRESENTED_RE.search(text) or _FUNNEL_ADVANCE_TEXT_RE.search(text))

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

# Отказ клиента. «Спасибо не надо», «Не надо», «Не надо мне» — модель прочитала
# их как согласие: на третье подряд она ответила «фиксирую под Вас этот вариант»
# и следом развернула связку со счётом на 4 990 ₽ (диалог 89, 11:24-11:25).
_REFUSAL_RE = re.compile(
    r"^\W*(?:(?:нет|спасибо|ой|ну|да)\W+){0,2}"
    r"(?:не\s+(?:надо|нужно|хочу|буду|интересует|интересно|актуально|готов\w*)"
    r"|нет\b|отказ\w*|откажусь|передума\w+|отмен(?:а|ю|и|ите|ить|яем)\w*"
    r"|ничего\s+не\s+(?:надо|нужно))",
    re.I,
)

# «Нет, всё верно» — отрицание относится к сомнению, а не к заказу: шаг закрыт
# согласием. Проверяем только у голого «нет»: «не хочу, всё верно» не бывает.
_CONFIRMS_RE = re.compile(
    r"вс[её]\s+верно|верно|так\s+и\s+есть|правильно|согласн\w+|подходит", re.I,
)

# «Не надо частями, давайте всю сумму» — это выбор способа оплаты, не отказ.
_REFUSAL_WITH_CHOICE_RE = re.compile(r"вс[юей]\w*\s+сумм|частями|500|бронь", re.I)


def client_refused(client_text: str) -> bool:
    """Клиент отказывается — воронку двигать нельзя.

    Отказ на сверке дизайна модель принимает за подтверждение, а дальше по
    регламенту идут фиксация, сумма заказа и запрос данных получателя. Клиент
    трижды сказал «не надо» и получил счёт.
    """
    text = (client_text or "").strip()
    m = _REFUSAL_RE.match(text)
    if not m or _REFUSAL_WITH_CHOICE_RE.search(text):
        return False
    if m.group(0).strip(" ,.!-").lower() == "нет" and _CONFIRMS_RE.search(text):
        return False
    return True


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
#
# Шаблон требует ОБА варианта и «или» между ними. По одной лишь «всей сумме
# сразу» ловилась отработка «дорого» — «Всю сумму сразу вносить не нужно, можно
# оплатить частями. Подойдёт такой вариант?»: клиент отвечал «Да» на согласие с
# ценой, а следом ему прилетал запрос ФИО и телефона.
_ASKS_PAYMENT_CHOICE_RE = re.compile(
    r"(?:вс[юей]\w*\s+сумм\w*\s+сразу|с\s+подарком).{0,60}\bили\b.{0,60}(?:500|частями)"
    r"|(?:500|частями).{0,60}\bили\b.{0,60}(?:вс[юей]\w*\s+сумм\w*\s+сразу|с\s+подарком)",
    re.I | re.S,
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


async def find_design_review_script(db: AsyncSession, type_id: int | None) -> Script | None:
    """«4.1 Согласовываем дизайн» — раскладка нанесений перед фиксацией."""
    return await _pick(db, type_id, _DESIGN_REVIEW_CONDITION_RE)


async def funnel_advancing_script_ids(db: AsyncSession, type_id: int | None) -> set[int]:
    """Шаги, которые двигают заказ к оплате: фиксация дизайна, оформление,
    данные получателя, ссылка на счёт. После отказа клиента ни один из них
    уходить не должен."""
    ids = set()
    for finder in (
        _DESIGN_FIXED_CONDITION_RE,
        _CHECKOUT_CONDITION_RE,
        _CONTACTS_CONDITION_RE,
        _PAYMENT_LINK_CONDITION_RE,
    ):
        s = await _pick(db, type_id, finder)
        if s is not None:
            ids.add(s.id)
    return ids


async def find_design_fixed_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _DESIGN_FIXED_CONDITION_RE)


async def find_checkout_script(db: AsyncSession, type_id: int | None) -> Script | None:
    """«5. Оформление» — сумма заказа и два способа оплаты."""
    return await _pick(db, type_id, _CHECKOUT_CONDITION_RE)


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


async def size_just_given(db: AsyncSession, dialog_id: int, client_text: str) -> bool:
    """Клиент назвал рост и вес в ответ на наш вопрос про размер — по регламенту
    следующим ходом идёт сверка дизайна.

    Свой пересказ вместо скрипта модель уже писала: «Элементы дизайна - только
    надпись «Орех», расположение не уточнено» (диалог 89) — раскладка нанесений
    из скрипта потерялась целиком, а вместе с ней и место надписи.
    """
    if not client_text or "?" in client_text or not has_size(client_text):
        return False
    last = await _last_outgoing(db, dialog_id)
    return bool(last and asked_slot(last) == "size")


# Пинг «Давайте начистоту, из-за чего молчите?» со списком причин 1-7 (скрипты
# 440 и 466). Клиент отвечает одной цифрой, и для модели это просто «1» —
# смысла в ней столько же, сколько в опечатке.
_ASKS_HONEST_RE = re.compile(r"начистоту|из-за чего молчите", re.I)

HONEST_OPTIONS = {
    "1": "Заказ не актуален",
    "2": "Сомневаюсь в предоплате",
    "3": "У вас дорого",
    "4": "Планирую делать заказ позже",
    "5": "Нет времени пообщаться",
    "6": "Думаю что вы мошенники",
    "7": "Другое",
}

# Причины, после которых продажу ведёт человек: заказ отменён и обвинение в
# мошенничестве — не те возражения, которые отрабатывают скриптом.
HONEST_CURATOR_OPTIONS = frozenset({"1", "6"})

_BARE_DIGIT_RE = re.compile(r"^\W*([1-7])\W*$")


async def honest_answer(db: AsyncSession, dialog_id: int, client_text: str) -> str | None:
    """Цифра, которой клиент ответил на список «давайте начистоту», либо None."""
    m = _BARE_DIGIT_RE.match((client_text or "").strip())
    if not m:
        return None
    last = await _last_outgoing(db, dialog_id)
    if not last or not _ASKS_HONEST_RE.search(last):
        return None
    return m.group(1)


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
