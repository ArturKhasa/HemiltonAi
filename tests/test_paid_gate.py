"""Шаги «после оплаты» и ручные скрипты недоступны ИИ.

Два замечания ОП от 10 августа, 14:15:
- «Макет на правки всегда отправляем дизам, они вручную кидают его с таким
  скриптом» — а ИИ прислал «Ваш макет готов! Проверьте, пожалуйста, все ли
  верно?» сам, макета при этом не существовало (диалог 142, 14:13).
- «Оплаты от клиента не было» — а ИИ отправил «Благодарю Вас за заказ и за
  доверие! Теперь пришлите адрес пункта выдачи СДЭК» и поставил статус «Заказ
  оформлен» (там же, 14:13).
"""
from dataclasses import dataclass, field

from app.ai.tools import format_scripts_list


@dataclass
class FakeScript:
    id: int
    condition: str
    phrase_text: str = "текст"
    marketing_tag: str | None = None
    funnel_stage: str | None = None
    manual_only: bool = False


def _scripts() -> list[FakeScript]:
    return [
        FakeScript(1, "Возражение: Дорого"),
        FakeScript(2, "Возражение: Макет готов", manual_only=True),
        FakeScript(3, "Уточняем СДЭК после оплаты", funnel_stage="post_payment"),
        FakeScript(4, "Допродажа второго изделия", funnel_stage="paid"),
    ]


class TestManualOnly:
    def test_designer_script_is_hidden_from_the_model(self):
        out = format_scripts_list(_scripts(), client_tags=None)
        assert "Макет готов" not in out
        assert "Возражение: Дорого" in out


class TestPaidGate:
    def test_post_payment_steps_hidden_until_payment_is_confirmed(self):
        out = format_scripts_list(_scripts(), client_tags=None, payment_confirmed=False)
        assert "Уточняем СДЭК" not in out
        assert "Допродажа второго изделия" not in out
        assert "Возражение: Дорого" in out

    def test_post_payment_steps_appear_once_payment_is_confirmed(self):
        out = format_scripts_list(_scripts(), client_tags=None, payment_confirmed=True)
        assert "Уточняем СДЭК" in out
        assert "Допродажа второго изделия" in out
        # Ручной скрипт не появляется и после оплаты — его шлёт только человек.
        assert "Макет готов" not in out
