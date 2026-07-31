"""Белый список меток рекламных ссылок.

«Надо сделать админку, где указываются реф метки, на которые ИИ будет отвечать»
— то есть трафик с неизвестной метки ведёт человек, а не бот.

Пока список ПУСТ, он не применяется: иначе выкатка этой возможности разом
оборвала бы все живые диалоги, включая тех, кто пришёл из поиска по группе, где
метки нет вовсе. Список начинает работать с момента, когда в него добавили
первую метку.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DialogType, RefTag

logger = logging.getLogger(__name__)


class RefTagService(object):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def is_configured(self, type_id: int | None = None) -> bool:
        """В списке есть хоть одна метка — значит белый список включён."""
        q = select(func.count()).select_from(RefTag)
        if type_id is not None:
            q = q.where(RefTag.type_id == type_id)
        return bool(await self.db.scalar(q))

    async def get(self, tag: str | None, type_id: int | None = None) -> RefTag | None:
        if not tag:
            return None
        q = select(RefTag).where(RefTag.tag == tag)
        if type_id is not None:
            q = q.where(RefTag.type_id == type_id)
        return await self.db.scalar(q.limit(1))

    async def _answer_untagged(self, type_id: int | None) -> bool:
        """Настройка направления: обслуживать ли приход без метки."""
        if type_id is None:
            return True
        dt = await self.db.get(DialogType, type_id)
        return True if dt is None else bool(dt.answer_untagged)

    async def ai_allowed(self, tag: str | None, type_id: int | None = None) -> bool:
        """Отвечает ли ИИ клиенту, пришедшему с этой меткой.

        Метки нет вовсе — это не обязательно чужой трафик: ВК присылает ref
        только в первом сообщении, а в группу приходят ещё и из поиска. Такой
        случай решает настройка направления, а не белый список.
        """
        if not await self.is_configured(type_id):
            return True  # список ещё не заполнен — работаем как раньше
        if not tag:
            allowed = await self._answer_untagged(type_id)
            if not allowed:
                logger.info("клиент без ref-метки — диалог ведёт человек")
            return allowed
        row = await self.get(tag, type_id)
        if row is None:
            logger.info("ref-метка %r не в белом списке — диалог ведёт человек", tag)
            return False
        if not row.is_active:
            logger.info("ref-метка %r выключена — диалог ведёт человек", tag)
            return False
        return True

    async def list_all(self, type_id: int | None = None) -> list[RefTag]:
        q = select(RefTag)
        if type_id is not None:
            q = q.where(RefTag.type_id == type_id)
        return list((await self.db.execute(q.order_by(RefTag.tag))).scalars().all())

    async def create(self, tag: str, type_id: int | None = None, **fields) -> RefTag:
        row = RefTag(tag=tag.strip(), type_id=type_id, **fields)
        self.db.add(row)
        await self.db.flush()
        return row

    async def update(self, ref_tag_id: int, **fields) -> RefTag | None:
        row = await self.db.get(RefTag, ref_tag_id)
        if not row:
            return None
        for k, v in fields.items():
            setattr(row, k, v)
        await self.db.flush()
        return row

    async def delete(self, ref_tag_id: int) -> bool:
        row = await self.db.get(RefTag, ref_tag_id)
        if not row:
            return False
        await self.db.delete(row)
        return True
