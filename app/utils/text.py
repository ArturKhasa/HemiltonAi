"""Text post-processing helpers for outgoing messages."""
import re

# Плейсхолдер имени в текстах скриптов, унаследованных из CRM.
_NAME_PLACEHOLDER_RE = re.compile(r"\[Имя\]", re.IGNORECASE)
_CYRILLIC_NAME_RE = re.compile(r"^[А-Яа-яЁё][А-Яа-яЁё\-]*$")

# Уменьшительные — фамильярны в продаже, разворачиваем в полные.
_FULL_NAMES = {
    "женя": "Евгений", "саша": "Александр", "сашка": "Александр", "шура": "Александр",
    "макс": "Максим", "лёва": "Лев", "лева": "Лев", "тёма": "Артём", "тема": "Артём",
    "катя": "Екатерина", "катюша": "Екатерина", "маша": "Мария", "машa": "Мария",
    "миша": "Михаил", "лена": "Елена", "леночка": "Елена", "таня": "Татьяна",
    "оля": "Ольга", "аня": "Анна", "ваня": "Иван", "коля": "Николай",
    "дима": "Дмитрий", "димка": "Дмитрий", "серёжа": "Сергей", "сережа": "Сергей",
    "света": "Светлана", "наташа": "Наталья", "юля": "Юлия", "ира": "Ирина",
    "надя": "Надежда", "люба": "Любовь", "вера": "Вера", "паша": "Павел",
    "рома": "Роман", "костя": "Константин", "толя": "Анатолий", "гриша": "Григорий",
    "боря": "Борис", "витя": "Виктор", "слава": "Вячеслав", "лёша": "Алексей",
    "леша": "Алексей", "андрюша": "Андрей", "настя": "Анастасия", "ксюша": "Ксения",
    "даша": "Дарья", "поля": "Полина", "соня": "София", "зина": "Зинаида",
}

# Фамильные окончания. Клиент отвечает фамилию на вопрос «какое имя или фамилию
# напишем на кофте?» — это текст ДЛЯ НАНЕСЕНИЯ, а не форма обращения. Обращаться
# по фамилии нельзя: звучит как повестка, а не как разговор с менеджером.
_SURNAME_SUFFIXES = (
    "ов", "ова", "ев", "ева", "ёв", "ёва", "ин", "ина", "ын", "ына",
    "ский", "ская", "цкий", "цкая", "ко", "ук", "юк", "енко", "швили", "ян",
)
# Ниже пяти букв окончание не проверяем: «Ева», «Лев», «Нина», «Дина» короче
# любой фамилии и заканчиваются ровно теми же буквами.
_MIN_SURNAME_LEN = 5

# Имена, неотличимые от фамилий по окончанию. Без этого списка «Ирина»,
# «Марина», «Екатерина» и «Константин» уходили бы в безличное «Вы» — а это
# заметная доля клиентов.
_NAMES_LOOKING_LIKE_SURNAMES = {
    "алина", "ангелина", "аделина", "альбина", "валентина", "галина", "ирина",
    "карина", "каролина", "кристина", "марина", "полина", "регина", "сабина",
    "эвелина", "екатерина", "христина",
    "константин", "валентин", "мартин", "августин",
}


# «Здравствуйте! Меня зовут София, я Ваш персональный менеджер.» — приветствие и
# представление в начале реплики. Ограничены началом строки и одним предложением,
# чтобы не срезать «здравствуйте» в середине осмысленного текста.
_REPEAT_GREETING_RE = re.compile(
    r"^\s*(?:здравствуйте|добрый день|доброе утро|добрый вечер|приветствую|привет)"
    r"[!,.…\s]*"
    r"(?:меня зовут[^.!?\n]*[.!?]?\s*)?",
    re.IGNORECASE,
)


