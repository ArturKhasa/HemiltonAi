"""Tests for objection detection logic in AI runner."""
from app.ai.runner import _is_objection


def test_price_objection_ru():
    assert _is_objection("Это слишком дорого для меня") is True


def test_price_objection_en():
    assert _is_objection("It's too expensive") is True


def test_need_to_think_objection():
    assert _is_objection("Мне нужно подумать") is True


def test_competitor_objection():
    assert _is_objection("У конкурентов дешевле") is True


def test_quality_doubt_objection():
    assert _is_objection("Я сомневаюсь в качестве") is True


def test_delivery_objection():
    assert _is_objection("Это долго ждать, у меня скоро событие") is True


def test_no_objection_simple_question():
    assert _is_objection("Какие размеры доступны?") is False


def test_no_objection_positive():
    assert _is_objection("Отлично, давайте оформим заказ!") is False


def test_no_objection_greeting():
    assert _is_objection("Здравствуйте, я хочу узнать про фотоальбом") is False


def test_no_objection_payment_question():
    assert _is_objection("Как можно оплатить?") is False
