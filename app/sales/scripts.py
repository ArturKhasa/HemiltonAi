from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Script


class ScriptService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_active(self, type_id: int | None = None, include_inactive: bool = False) -> list[Script]:
        q = select(Script)
        if not include_inactive:
            q = q.where(Script.is_active == True)
        if type_id is not None:
            q = q.where(Script.type_id == type_id)
        result = await self.db.execute(q.order_by(Script.id))
        return list(result.scalars().all())

    async def get_by_id(self, script_id: int) -> Script | None:
        return await self.db.get(Script, script_id)

    async def create(
        self, condition: str, phrase_text: str, type_id: int | None = None,
        marketing_tag: str | None = None, funnel_stage: str | None = None,
    ) -> Script:
        script = Script(
            condition=condition, phrase_text=phrase_text, type_id=type_id,
            marketing_tag=marketing_tag, funnel_stage=funnel_stage,
        )
        self.db.add(script)
        await self.db.flush()
        return script

    async def update(self, script_id: int, **fields) -> Script | None:
        script = await self.db.get(Script, script_id)
        if not script:
            return None
        for k, v in fields.items():
            setattr(script, k, v)
        await self.db.flush()
        return script

    async def delete(self, script_id: int) -> bool:
        script = await self.db.get(Script, script_id)
        if not script:
            return False
        await self.db.delete(script)
        return True
