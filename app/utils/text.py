"""Text post-processing helpers for outgoing messages."""
import re

# Плейсхолдер имени в текстах скриптов, унаследованных из CRM.
_NAME_PLACEHOLDER_RE = re.compile(r"\[Имя\]", re.IGNORECASE)
_CYRILLIC_NAME_RE = re.compile(r"^[А-Яа-яЁё][А-Яа-яЁё\-]*$")


def render_name_placeholder(text: str, client_name: str | None) -> str:
    """Подставить имя клиента в «[Имя]» скриптового текста.

    Обращаемся по имени только если оно кириллицей — латиница, транслит, ники и
    наборы букв дают «Max, какое имя напишем...», что сразу читается как бот (то
    же правило в системном промпте). Имени нет — плейсхолдер вырезается вместе с
    идущей за ним запятой, а фраза начинается с большой буквы.
    """
    name = (client_name or "").strip()
    if name and _CYRILLIC_NAME_RE.match(name):
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
