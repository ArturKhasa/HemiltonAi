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
from app.utils.text import looks_like_surname
from app.vk.outgoing import delivered_only, was_delivered

logger = logging.getLogger(__name__)

# Сколько последних исходящих просматриваем в поисках доставленного. Подряд
# недоставленных бывает не больше одного хода, пяти хватает с запасом.
_OUTGOING_LOOKBACK = 5


async def _outgoing_texts(db: AsyncSession, dialog_id: int) -> list[str]:
    """Тексты всех наших сообщений диалога, дошедших до клиента."""
    rows = await db.execute(
        select(Message).where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
    )
    return [m.text for m in delivered_only(list(rows.scalars().all()))]

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

# «2.2 Стоимость» — первый прайс. Второй раз его слать незачем: клиент цену уже
# видел, а на возражение отвечают отдельные скрипты отработки. В диалоге 156
# прайс ушёл трижды — в 12:32, 14:29 и 14:32 (замечание ОП от 10 августа, 13:53:
# «Опять отправили цену»).
_PRICE_CONDITION_RE = re.compile(r"2\.2\s*Стоимость", re.I)

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
    r"зафиксировал\w*\s+дизайн|фио\s+и\s+(?:номер\s+)?телефон|"
    # Текст скрипта «2. Похвала» — модель пишет его и без ссылки на скрипт.
    r"^\W*(?:супер|отлично)\W+зафиксировал", re.I,
)


def render_design_inscription(text: str, inscription: str | None) -> str:
    """Подставить надпись клиента в строку раскладки вместо примера «РОССИЯ»."""
    if not inscription:
        return text
    return _DESIGN_INSCRIPTION_RE.sub(lambda _: f"надпись «{inscription}»", text, count=1)


# Место нанесения по умолчанию. В скрипте раскладка записана под патриотическую
# линейку, где по центру груди идёт надпись «РОССИЯ», — и модель ставила туда же
# имя клиента. ОП, 22.08: «ИИ во всех диалогах прописывает имя спереди
# посередине, мы так не делаем. Если имя — то это по умолчанию на груди справа.
# Если фамилия — то это по умолчанию на спине с гербом».
_NAME_PLACEMENT = "На груди справа"
_SURNAME_PLACEMENT = "На спине"

# Место в строке раскладки — всё, что стоит слева от тире: «На груди по центру -
# надпись "РОССИЯ"».
_LAYOUT_PLACE_RE = re.compile(r"^[^\n\-]*-\s*(?=надпись)", re.I)

# Клиент назвал место сам — его слово главнее умолчания. Андрей Олейник, 22.08:
# «по центру не нужно. Лучше слева и небольшими буквами».
_CLIENT_PLACEMENT_RES = (
    (re.compile(r"на\s+спин[еу]|сзади|со\s+спины", re.I), "На спине"),
    (re.compile(r"на\s+рукав\w*", re.I), "На рукаве справа"),
    (re.compile(r"\bслева\b|\bлев\w+\s+сторон\w+", re.I), "На груди слева"),
    (re.compile(r"\bсправа\b|\bправ\w+\s+сторон\w+", re.I), "На груди справа"),
    (re.compile(r"по\s+центру|посередине|посредине|в\s+центре", re.I), "На груди по центру"),
)

# То же место, но разложенное на блок и строку внутри него — для формата, которым
# сверку пишут менеджеры (см. build_design_layout).
_PLACEMENT_SECTIONS = {
    "На спине": ("НА СПИНЕ", "Сверху"),
    "На рукаве справа": ("рукав", "На правом рукаве"),
    "На груди слева": ("НА ГРУДИ", "Слева"),
    "На груди справа": ("НА ГРУДИ", "Справа"),
    "На груди по центру": ("НА ГРУДИ", "По центру"),
}

