"""Клиент не ответил на вопрос про имя — через 15 минут отправляем цену.

Правило Лены от 17.08: «если клиент ничего не отвечает на вопрос про
имя/фамилию, то ИИ отправляем стандартную цену 5990 ₽», время ожидания —
15 минут.

До этого такой диалог замолкал навсегда: пинги ему не полагались вовсе. Воронка
пингов в базе одна, `knows_price`, и до отправки цены она заблокирована — иначе
клиент, цены не видевший, получил бы «Я Вам стоимость отправила, а вы мне
что-то не отвечаете))» (см. app.ping.agent). Диалог 346 от 17.08: клиент нажал
«Начать» в 11:41, получил приветствие и вопрос про надпись, замолчал — и за
пять часов не получил ни одного сообщения.

Теперь молчание после приветствия закрывается тем же скриптом стоимости, что и
в обычном ходе воронки, со всеми его картинками и связкой. Заодно после этого
диалог перестаёт быть «без цены» и попадает под обычные пинги.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Client, Dialog, DialogStatusConfig, Message, MessageRole, Script
from app.db.session import AsyncSessionLocal
from app.logging_context import current_dialog_type
from app.sales.order_slots import ASKS_INSCRIPTION_RE
from app.utils.time import msk_now
from app.vk.outgoing import mark_delivered, mark_failed
from app.vk.sender import VkMessagesForbiddenError, send_to_dialog

logger = logging.getLogger(__name__)

# Сколько ждём ответа на вопрос про надпись. Названо Леной: 15 минут.
SILENCE_SECONDS = 15 * 60
# Дальше суток догонять смысла нет — клиент уже забыл, о чём речь.
_MAX_AGE_HOURS = 24
_BATCH = 20


async def find_price_script(db: AsyncSession, type_id: int | None) -> Script | None:
    """Скрипт стоимости — тот, на который ведёт связка со стадии приветствия.

    Искать по id нельзя: в админке скрипты пересоздают. «2.2 Стоимость» — это
    звено, на которое ссылается «2. Похвала», и оно стоит на стадии `pricing`.
    """
    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    scripts = list((await db.execute(q.order_by(Script.id))).scalars().all())
    by_id = {s.id: s for s in scripts}

    for script in scripts:
        if script.funnel_stage != "greeting" or not script.follow_up_script_id:
            continue
        target = by_id.get(script.follow_up_script_id)
        if target is not None and target.funnel_stage == "pricing":
            return target
    return None


async def _greeting_unanswered(db: AsyncSession, dialog: Dialog, now) -> bool:
    """Последнее слово за нами, и это вопрос про надпись."""
    last = await db.scalar(
        select(Message)
        .where(Message.dialog_id == dialog.id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if last is None or last.role != MessageRole.ai:
        return False
    if not ASKS_INSCRIPTION_RE.search(last.text or ""):
        return False
    return last.created_at <= now - timedelta(seconds=SILENCE_SECONDS)


async def _send_price(db: AsyncSession, dialog: Dialog, script: Script, now) -> bool:
    """Отправить связку со стоимостью так же, как её отправляет обычный ход."""
    from app.ai.runner import build_script_parts

    client = await db.get(Client, dialog.client_id)
    parts = await build_script_parts(db, dialog, script, client)
    if not parts:
        return False

    for i, part in enumerate(parts):
        try:
            result = await send_to_dialog(db, dialog, part.text)
        except VkMessagesForbiddenError:
            for rest in parts[i:]:
                mark_failed(rest.message)
            return False
        except Exception as exc:
            logger.error("цена молчуну: отправка не удалась | dialog=%s: %s", dialog.id, exc)
            for rest in parts[i:]:
                mark_failed(rest.message)
            return False
        mark_delivered(part.message, result)

    dialog.funnel_stage = script.funnel_stage or dialog.funnel_stage
    dialog.last_message_at = now
    logger.info(
        "цена отправлена молчуну | dialog=%s script=%s parts=%d",
        dialog.id, script.id, len(parts),
    )
    return True


async def send_price_to_silent() -> None:
    """Один проход: догнать ценой всех, кто молчит после вопроса про надпись."""
    if not settings.PING_ENABLED:
        return

    async with AsyncSessionLocal() as db:
        now = msk_now()
        if not (8 <= now.hour < 22):
            return

        blacklist = select(DialogStatusConfig.id).where(DialogStatusConfig.name == "ЧС")
        dialogs = (await db.execute(
            select(Dialog).where(
                Dialog.funnel_stage == "greeting",
                Dialog.ai_paused == False,
                Dialog.vk_blocked == False,
                Dialog.last_message_at.isnot(None),
                Dialog.last_message_at <= now - timedelta(seconds=SILENCE_SECONDS),
                Dialog.last_message_at >= now - timedelta(hours=_MAX_AGE_HOURS),
                Dialog.current_status_id.not_in(blacklist) | Dialog.current_status_id.is_(None),
            )
            .order_by(Dialog.last_message_at.desc())
            .limit(_BATCH)
        )).scalars().all()

        for dialog in dialogs:
            token = current_dialog_type.set(current_dialog_type.get())
            try:
                if not await _greeting_unanswered(db, dialog, now):
                    continue
                script = await find_price_script(db, dialog.type_id)
                if script is None:
                    logger.warning(
                        "цена молчуну: скрипт стоимости не найден | dialog=%s", dialog.id,
                    )
                    continue
                if await _send_price(db, dialog, script, now):
                    await db.commit()
                else:
                    await db.rollback()
            except Exception as exc:
                await db.rollback()
                logger.error("цена молчуну: ошибка | dialog=%s: %s", dialog.id, exc, exc_info=True)
            finally:
                current_dialog_type.reset(token)
