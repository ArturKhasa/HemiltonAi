"""Слово про вышивку выключает ИИ на любом пути — и молча.

Лена, 01.09: «ИИ строго должна выключаться после слова про вышивку». Сам триггер
работает с 10.08 — за три недели 53 эскалации, — но мимо него проходили два
пути, и оба видны в проде:

* приветствие уходит скриптом, без обращения к модели, и вместе с ним мимо всех
  гейтов эскалации проходил весь первый ход. Тринадцать диалогов за три недели
  начались словом про вышивку, и ни один менеджеру передан не был;
* клиент дробит мысль на две реплики, ход по первой уступает место второй
  (`superseded_by_newer_message`), и до проверки доходил только текст последней.

Прощальную реплику на этой теме заказчик 02.09 убрал совсем. Замер за три
недели: из 53 эскалаций по вышивке 52 реплики кончались вопросом («Какой рисунок
хотите вышить?», «Оставляем вышивку или считаем термопринт?»), пять предлагали
свой компромисс, девять называли рядом цифры — а отвечать на этот вопрос было уже
некому, диалог в тот же момент вставал на паузу. Теперь ИИ молчит, а менеджер
получает уведомление сразу.

Что дальше диалог возвращает менеджер — не наш случай: заказчик 02.09 уточнил,
«спросили про вышивку → ответили → сняли с паузы → ИИ дальше работает».
"""
import pytest

from app.ai.runner import _run_scripted_greeting
from app.ai.triggers import SILENT_TRIGGERS, curator_trigger_in_batch
from app.db.models import (
    Client, Dialog, DialogStatusConfig, DialogType, Message, MessageRole, Script,
)

GREETING_CONDITION = "Первое приветственное сообщение, отправляем всем новым клиентом"


class TestSplitMessages:
    def test_topic_in_the_earlier_reply_still_escalates(self):
        """«а вышивка есть?» + «или только принт?» — ход идёт по второй реплике."""
        assert curator_trigger_in_batch(["или только принт?", "а вышивка есть?"]) == "вышивка"

    def test_current_message_wins_when_both_have_a_topic(self):
        """В причине эскалации должна остаться тема, из-за которой ход и встал."""
        assert curator_trigger_in_batch(["нужно 10 штук", "а вышивка есть?"]) == "опт"

    def test_ordinary_batch_passes_through(self):
        assert curator_trigger_in_batch(["Смирнов", "на груди справа"]) is None

    def test_empty_batch(self):
        assert curator_trigger_in_batch([None, ""]) is None

    def test_wired_into_the_run(self):
        import inspect

        from app.ai import runner

        assert "curator_trigger_in_batch(unanswered" in inspect.getsource(runner.run_ai)


class TestGreetingPath:
    @pytest.fixture
    async def setup(self, db):
        db.add(DialogType(id=1, name="default", display_name="Основное"))
        db.add(DialogStatusConfig(
            name="Нужен куратор", pattern="", is_active=True, sort_order=100,
        ))
        db.add(Script(
            id=358, condition=GREETING_CONDITION, type_id=1, funnel_stage="greeting",
            phrase_text="[Имя], здравствуйте! Меня зовут София",
        ))
        client = Client(vk_user_id=1, name="Иван")
        db.add(client)
        await db.flush()
        dialog = Dialog(client_id=client.id, type_id=1)
        db.add(dialog)
        await db.commit()
        return dialog, client

    @pytest.fixture
    def notified(self, monkeypatch):
        calls = []

        async def _notify(dialog_id, reason, **kwargs):
            calls.append(reason)

        monkeypatch.setattr("app.notify.notify_curator", _notify)
        return calls

    async def test_first_message_about_embroidery_hands_the_dialog_over(
        self, db, setup, notified,
    ):
        dialog, client = setup
        script = await db.get(Script, 358)

        output, _run, _parts = await _run_scripted_greeting(
            db, dialog, client, script, "test", client_text="а вышивка у вас есть?",
        )

        # Приветствие придержано: шаблон с вопросом «какое имя напишем?» вместо
        # ответа на вопрос клиента — ровно то, из-за чего реплику и убрали.
        assert output.need_curator is True
        assert dialog.ai_paused is True
        status = await db.get(DialogStatusConfig, dialog.current_status_id)
        assert status.name == "Нужен куратор"
        assert output.curator_reason == "Тема менеджера: вышивка"
        assert notified == ["Тема менеджера: вышивка"]

    async def test_other_manager_topics_still_get_the_greeting(self, db, setup, notified):
        """Опт, срочность, размер — там прощальная реплика осталась: она про
        тему клиента ничего не утверждает, а тишина на первое сообщение хуже."""
        dialog, client = setup
        script = await db.get(Script, 358)

        output, _run, parts = await _run_scripted_greeting(
            db, dialog, client, script, "test", client_text="нужно 10 штук на команду",
        )

        assert output.need_curator is False
        assert parts and "здравствуйте" in parts[0].text.lower()
        assert dialog.ai_paused is True
        assert notified == ["Тема менеджера: опт"]

    async def test_ordinary_first_message_keeps_the_ai_working(self, db, setup, notified):
        dialog, client = setup
        script = await db.get(Script, 358)

        output, _run, parts = await _run_scripted_greeting(
            db, dialog, client, script, "test", client_text="+",
        )

        assert dialog.ai_paused is False
        assert dialog.current_status_id is None
        assert output.curator_reason is None
        assert output.need_curator is False
        assert notified == []

    async def test_greeting_without_an_incoming_message_is_unaffected(self, db, setup, notified):
        """В MAX приветствие уходит по кнопке «Начать», входящего текста нет."""
        dialog, client = setup
        script = await db.get(Script, 358)

        await _run_scripted_greeting(db, dialog, client, script, "test")

        assert dialog.ai_paused is False
        assert notified == []


class TestSilentTopics:
    def test_only_embroidery_is_silent_for_now(self):
        """Остальные темы менеджера решения заказчика не касались."""
        assert "вышивка" in SILENT_TRIGGERS
        for topic in ("опт", "возврат предоплаты", "срочный заказ", "нестандартный размер"):
            assert topic not in SILENT_TRIGGERS

    def test_reply_is_held_by_need_curator(self):
        """Придержать ответ умеет только один механизм — вебхук смотрит на
        need_curator (webhook.py, «reply held for review»)."""
        import inspect

        from app.ai import runner
        from app.vk import webhook

        assert '"need_curator": hold_reply' in inspect.getsource(runner.run_ai)
        assert "hold_reply = trigger in SILENT_TRIGGERS" in inspect.getsource(runner.run_ai)
        assert "if output.need_curator:" in inspect.getsource(webhook._reply_with_ai)
