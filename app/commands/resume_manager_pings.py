"""python -m app.commands.resume_manager_pings — догнать диалоги, которые вернули ИИ.

Пинги ищет `discover()`, и смотрит он только сутки назад
(`PING_DISCOVERY_MAX_AGE_HOURS`). Диалог, который менеджер вёл неделю, а потом
вернул автоматике, в это окно не попадает никогда — воронки у него нет и не
будет. На 02.09 таких в проде 48 с живой репликой менеджера в конце и ещё 179 с
репликой ИИ.

Правка от 02.09 чинит это на будущее: воронка продолжается прямо в момент снятия
паузы (`app.ping.worker.resume_after_handoff`). Накопившееся эта команда
разбирает разово — заказчик 02.09: «да, можно в целом, если заново включили».

    python -m app.commands.resume_manager_pings --dry-run     # только посчитать
    python -m app.commands.resume_manager_pings               # менеджер писал последним
    python -m app.commands.resume_manager_pings --include-ai-last   # и те, где последним был ИИ

Берём только диалоги, где ИИ включён, клиент не в ЧС и не заблокировал
сообщения, а канал активен, — то есть ровно те, где автоматика и так имеет право
писать. Рассылка последним словом воронку не заводит: она приходит в диалог сама
по себе и продолжением разговора не является.
"""
import argparse
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from app.db.models import Dialog, DialogPingState, DialogStatusConfig, Message, MessageRole
from app.db.session import AsyncSessionLocal
from app.messaging import dialogs_on_inactive_channels
from app.ping.eligibility import is_non_broadcast_curator_message, is_pingable_outbound
from app.ping.worker import resume_after_handoff
from app.utils.time import msk_now

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Диалоги моложе суток разберёт обычный discovery — трогать их не нужно.
_MIN_AGE_HOURS = 24


async def _candidates(include_ai_last: bool) -> list[int]:
    async with AsyncSessionLocal() as db:
        blacklist_ids = select(DialogStatusConfig.id).where(DialogStatusConfig.name == "ЧС")
        cutoff = msk_now() - timedelta(hours=_MIN_AGE_HOURS)
        rows = (await db.execute(
            select(Dialog.id)
            .where(
                Dialog.ai_paused == False,
                Dialog.vk_blocked == False,
                Dialog.is_test == False,
                Dialog.id.not_in(dialogs_on_inactive_channels()),
                Dialog.last_message_at.isnot(None),
                Dialog.last_message_at < cutoff,
                Dialog.current_status_id.not_in(blacklist_ids)
                | Dialog.current_status_id.is_(None),
            )
            .order_by(Dialog.id)
        )).scalars().all()

        keep: list[int] = []
        for dialog_id in rows:
            last = await db.scalar(
                select(Message)
                .where(Message.dialog_id == dialog_id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            if last is None:
                continue
            if is_non_broadcast_curator_message(last):
                keep.append(dialog_id)
            elif include_ai_last and last.role == MessageRole.ai and is_pingable_outbound(last):
                keep.append(dialog_id)
        return keep


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-ai-last",
        action="store_true",
        help="взять и диалоги, где последним писал ИИ (не только менеджер)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    ids = await _candidates(args.include_ai_last)
    if args.limit:
        ids = ids[: args.limit]
    print(f"кандидатов: {len(ids)}")

    done = 0
    for dialog_id in ids:
        async with AsyncSessionLocal() as db:
            dialog = await db.get(Dialog, dialog_id)
            if dialog is None:
                continue
            state = await db.scalar(
                select(DialogPingState).where(DialogPingState.dialog_id == dialog_id)
            )
            if state is not None and not state.is_completed:
                continue  # воронка и так идёт
            if args.dry_run:
                print(f"  диалог {dialog_id}: воронка была бы продолжена")
                done += 1
                continue
            what = await resume_after_handoff(db, dialog)
            await db.commit()
            print(f"  диалог {dialog_id}: {what}")
            done += 1

    print(f"{'посчитано' if args.dry_run else 'обработано'}: {done}")


if __name__ == "__main__":
    asyncio.run(main())