def strip_repeated_greeting(text: str) -> str:
    """Срезать приветствие, если мы уже здоровались в этом диалоге.

    Правило «не здоровайся повторно» есть в системном промпте, но модель его
    нарушает: в диалоге 13 на третьем ходу пришло «Здравствуйте! Меня зовут
    София, я Ваш персональный менеджер. Свитшот или худи...». Промпт тут не
    гарантия, а код — гарантия.

    Если после среза ничего не остаётся, возвращаем исходный текст: пустая
    реплика хуже лишнего «здравствуйте».
    """
    stripped = _REPEAT_GREETING_RE.sub("", text or "", count=1)
    # Хвост представления без приветствия: «..., я Ваш персональный менеджер.»
    stripped = re.sub(r"^\s*,?\s*я ваш[^.!?\n]*[.!?]\s*", "", stripped, count=1, flags=re.IGNORECASE)
    stripped = stripped.lstrip(" ,.!—-\n")
    if not stripped.strip():
        return text
    return stripped[:1].upper() + stripped[1:]


def looks_like_surname(word: str | None) -> bool:
    """Слово похоже на фамилию, а не на имя.

    Нужно не только для обращения. Место нанесения по умолчанию зависит от того,
    что клиент написал на изделии: имя идёт на грудь, фамилия — на спину
    (правка ОП от 22.08).
    """
    lowered = (word or "").strip().lower()
    if not lowered or not _CYRILLIC_NAME_RE.match(lowered):
        return False
    if lowered in _FULL_NAMES or lowered in _NAMES_LOOKING_LIKE_SURNAMES:
        return False
    return len(lowered) >= _MIN_SURNAME_LEN and lowered.endswith(_SURNAME_SUFFIXES)


def usable_name(client_name: str | None) -> str | None:
    """Имя, которым можно обратиться к клиенту, либо None — тогда просто «Вы».

    Отбрасываем всё, что обращением быть не может: латиницу и транслит (Max,
    Sasha), ники, эмодзи, наборы букв — и ФАМИЛИИ. Уменьшительные разворачиваем
    в полные: «Женя» в продаже фамильярно, «Евгений» — нет.
    """
    name = (client_name or "").strip()
    if not name or not _CYRILLIC_NAME_RE.match(name):
        return None
    lowered = name.lower()
    if lowered in _FULL_NAMES:
        return _FULL_NAMES[lowered]
    # Фамильный фильтр — последним: и уменьшительные («Дима»), и полные имена
    # («Ирина») кончаются на те же буквы, что фамилии, и должны пройти раньше.
    if (
        lowered not in _NAMES_LOOKING_LIKE_SURNAMES
        and len(lowered) >= _MIN_SURNAME_LEN
        and lowered.endswith(_SURNAME_SUFFIXES)
    ):
        return None
    return name[:1].upper() + name[1:]


def render_name_placeholder(text: str, client_name: str | None) -> str:
    """Подставить имя клиента в «[Имя]» скриптового текста.

    Имени нет или им нельзя обращаться (см. usable_name) — плейсхолдер
    вырезается вместе с идущей за ним запятой, а фраза начинается с большой буквы.
    """
    name = usable_name(client_name)
    if name:
        return _NAME_PLACEHOLDER_RE.sub(name, text)
    stripped = _NAME_PLACEHOLDER_RE.sub("", text).lstrip(" ,")
    return stripped[:1].upper() + stripped[1:] if stripped else stripped


def normalize_dashes(text: str) -> str:
    """Strip the em-dash / en-dash «AI tell»: model loves spaced em-dashes,
    which read as machine-written. Replace every em-dash «—» and en-dash «–»
    with a plain hyphen «-». Hyphenated words ("по-настоящему") already use a
    plain hyphen, so they stay intact.

    Also strip Markdown bold markers «**»: the model wraps emphasis in «**»,
    which renders literally as asterisks in plain-text channels.

    Also unescape literal «\n» sequences: gpt-4.1 structured output occasionally
    double-escapes newlines inside the JSON string, so after parsing the reply
    contains the two characters «\» + «n» instead of a line break (client 8548090).
    """
    text = re.sub(r"[—–]", "-", text)
    text = text.replace("**", "")
    text = text.replace("\\n", "\n")
    return text