# Куски реплики. «по центру не нужно» и «лучше слева» — два разных куска, и
# отрицание относится только к первому.
_CLAUSE_SPLIT_RE = re.compile(r"[.,;!?\n]+|\bно\b|\bа\s+лучше\b|\bлучше\b")
_NEGATION_RE = re.compile(r"\bне\b|\bнет\b|\bбез\b", re.I)
# Кусок про герб или флаг — место в нём относится к ним, а не к надписи.
_OTHER_ELEMENT_RE = re.compile(r"герб|орёл|орел|флаг|триколор", re.I)
_INSCRIPTION_WORD_RE = re.compile(r"надпис|им[яё]|фамили|букв", re.I)


def _stated_placement(client_texts: list[str]) -> str | None:
    """Место нанесения надписи, названное самим клиентом, либо None."""
    found: str | None = None
    for raw in client_texts:
        for clause in _CLAUSE_SPLIT_RE.split(raw or ""):
            if _NEGATION_RE.search(clause):
                continue
            if _OTHER_ELEMENT_RE.search(clause) and not _INSCRIPTION_WORD_RE.search(clause):
                continue
            for rx, place in _CLIENT_PLACEMENT_RES:
                if rx.search(clause):
                    found = place
                    break
    return found


def _default_placement(inscription: str) -> tuple[str, bool]:
    """Место по умолчанию и нужен ли рядом герб: фамилия идёт на спину с гербом."""
    if any(looks_like_surname(w) for w in re.split(r"[\s,]+", inscription) if w):
        return _SURNAME_PLACEMENT, True
    return _NAME_PLACEMENT, False


def render_design_placement(
    text: str, inscription: str | None, client_texts: list[str], emblem_requested: bool = False,
) -> str:
    """Проставить в строке с надписью место нанесения вместо примера из скрипта."""
    if not inscription:
        return text
    place = _stated_placement(client_texts)
    with_emblem = False
    if place is None:
        place, with_emblem = _default_placement(inscription)
    # Герб клиент назвал сам — он уже стоит отдельной строкой раскладки, второй
    # раз в строке с надписью его не повторяем.
    head = f"{place} - герб РФ и " if with_emblem and not emblem_requested else f"{place} - "
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if _LAYOUT_PLACE_RE.search(line):
            lines[i] = _LAYOUT_PLACE_RE.sub(lambda _: head, line, count=1)
            break
        # Строка без места («надпись «Соколов»») — место дописываем перед ней.
        if line.lstrip().lower().startswith("надпись"):
            lines[i] = head + line.lstrip()
            break
    return "\n".join(lines)


# Элементы раскладки. В скрипте она записана под патриотическую линейку — герб,
# флаг и надпись «РОССИЯ», — но это пример, а не то, что заказал клиент: на
# «Чебурек» ему пришло «На груди слева - герб РФ / На спине - герб РФ», хотя
# герба он не просил. Строку оставляем, только если её элемент клиент называл.
_DESIGN_ELEMENT_RES = {
    "герб": re.compile(r"герб|орёл|орел", re.I),
    "флаг": re.compile(r"флаг|триколор", re.I),
    "надпись": re.compile(r"надпись", re.I),
}


# «[раскладка]» — место нанесений в тексте скрипта сверки. Собирает его система
# из того, что клиент назвал, а формулировки вокруг остаются за панелью: ОП
# заводит свой вариант шага под каждую рекламную метку (так сделан прайс 519 под
# «hood141»), и переписывать её текст кодом нельзя. Нет плейсхолдера — скрипт
# уходит клиенту ровно так, как написан; правится только строка с надписью
# (см. render_design_placement).
_LAYOUT_PLACEHOLDER_RE = re.compile(r"\[раскладка\]", re.I)

