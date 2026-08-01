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

from app.db.models import DialogType, RefTag, Script

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

    async def greeting_text(self, row: RefTag) -> str | None:
        """Текст приветствия метки, либо None — значит общее приветствие."""
        if not row.greeting_script_id:
            return None
        script = await self.db.get(Script, row.greeting_script_id)
        return script.phrase_text if script else None

    async def greeting_shared_with(self, row: RefTag) -> int:
        """Сколько других меток пишут тем же приветствием."""
        if not row.greeting_script_id:
            return 0
        return await self._sharing_tags(row.greeting_script_id, row.id)

    async def _sharing_tags(self, script_id: int, except_id: int) -> int:
        """Сколько ДРУГИХ меток пишут тем же приветствием."""
        return await self.db.scalar(
            select(func.count()).select_from(RefTag).where(
                RefTag.greeting_script_id == script_id, RefTag.id != except_id,
            )
        ) or 0

    async def set_greeting_text(self, row: RefTag, text: str | None) -> RefTag:
        """Задать метке её первое сообщение.

        Пустой текст — метка возвращается на общее приветствие.

        Скрипт правим на месте, только если он принадлежит этой метке одной.
        Приветствия из выгрузки ОП разделены между метками, и правка «под одну»
        молча меняла бы текст всем остальным — вместо этого метке заводится
        собственная копия.
        """
        text = (text or "").strip()
        if not text:
            row.greeting_script_id = None
            await self.db.flush()
            return row

        if row.greeting_script_id and not await self._sharing_tags(row.greeting_script_id, row.id):
            script = await self.db.get(Script, row.greeting_script_id)
            if script is not None:
                script.phrase_text = text
                await self.db.flush()
                return row

        script = Script(
            # Маркер условия обязателен: по нему приветствие находит
            # app.ai.greeting.pick_greeting_script, если метка отвяжется.
            condition=f"Первое приветственное сообщение, реф-метка {row.tag}",
            phrase_text=text,
            type_id=row.type_id,
            funnel_stage="greeting",
            is_active=True,
        )
        self.db.add(script)
        await self.db.flush()
        # Вопрос про имя/фамилию уходит связкой следом за любым приветствием.
        follow_up = await self.db.scalar(
            select(Script.follow_up_script_id).where(
                Script.is_active == True,
                Script.follow_up_script_id.isnot(None),
                func.lower(Script.condition).like("%первое приветственное%"),
            ).limit(1)
        )
        if follow_up:
            script.follow_up_script_id = follow_up
        row.greeting_script_id = script.id
        await self.db.flush()
        return row

    async def delete(self, ref_tag_id: int) -> bool:
        row = await self.db.get(RefTag, ref_tag_id)
        if not row:
            return False
        await self.db.delete(row)
        return True
