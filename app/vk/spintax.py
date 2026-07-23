"""Spintax-резолвер: {вариант1|вариант2} → случайный выбор.

Применяется к текстам скриптов и пинг-фраз, чтобы ответы не выглядели шаблонными.
"""
import random
import re


def resolve_spintax(text: str) -> str:
    """Resolve {option1|option2|option3} → random pick. Nested not supported."""
    def pick(match: re.Match) -> str:
        options = match.group(1).split("|")
        return random.choice(options)
    return re.sub(r"\{([^{}]+)\}", pick, text)