# Блок раскладки в том виде, в каком сверку пишут менеджеры (боевые диалоги 183
# и 409, 20.08):
#
#     НА ГРУДИ
#     - Справа: Артур
#     - Слева: Герб РФ
#
#     НА СПИНЕ
#     - Сверху: Халитов
#     - В центре: Герб РФ
#
#     На правом рукаве: Флаг РФ
#
# Имя идёт на грудь справа, фамилия — на спину, герб к ней в центре: ровно то,
# что ОП просила 21.08 («Если имя — то по умолчанию на груди справа. Если
# фамилия — то по умолчанию на спине с гербом. ИИ во всех диалогах прописывает
# имя спереди посередине, мы так не делаем»).
#
# Герб здесь — термопринт, он входит в цену изделия, и добавлять его к фамилии
# по умолчанию ничего не стоит. Вышивка (в матрице «Герб на спине - вышивка»,
# 6 490 ₽) — отдельный заказ с отдельным расчётом, к раскладке отношения не имеет.
_CHEST_BLOCK = "НА ГРУДИ"
_BACK_BLOCK = "НА СПИНЕ"
_SLEEVE_BLOCK = "рукав"

# «Герб на спине» — клиент назвал место сам, и относится оно к гербу.
_BACK_RE = _CLIENT_PLACEMENT_RES[0][0]


def _split_inscription(inscription: str) -> tuple[list[str], list[str]]:
    """Слова надписи, разложенные на имена и фамилии.

    «Шишкин Кирилл» — фамилия на спину, имя на грудь: в раскладке менеджера это
    две разные строки, а не одна надпись целиком.
    """
    names: list[str] = []
    surnames: list[str] = []
    for word in re.split(r"[\s,]+", inscription or ""):
        if word:
            (surnames if looks_like_surname(word) else names).append(word)
    return names, surnames


def build_design_layout(inscription: str | None, client_texts: list[str]) -> str | None:
    """Раскладка нанесений из того, что клиент назвал сам. None — называть нечего.

    В сверку попадает только заказанное: клиенту с одной надписью «Чебурек»
    пришли ещё герб на груди, флаг на рукаве и герб на спине, которых он не
    просил (диалог 90, 11:53).
    """
    requested = {
        name for name, rx in _DESIGN_ELEMENT_RES.items()
        if any(rx.search(t or "") for t in client_texts)
    }
    chest: list[tuple[str, str]] = []
    back: list[tuple[str, str]] = []
    sleeve: list[str] = []
    emblem_on_back = any(
        _DESIGN_ELEMENT_RES["герб"].search(t or "") and _BACK_RE.search(t or "")
        for t in client_texts
    )

    if inscription:
        stated = _stated_placement(client_texts)
        if stated is not None:
            block, row = _PLACEMENT_SECTIONS[stated]
            if block == _CHEST_BLOCK:
                chest.append((row, inscription))
            elif block == _BACK_BLOCK:
                back.append((row, inscription))
            else:
                sleeve.append(inscription)
        else:
            names, surnames = _split_inscription(inscription)
            if names:
                chest.append(("Справа", " ".join(names)))
            if surnames:
                back.append(("Сверху", " ".join(surnames)))
                # Фамилия по умолчанию идёт на спину вместе с гербом.
                emblem_on_back = True

    if "герб" in requested or emblem_on_back:
        if back or emblem_on_back:
            back.append(("В центре", "Герб РФ"))
        else:
            chest.append(("Слева", "Герб РФ"))
    if "флаг" in requested:
        sleeve.append("Флаг РФ")

    if not (chest or back or sleeve):
        return None

    blocks: list[str] = []
    for title, rows in ((_CHEST_BLOCK, chest), (_BACK_BLOCK, back)):
        if rows:
            blocks.append("\n".join([title] + [f"- {row}: {value}" for row, value in rows]))
    blocks.extend(f"На правом рукаве: {item}" for item in sleeve)
    return "\n\n".join(blocks)


