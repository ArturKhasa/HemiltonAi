"""Пинги на тестовых диалогах.

discover() исключал их фильтром is_test == False, а в базе панели других диалогов
и нет — лестницу из 17 шагов было негде посмотреть. Отправку в ВК для них
пропускаем: клиента за тестовым диалогом нет, send_to_dialog падает с
«no VK client binding».
"""
import pytest

from app.db.models import Dialog
from app.ping.worker import _deliverable


class TestDeliverable:
    def test_real_dialog_goes_to_vk(self):
        assert _deliverable(Dialog(client_id=1, type_id=1, is_test=False))

    def test_test_dialog_stays_in_the_panel(self):
        assert not _deliverable(Dialog(client_id=1, type_id=1, is_test=True))

    def test_missing_dialog_is_not_deliverable(self):
        assert not _deliverable(None)


class TestDiscoveryQuery:
    async def test_test_dialogs_are_no_longer_excluded(self, db):
        """Раньше запрос discovery отсекал их прямо в WHERE."""
        import inspect

        from app.ping import worker

        source = inspect.getsource(worker.discover)
        assert "Dialog.is_test == False" not in source
        # Остальные гейты на месте: оператор, блокировка ВК, ЧС.
        assert "Dialog.ai_paused == False" in source
        assert "Dialog.vk_blocked == False" in source