# Обращение в начале реплики: «Иван, а цвет какой выберем?» → group(1) = «Иван».
# Латиницу тоже ловим: ей обращаться нельзя, и «Max, а цвет какой?» надо снять.
_LEADING_VOCATIVE_RE = re.compile(r"^\s*([А-ЯЁA-Z][а-яёa-z]+)\s*,\s+")

# Запятая после первого слова — ещё не обращение. Эти слова открывают реплику
# чаще любого имени, и без списка «Отлично, тогда подскажите ФИО» превращалось
# в «Тогда подскажите ФИО», а «Да, всё верно» — в «Всё верно».
_NOT_A_VOCATIVE = frozenset("""
    отлично понимаю поняла понял да нет хорошо супер конечно спасибо извините
    простите слушайте смотрите кстати итак значит окей ок верно точно ясно
    здравствуйте привет добрый доброе доброго ага угу ладно прекрасно замечательно
    жаль ну вот итого получается правильно согласна согласен рада благодарю
    пожалуйста давайте договорились принято слышу разумеется безусловно здорово
""".split())

# Глагол в повелительном наклонении, а не имя: «Подскажите, пожалуйста, ФИО…»
# начинается ровно так же, как обращение по имени, и без этой проверки скрипт
# «5.1 Данные перед оформлением» терял первое слово. Русские имена на «-те» не
# заканчиваются, так что признак надёжный и списка слов не требует.
_IMPERATIVE_SUFFIXES = ("те", "ка")


def _looks_like_a_verb(word: str) -> bool:
    return word.lower().endswith(_IMPERATIVE_SUFFIXES)


# Слово-обращение не в начале реплики, а в начале абзаца или предложения:
# «Отлично, в Ваш город доставляем СДЭК...\n\nОрех, а цвет какой выберем?».
# Так проверять любое слово нельзя — под шаблон попадают перечисления («Белый,
# бежевый, серый») и города («Казань, отличный выбор»), поэтому здесь ищется
# ровно одно слово: надпись, которую клиент заказал на изделие.
def _inscription_vocative_re(word: str) -> re.Pattern:
    return re.compile(
        rf"(^|\n|[.!?…]\s+){re.escape(word)}\s*,\s+(\S)",
        re.IGNORECASE,
    )


def strip_foreign_name(
    text: str,
    client_name: str | None,
    inscription: str | None = None,
) -> str:
    """Убрать обращение по имени, которое клиенту не принадлежит.

    Ответ на «какое имя или фамилию напишем на кофте?» — это НАДПИСЬ НА ИЗДЕЛИИ,
    а модель принимает её за имя собеседника: клиент 289653120 (в профиле имени
    нет вовсе) заказал кофту с надписью «Иван» и получил «Иван, а цвет для
    свитшота какой выберем?», а в пинге — «Пётр» из прошлого заказа. Правило в
    промпте это не удерживает.

    Имени в профиле нет — обращаться нельзя вообще, обращение снимается целиком.

    `inscription` — надпись из [Уже собрано по заказу]. Ею модель зовёт клиента
    и в середине реплики, за текстом скрипта: «...Оплата при получении.\n\nОрех,
    а цвет для свитшота какой выберем?» — начало реплики там занято скриптом,
    и проверки первого слова не хватает.
    """
    text = _strip_leading_vocative(text, client_name)
    return _strip_inscription_vocative(text, client_name, inscription)


def _strip_leading_vocative(text: str, client_name: str | None) -> str:
    m = _LEADING_VOCATIVE_RE.match(text or "")
    if not m or m.group(1).lower() in _NOT_A_VOCATIVE or _looks_like_a_verb(m.group(1)):
        return text
    known = usable_name(client_name)
    if known and m.group(1).lower() == known.lower():
        return text
    rest = text[m.end():]
    if not rest:
        return text
    return rest[:1].upper() + rest[1:]