def render_design_review(
    text: str, inscription: str | None, client_texts: list[str],
) -> str | None:
    """Текст сверки дизайна с раскладкой того, что заказал клиент.

    Возвращает None, когда согласовывать нечего: ни надписи, ни герба, ни флага
    клиент не называл — тогда шаг ведёт модель, ей есть что спросить.
    """
    # Скрипт с плейсхолдером — единственное место, куда мы пишем: остальной текст
    # принадлежит панели.
    if _LAYOUT_PLACEHOLDER_RE.search(text or ""):
        layout = build_design_layout(inscription, client_texts)
        if not layout:
            return None
        return _LAYOUT_PLACEHOLDER_RE.sub(lambda _: layout, text, count=1).strip()

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
    body = render_design_inscription(
        re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), inscription,
    )
    return render_design_placement(
        body, inscription, client_texts, emblem_requested="герб" in requested,
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
#
# Ловим не только скриптовую формулировку: модель пишет сверку своими словами —
# «Всё так?», «Верно?», «Ничего не упустила?», «Подтверждаете?» — и счётчик
# подряд идущих сверок обнулялся, будто её и не было. Формулировка другая,
# а клиент читает одно и то же третий раз.
_ASKS_CONFIRMATION_RE = re.compile(
    r"вс[её]\s+верно"
    r"|вс[её]\s+так\s*\?"
    r"|\bверно\s*\?"
    r"|\bправильно\s*\?"
    r"|ничего\s+не\s+(?:упустила|забыла|пропустила)"
    r"|подтвержда[ею]те\s*\?"
    r"|(?:всё|все)\s+ли\s+(?:верно|правильно|так)"
    r"|ничего\s+не\s+пере(?:путала|врала)",
    re.I,
)

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
    r"^\W*(?:(?:нет|спасибо|ой|ну|да|пока|я)\W+){0,3}"
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


# Клиент просит переделать дизайн. Это не согласие и не отказ — это незакрытый
# шаг: пока правка не внесена и не подтверждена, воронку двигать нельзя.
#
# Модель читала такую реплику как подтверждение: на «Изменить дизайн» она выбрала
# скрипт «Зафиксировали дизайн» и следом отправила сумму заказа (диалог 163,
# 14:14). ОП, 13:51: «По цене не было возражений, клиенту было важно глянуть
# именно макет с внесёнными правками».
_DESIGN_EDIT_RE = re.compile(
    r"\bизменить\b|\bизмени|\bпоменя|\bпеределать\b|\bпеределай|\bисправ|"
    r"\bубрать\b|\bубери|\bдобав(?:ить|ь|ьте)\b|\bне так\b|\bне то\b|"
    r"\bзачем\b.{0,20}\bставить\b|\bправк",
    re.I,
)

# «Изменить размер», «поменять цвет» — обычный шаг воронки, а не правка макета.
_DESIGN_WORDS_RE = re.compile(
    r"дизайн|макет|надпис|букв|герб|флаг|принт|вышив|"
    r"спереди|сзади|взади|сверху|снизу|на\s+груди|на\s+спине|на\s+рукав",
    re.I,
)


def client_wants_design_edit(client_text: str) -> bool:
    """Клиент просит поменять дизайн — шаг не закрыт, дальше идти нельзя."""
    text = (client_text or "").replace("ё", "е")
    if not _DESIGN_EDIT_RE.search(text):
        return False
    return bool(_DESIGN_WORDS_RE.search(text))


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


# Прощание вместо вопроса. На «Пока ничего не нужно» модель ответила «Хорошо,
# поняла. Если решите вернуться к заказу, напишите мне» — и клиент ушёл, так и не
# сказав, что его остановило. ОП, 22.08: «Если клиент говорит, что ему ничего не
# нужно, то мы всегда обязательно уточняем, что именно ему не подошло. Клиента
# просто так не отпускаем думать/возвращаться к диалогу когда ему будет удобно.
# Тут нужно узнавать обязательно и дожимать».
#
# «Как Вам будет удобно» сюда не входит: этим заканчивается скрипт брони, и речь
# там про сроки работы, а не про то, когда клиенту вернуться.
_LETS_GO_RE = re.compile(
    r"(?:если|когда|как\s+только)\s+(?:вдруг\s+|снова\s+|что-то\s+|вам\s+)?"
    r"(?:реши\w+|надума\w+|захоти\w+|понадоб\w+|передума\w+|верн[её]\w+|"
    r"будет\s+нужн\w+|нужно\s+будет|станет\s+актуальн\w+)"
    r"|верн[её](?:мся|тесь)\s+к\s+(?:эт\w+\s+)?(?:вопрос\w*|разговор\w*|заказ\w*|диалог\w*)"
    r"|напишите\s+мне\s*[.!)]"
    r"|буду\s+на\s+связи"
    r"|обращайтесь"
    r"|хорошего\s+(?:дня|вечера)|всего\s+доброго|удачи\b",
    re.I,
)

# Вопрос про причину отказа: что именно не подошло. Ровно его на отказе и ждём.
_ASKS_REASON_RE = re.compile(
    r"что\s+(?:именно|же|такое)\b|что\s+не\s+|почему|по\s+какой\s+причине"
    r"|в\s+ч[её]м\s+(?:причина|дело|сомнени\w*|вопрос)|причин\w*"
    r"|смути\w*|останов\w*|устро\w*|подошл\w*|понрав\w*|сомнева\w*|не\s+устраива\w*",
    re.I,
)


# Отказ отказу рознь. Голое «Нет» чаще всего отвечает на наш же вопрос («Всё
# верно?», «Добавим герб?») — это правка заказа, а не уход клиента. Выяснять
# «что именно не подошло» надо там, где клиент уходит совсем: «не надо»,
# «ничего не нужно», «не актуально», «откажусь» (диалоги 77116 и 76943, 21-22.08:
# там «Нет» правило дизайн, а не закрывало разговор).
_WALKS_AWAY_RE = re.compile(
    r"не\s+(?:надо|нужно|хочу|буду|интересует|интересно|актуально|готов\w*)"
    r"|ничего\s+не\s+(?:надо|нужно)|не\s+актуальн\w*"
    r"|отказ\w*|откажусь|передума\w+|отмен(?:а|ю|и|ите|ить|яем)\w*"
    r"|нет\W+спасибо|спасибо\W+нет",
    re.I,
)


def client_walks_away(client_text: str) -> bool:
    """Клиент уходит из диалога, а не поправляет заказ словом «нет»."""
    return client_refused(client_text) and bool(_WALKS_AWAY_RE.search(client_text or ""))


def lets_client_go(reply_text: str) -> bool:
    """Ответ отпускает клиента вместо того, чтобы узнать причину отказа."""
    text = reply_text or ""
    if _LETS_GO_RE.search(text):
        return True
    # Вопроса нет вовсе — разговор закончен той же прощальной фразой, только без
    # приметных слов.
    return "?" not in text or not _ASKS_REASON_RE.search(text)


# Надпись посередине груди. Раскладку из скрипта код уже правит сам, но своими
# словами модель по-прежнему пишет «размещаем на груди по центру» (диалоги 76950
# и 77116, 21-22.08). ОП, 22.08: «мы так не делаем».
_CENTER_PLACEMENT_RE = re.compile(r"по\s+центру|посередине|посредине|в\s+центре", re.I)
_PLACEMENT_SUBJECT_RE = re.compile(r"надпис|им[яею]|фамили|размещ|нанос|напиш", re.I)


def places_inscription_in_the_center(reply_text: str, client_texts: list[str] | None = None) -> bool:
    """Ответ ставит надпись по центру, хотя клиент об этом не просил."""
    text = reply_text or ""
    if not (_CENTER_PLACEMENT_RE.search(text) and _PLACEMENT_SUBJECT_RE.search(text)):
        return False
    # Клиент сам попросил центр — тогда это его выбор, а не умолчание модели.
    return _stated_placement(client_texts or []) != "На груди по центру"


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
    """Шаги, которые двигают заказ к оплате: похвала, фиксация дизайна,
    оформление, данные получателя, ссылка на счёт. После отказа клиента ни один
    из них уходить не должен.

    Похвала попала сюда после диалога 77117 (22.08, 12:10): на «Не надо» в ответ
    на вопрос про надпись модель выбрала скрипт «2. Похвала», и связка развернула
    следом прайс и доставку. В условии скрипта так и написано — «применяй ВСЕГДА,
    чем бы клиент ни ответил», — поэтому держать его должен код."""
    ids = set()
    for finder in (
        _PRAISE_CONDITION_RE,
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


# Сколько последних наших сообщений считаем «только что спрошенным». Регламент
# требует дождаться ответа на вопрос, прежде чем задавать следующий, — но не
# запрещает переспросить, если клиент молчит несколько ходов подряд.
_RECENT_ASK_LOOKBACK = 2


async def scripts_repeating_recent_question(
    db: AsyncSession, dialog_id: int, type_id: int | None,
) -> set[int]:
    """Скрипты, которые спрашивают то же, что мы уже спросили в последних репликах.

    Исключение недавних скриптов работало по id, а модель пишет тот же вопрос и
    своими словами: в диалоге 163 она сама попросила «ФИО и телефон получателя»
    (14:15), source_script_id остался пустым, и на следующем ходу штатно выбрался
    скрипт 381 с тем же вопросом (14:16). Сравниваем не id, а о чём вопрос.
    """
    recent = await _recent_outgoing_texts(db, dialog_id, _RECENT_ASK_LOOKBACK)
    asked = {slot for slot in (asked_slot(t) for t in recent) if slot}
    if not asked:
        return set()

    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    rows = (await db.execute(q)).scalars().all()
    return {s.id for s in rows if asked_slot(s.phrase_text or "") in asked}


async def _recent_outgoing_texts(db: AsyncSession, dialog_id: int, limit: int) -> list[str]:
    """Последние доставленные исходящие, свежие первыми."""
    rows = await db.execute(
        select(Message)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.id.desc())
        .limit(limit + _OUTGOING_LOOKBACK)
    )
    return [m.text for m in rows.scalars().all() if was_delivered(m)][:limit]


# Скидочные скрипты узнаём по макросу уступки в тексте: любой из них называет
# клиенту цену ниже текущей.
_CONCESSION_MACRO_RE = re.compile(r"\[(?:минимальная-цена|цена-со-скидкой):", re.I)


async def discount_script_ids(db: AsyncSession, type_id: int | None) -> set[int]:
    """Скрипты, которые дают скидку. Показывать их модели можно только после
    повторного ценового возражения (см. app.sales.price_objection)."""
    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    rows = (await db.execute(q)).scalars().all()
    return {s.id for s in rows if _CONCESSION_MACRO_RE.search(s.phrase_text or "")}


async def find_price_script(db: AsyncSession, type_id: int | None) -> Script | None:
    """«2.2 Стоимость» — первый прайс, повторно не отправляется."""
    return await _pick(db, type_id, _PRICE_CONDITION_RE)


async def find_checkout_script(db: AsyncSession, type_id: int | None) -> Script | None:
    """«5. Оформление» — сумма заказа и два способа оплаты."""
    return await _pick(db, type_id, _CHECKOUT_CONDITION_RE)


async def find_payment_link_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _PAYMENT_LINK_CONDITION_RE)


