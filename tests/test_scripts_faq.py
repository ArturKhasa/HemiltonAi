import pytest
from sqlalchemy import insert

from app.db.models import Script
from app.sales.scripts import ScriptService


@pytest.fixture
async def script_service(db):
    await db.execute(
        insert(Script).values([
            {"condition": "intro", "phrase_text": "Привет! {Чем|Как} могу помочь?", "is_active": True},
            {"condition": "price objection", "phrase_text": "Понимаю, давайте подберём вариант", "is_active": True},
            {"condition": "old", "phrase_text": "устаревший текст", "is_active": False},
        ])
    )
    await db.commit()
    return ScriptService(db)


async def test_get_active_scripts_excludes_inactive(script_service):
    scripts = await script_service.get_all_active()
    assert len(scripts) == 2
    conditions = [s.condition for s in scripts]
    assert "old" not in conditions


class TestProductGate:
    """Клиент покупал толстовку, попросил показать, как выглядит, и получил
    скрипт про костюм — он лежит на стадии None и виден всегда (диалог 111)."""

    def _scripts(self):
        from types import SimpleNamespace
        return [
            SimpleNamespace(id=406, marketing_tag=None, funnel_stage=None,
                            condition="Дополнительные фотографии изделий для клиентов",
                            phrase_text="Этот костюм мы отшиваем в 4-х цветах: черный, серый"),
            SimpleNamespace(id=380, marketing_tag=None, funnel_stage=None,
                            condition="Дополнительные фотографии изделий для клиентов",
                            phrase_text="Вот такие цвета есть для свитшотов"),
            SimpleNamespace(id=403, marketing_tag=None, funnel_stage=None,
                            condition="Доп. товар - лонгслив",
                            phrase_text="Стоимость лонгслива со скидкой"),
        ]

    def test_costume_script_hidden_from_a_sweatshirt_client(self):
        from app.ai.tools import format_scripts_list

        out = format_scripts_list(self._scripts(), None, client_product="свитшот")
        assert "script_id=406" not in out
        assert "script_id=380" in out

    def test_upsell_of_another_item_stays(self):
        """«Доп. товар - лонгслив» говорит о другом товаре нарочно."""
        from app.ai.tools import format_scripts_list

        out = format_scripts_list(self._scripts(), None, client_product="свитшот")
        assert "script_id=403" in out

    def test_without_a_known_product_nothing_is_hidden(self):
        from app.ai.tools import format_scripts_list

        out = format_scripts_list(self._scripts(), None)
        assert all(f"script_id={i}" in out for i in (406, 380, 403))

    def test_hoodie_and_sweatshirt_are_one_family(self):
        from app.ai.tools import client_product_family

        assert client_product_family("худи") == client_product_family("свитшот") == "кофта"
        assert client_product_family("костюм") == "костюм"
