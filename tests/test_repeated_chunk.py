"""Абзац, который клиент уже читал, не уходит вторым сообщением.

«Ткани таааак подорожали, это просто ужас!» лежит и в скрипте 477, и в 478 —
клиент получил его дважды за девять минут (прогоны 1353 и 1381). Реплики целиком
при этом разные, и проверка дубля по всему сообщению их не ловит.
"""
import pytest

from app.ai.runner import _find_repeated_chunk

FABRIC = (
    "Ткани таааак подорожали, это просто ужас! Пока старая партия, цену держим, "
    "но скорее всего придется поднять после следующей закупки"
)


class TestFindRepeatedChunk:
    def test_shared_paragraph_is_caught(self):
        sent = [f"Айдар, к сожалению, потом будет ощутимо дороже\n\n{FABRIC}\n\nСмотрите сами)"]
        reply = f"Айдар, понимаю Вашу ситуацию\n\n{FABRIC}\n\nОформляем?"
        assert _find_repeated_chunk(reply, sent) is not None

    def test_fresh_reply_passes(self):
        sent = [f"Айдар, к сожалению, потом будет дороже\n\n{FABRIC}"]
        reply = "Поняла Вас. Скажите, какой цвет ближе - чёрный или бежевый?"
        assert _find_repeated_chunk(reply, sent) is None

    def test_short_lines_may_repeat(self):
        """«Всё верно?» и «Что скажете?» повторяются законно."""
        sent = ["Зафиксировала размер!\n\nВсё верно?"]
        reply = "Хорошо, тогда цвет чёрный.\n\nВсё верно?"
        assert _find_repeated_chunk(reply, sent) is None

    def test_reworded_paragraph_passes(self):
        """Пересказ своими словами — то, чего мы и добиваемся повтором прогона."""
        sent = [f"Смотрите\n\n{FABRIC}"]
        reply = (
            "Смотрите\n\nЦены на ткани заметно выросли, и после следующей закупки "
            "нам, скорее всего, придётся поднять стоимость."
        )
        assert _find_repeated_chunk(reply, sent) is None

    @pytest.mark.parametrize("history", [[], ["Привет!"], ["", None]])
    def test_empty_history_is_safe(self, history):
        assert _find_repeated_chunk(f"Текст\n\n{FABRIC}", history) is None

    def test_punctuation_and_case_do_not_hide_a_repeat(self):
        sent = [f"Вот\n\n{FABRIC}."]
        reply = f"Ещё раз\n\n{FABRIC.upper()}!!!"
        assert _find_repeated_chunk(reply, sent) is not None
