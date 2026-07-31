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
    # Проверяем ПОСЛЕ словаря: «Дима»/«Ксюша» тоже кончаются на фамильные буквы,
    # но они в словаре и до этой ветки не доходят.
    if lowered.endswith(_SURNAME_SUFFIXES):
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
