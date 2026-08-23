"""Чего мы не шьём и не печатаем — решает менеджер, а не ИИ.

Женя, 03.08: «например, мы не можем наносить принт на манжету… по нестандартным
размерам — на вес больше 110 кг лучше звать менеджера». Правил на этот счёт не
было нигде: ИИ спокойно соглашалась на манжету и подбирала размер сама.
"""
import pytest

from app.ai.triggers import curator_trigger, mentions_impossible_placement, oversize


class TestImpossiblePlacement:
    @pytest.mark.parametrize("text", [
        "можно принт на манжете?",
        "хочу надпись на манжетах",
        "давайте вышьем на воротнике",
        "а на резинке можно?",
    ])
    def test_escalates(self, text):
        assert mentions_impossible_placement(text) is True
        assert curator_trigger(text) is not None

    @pytest.mark.parametrize("text", [
        "на груди слева",
        "на спине с гербом",
        "на рукаве справа флаг",
        "на капюшоне можно?",
    ])
    def test_normal_placements_pass(self, text):
        assert mentions_impossible_placement(text) is False


class TestOversize:
    @pytest.mark.parametrize("text", [
        "рост 180 вес 125",
        "125 кг",
        "вес 112",
        "я вешу 130",
        "мой вес 115",
        "35 кг",
    ])
    def test_out_of_grid(self, text):
        assert oversize(text) is True
        assert curator_trigger(text) == "нестандартный размер"

    @pytest.mark.parametrize("text", [
        "180 70",
        "рост 165 вес 55",
        "170 60",
        "рост 190 вес 95",
    ])
    def test_inside_the_grid(self, text):
        assert oversize(text) is False

    @pytest.mark.parametrize("text", [
        "300 рублей",
        "250 за доставку",
        "а можно за 300 ?",
        "5990",
        "давайте 500 предоплату",
    ])
    def test_money_is_not_weight(self, text):
        """Голое число без роста рядом — это чаще цена, чем килограммы."""
        assert oversize(text) is False

    @pytest.mark.parametrize("text", ["180/90", "180 90", "180-90", "170/60", "160/45"])
    def test_pair_of_measurements_inside_the_grid(self, text):
        """Мерки клиент шлёт как придётся: «180/90», «180 90», «180-90»."""
        assert oversize(text) is False

    @pytest.mark.parametrize("text", ["180/125", "195/120", "170/35", "125/190"])
    def test_pair_of_measurements_outside_the_grid(self, text):
        assert oversize(text) is True

    def test_bare_weight_counts_after_our_size_question(self):
        """На «назовите рост и вес» клиент отвечает и одним числом."""
        assert oversize("120", size_expected=True) is True
        assert oversize("90", size_expected=True) is False
        # Вне этого контекста то же число — скорее цена.
        assert oversize("120") is False

    def test_prices_stay_safe_even_after_the_size_question(self):
        for text in ("5990", "500", "давайте 500 предоплату"):
            assert oversize(text, size_expected=True) is False