async def _last_outgoing(db: AsyncSession, dialog_id: int) -> str | None:
    """Последнее наше сообщение, которое клиент действительно получил.

    Недоставленное сюда попадать не должно: на нём построены все точки воронки
    («клиент ответил на наш вопрос про надпись», «подтвердил сверку дизайна»), а
    отвечать он мог только на то, что видел.
    """
    rows = await db.execute(
        select(Message)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.id.desc())
        .limit(_OUTGOING_LOOKBACK)
    )
    for msg in rows.scalars().all():
        if was_delivered(msg):
            return msg.text
    return None


def asks_confirmation(text: str) -> bool:
    """Реплика заканчивается сверкой «Всё верно?»."""
    return bool(text and "?" in text and _ASKS_CONFIRMATION_RE.search(text))


async def confirmations_in_a_row(db: AsyncSession, dialog_id: int) -> int:
    """Сколько наших последних сообщений подряд закончились сверкой «Всё верно?».

    Регламент (промпт, «Отказ клиента»): «Один и тот же вопрос-сверку третий раз
    не задавай». Исполнять это было некому: защита от повторов сравнивает
    формулировки, а модель каждый раз пишет сверку заново. В диалоге 75853 их
    ушло пять подряд, 08:48–08:50, — клиент всё это время просил показать макет
    и в итоге ответил «Удачи с вашими тупыми ботами».
    """
    streak = 0
    for text in await _recent_outgoing_texts(db, dialog_id, _CONFIRMATION_LOOKBACK):
        if not asks_confirmation(text):
            break
        streak += 1
    return streak