def _inscription_words(inscription: str | None) -> list[str]:
    """Слова надписи, каждое из которых модель может принять за имя клиента.

    Проверять надпись целиком мало: клиент заказал «Хананов Михаил», и реплика
    ушла с обращением «Михаил, а цвет для свитшота какой выберем?» — а зовут
    клиентку Анастасия (диалог 163, 14:09). Раньше проверка выходила на первом
    же пробеле в надписи.

    Короче трёх букв не берём: односложное «я» или «да» сняло бы половину
    нормальных фраз.
    """
    raw = (inscription or "").strip()
    if not raw:
        return []
    words = [w.strip(".,!?;:«»\"\'") for w in raw.split()]
    return [w for w in words if len(w) >= 3]


def _strip_inscription_vocative(
    text: str, client_name: str | None, inscription: str | None,
) -> str:
    if not text:
        return text
    known = usable_name(client_name)
    for word in _inscription_words(inscription):
        # Клиент заказал кофту со своим же именем — обращение настоящее.
        if known and word.lower() == known.lower():
            continue
        text = _inscription_vocative_re(word).sub(
            lambda m: m.group(1) + m.group(2).upper(), text,
        )
    return text


# Отработка возражений в скриптах почти вся открывается словом «Понимаю», и
# реплики выходят под копирку: «Понимаю Ваши сомнения. При оплате всей суммы...»,
# «Понимаю, не буду настаивать...», «Понимаю Ваши сомнения. Без предоплаты...» —
# три подряд (диалог 85, 08:57-08:59). Читается как автоответчик ровно там, где
# нужно живое участие. Промпт просит не повторяться, но текст-то скриптовый.
#
# Замена только первого слова и только там, где она грамматически безопасна:
# перед запятой стоит вводное слово, перед «Вас/Ваши» — глагол с тем же
# управлением. Всё остальное оставляем как есть: лучше повтор, чем ломаная фраза.
_OPENER_RE = re.compile(r"^\s*([А-ЯЁ][а-яё]+)")
_VOCATIVE_OBJECT_RE = re.compile(r"^\s+(?:вас|ваши|ваше|вашу|ваш|вашего)\b", re.IGNORECASE)

_OPENER_ALTERNATIVES: dict[str, dict[str, tuple[str, ...]]] = {
    "понимаю": {
        "aside": ("Согласна", "Хорошо", "Ясно"),
        "verb": ("Прекрасно понимаю", "Слышу", "Полностью понимаю"),
    },
    "отлично": {"aside": ("Супер", "Здорово", "Замечательно")},
    "хорошо": {"aside": ("Договорились", "Принято", "Отлично")},
    "супер": {"aside": ("Отлично", "Здорово")},
    "здорово": {"aside": ("Отлично", "Супер")},
    "замечательно": {"aside": ("Отлично", "Прекрасно")},
    "конечно": {"aside": ("Разумеется", "Безусловно")},
    "спасибо": {"aside": ("Благодарю",)},
}

# Сколько наших последних сообщений считаем «подряд идущими».
_OPENER_LOOKBACK = 2


def _opening_word(text: str) -> str | None:
    m = _OPENER_RE.match(text or "")
    return m.group(1).lower() if m else None


def vary_repeated_opening(text: str, previous_texts: list[str]) -> str:
    """Сменить первое слово реплики, если предыдущие открывались тем же.

    previous_texts — наши отправленные сообщения по возрастанию времени.
    """
    m = _OPENER_RE.match(text or "")
    if not m:
        return text
    word = m.group(1).lower()
    variants = _OPENER_ALTERNATIVES.get(word)
    if not variants:
        return text

    recent = [w for w in (_opening_word(t) for t in previous_texts[-_OPENER_LOOKBACK:]) if w]
    if word not in recent:
        return text

    tail = text[m.end():]
    if tail[:1] in (",", ".", "!", "…", ":", ""):
        shape = "aside"
    elif _VOCATIVE_OBJECT_RE.match(tail):
        shape = "verb"
    else:
        return text

    for alt in variants.get(shape, ()):
        if alt.split()[0].lower() not in recent:
            return text[: m.start(1)] + alt + tail
    return text
