"""Лестница статусов: порядок ступеней и то, что модели ставить нельзя.

Раньше здесь проверялись три гейта в runner, каждый из которых чинил свой случай
выдуманного моделью статуса: откат из «горячего» назад (диалог 142), «Ждем
предоплату» на первом сообщении (клиент 8465497), «Ждем предоплату» без единой
ссылки на оплату (клиент 8522740). Все три лечили один корень — модель угадывала
статус вместо того, чтобы его знать.

Корень убран: ступени считает код по фактам (app.sales.status_flow), модели
остались только боковые статусы. Проверяем то, на что теперь опирается воронка.
"""
import pytest

from app.sales.status_names import (
    AWAITING_DATA,
    AWAITING_PREPAY,
    BLACKLIST,
    CALCULATED,
    CLARIFYING,
    HOT,
    INTERESTED,
    LADDER,
    MODEL_STATUSES,
    NEEDS_CURATOR,
    ORDER_CREATED,
    SIDE_STATUSES,
    is_hot,
    is_ladder,
    rank,
)


class TestLadderOrder:
    def test_rungs_go_in_the_order_the_client_walks_them(self):
        assert LADDER == (
            INTERESTED, CALCULATED, CLARIFYING, HOT,
            AWAITING_DATA, AWAITING_PREPAY, ORDER_CREATED,
        )

    @pytest.mark.parametrize("lower,higher", list(zip(LADDER, LADDER[1:])))
    def test_each_rung_is_higher_than_the_previous(self, lower, higher):
        assert rank(lower) < rank(higher)

    def test_old_duplicate_reads_as_the_same_rung(self):
        """«Горячий клиент» (id 9) — пустой дубль «Горячего» из прода. Считать
        его нулевой ступенью нельзя: диалог на нём поехал бы назад."""
        assert rank("Горячий клиент") == rank(HOT)
        assert is_hot("Горячий клиент") and is_hot(HOT)

    @pytest.mark.parametrize("name", [None, "", "Придуманный статус"])
    def test_unknown_status_is_below_every_rung(self, name):
        assert rank(name) < rank(INTERESTED)
        assert not is_ladder(name)


class TestSideStatuses:
    @pytest.mark.parametrize("name", [NEEDS_CURATOR, "Спам", BLACKLIST])
    def test_side_statuses_are_not_rungs(self, name):
        """Из переписки они не выводятся — лестница их не трогает."""
        assert name in SIDE_STATUSES
        assert not is_ladder(name)

    def test_model_may_only_propose_side_statuses(self):
        assert MODEL_STATUSES == SIDE_STATUSES
        for rung in LADDER:
            assert rung not in MODEL_STATUSES