# Сколько последних наших сообщений считаем «подряд». Ход даёт максимум пять
# сообщений, но сверка всегда последняя в ходе — трёх хватает.
_CONFIRMATION_LOOKBACK = 3


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
    return any(
        CHECKOUT_PRESENTED_RE.search(t or "") for t in await _outgoing_texts(db, dialog_id)
    )


async def dialog_has_payment_link(db: AsyncSession, dialog_id: int) -> bool:
    """Ссылка на оплату уже уходила клиенту в этом диалоге.

    Сверяем в Python, а не regexp-оператором СУБД: шаблон один и тот же и для
    истории, и для свежего ответа модели, а диалог короткий.
    """
    return any(
        PAYMENT_LINK_RE.search(t or "") for t in await _outgoing_texts(db, dialog_id)
    )


def _normalized(text: str | None) -> str:
    """Текст без пунктуации и регистра — для сравнения «это уже говорили»."""
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


async def script_already_sent(
    db: AsyncSession, dialog_id: int, phrase_text: str | None,
) -> bool:
    """Этот скрипт в диалоге уже уходил.

    Сравниваем по первой строке: она уходит дословно, а хвост скрипта модель
    переписывает и дополняет подстановками.
    """
    head = _normalized((phrase_text or "").split("\n")[0])[:40]
    if not head:
        return False
    return any(head in _normalized(t) for t in await _outgoing_texts(db, dialog_id))


async def answered_inscription_question(
    db: AsyncSession, dialog_id: int, type_id: int | None = None,
) -> bool:
    """Последнее наше сообщение — вопрос воронки про имя/фамилию для нанесения.

    Значит текущая реплика клиента и есть ответ на него, а следом по регламенту
    обязаны уйти похвала, стоимость и доставка.

    Ровно один раз за диалог. Шаблон вопроса ловит «имя … фамилия» и в сверке
    дизайна тоже — «На белом свитшоте разместим имена и фамилии: …», — и на
    уточнение «Два свитшота» клиент во второй раз получил «Супер, зафиксировала»
    вместе с заглушкой «Что скажете?» (диалог 75853, 21.08 08:47). Похвала уже
    уходила девятью минутами раньше, вместе с ценой.
    """
    from app.sales.order_slots import ASKS_INSCRIPTION_RE

    last = await _last_outgoing(db, dialog_id)
    if not last or not ASKS_INSCRIPTION_RE.search(last):
        return False
    praise = await find_praise_script(db, type_id)
    if praise is None:
        return True
    return not await script_already_sent(db, dialog_id, praise.phrase_text)
