"""Текущая дата доезжает до модели.

В контексте её не было вовсе: на «хочу к 9 августа» модель не знала, три это дня
или три месяца, и отвечала «подстроимся под Вас» вместо честного «не успеем»
(замечание ОП от 6 августа). Проверял по сохранённому full_context прогона 1389 —
ни «2026», ни «августа», ни «сегодня» там не встречалось ни разу.
"""
from datetime import datetime

import pytest

from app.utils.time import human_msk_now


class TestHumanMskNow:
    def test_reads_like_a_person_names_the_date(self):
        got = human_msk_now(datetime(2026, 8, 6, 21, 40))
        assert got == "четверг, 6 августа 2026, 21:40 (МСК)"

    @pytest.mark.parametrize("month,name", [
        (1, "января"), (3, "марта"), (5, "мая"), (9, "сентября"), (12, "декабря"),
    ])
    def test_month_is_in_the_form_the_client_uses(self, month, name):
        """Клиент пишет «к 9 августа» — падеж должен совпадать."""
        assert f" {name} " in human_msk_now(datetime(2026, month, 9, 10, 0))

    @pytest.mark.parametrize("day,weekday", [
        (3, "понедельник"), (8, "суббота"), (9, "воскресенье"),
    ])
    def test_weekday_matches_the_calendar(self, day, weekday):
        assert human_msk_now(datetime(2026, 8, day, 12, 0)).startswith(weekday)

    def test_defaults_to_now(self):
        assert "(МСК)" in human_msk_now()


class TestDateInPrompt:
    def test_sales_context_block_carries_the_date_and_the_lead_time(self):
        from app.ai import runner  # noqa: F401  — модуль собирает блок в run_ai

        import inspect
        src = inspect.getsource(runner.run_ai)
        assert "[Сегодня]" in src
        assert "human_msk_now()" in src
        # Дата без сроков производства бесполезна: модель всё равно не знает,
        # успевает ли заказ к названному числу.
        assert "10-14 дней" in src

    def test_ping_context_block_carries_it_too(self):
        import inspect

        from app.ping import agent

        src = inspect.getsource(agent.run_ping_agent)
        assert "[Сегодня]" in src
        assert "human_msk_now()" in src
