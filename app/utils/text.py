"""Text post-processing helpers for outgoing messages."""
import re


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
