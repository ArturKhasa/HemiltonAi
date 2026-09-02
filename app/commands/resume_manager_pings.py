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

Две оговорки именно для разового прогона по истории:

* диалоги в статусе «Нужен куратор» пропускаем. На живом пути правило Лены
  прямое — сняли паузу, пинги идут вне зависимости от статуса, — но там снятие
  паузы и есть осознанное действие человека. В истории отличить «менеджер вернул
  диалог ИИ» от «эскалацию кто-то снял мимоходом» нечем, а цена ошибки высокая:
  диалог 82014 — клиент просит вышивку, менеджер считает цену руками и шлёт
  голосовое, и общий пинг «Я Вам стоимость отправила, а вы мне что-то не
  отвечаете))» встал бы прямо поверх этого. Нужно и их — флаг `--include-curator`;
* в ВК не трогаем тех, кто нам не написал ни слова: такой диалог завела рассылка,
  и пинг в нём — сообщение незнакомому человеку. То же правило стоит в
  `discover()`. В MAX оно не действует: там боту пишут только после кнопки
  «Начать», её нажатие и есть согласие.
"""
import argparse
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select

from app.ai.triggers import CURATOR_STATUS_NAME
from app.db.models import (
    Client, Dialog, DialogPingState, DialogStatusConfig, Message, MessageRole, VkGroup,
)
from app.db.session import AsyncSessionLocal
from app.messaging import dialogs_on_inactive_channels
from app.ping.eligibility import is_non_broadcast_curator_message, is_pingable_outbound
from app.ping.worker import resume_after_handoff
from app.utils.time import msk_now

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Диалоги моложе суток разберёт обычный discovery — трогать их не нужно.
_MIN_AGE_HOURS = 24


async def _candidates(include_ai_last: bool, include_curator: bool) -> list[int]:
    async with AsyncSessionLocal() as db:
        skip_names = ["ЧС"] if include_curator else ["ЧС", CURATOR_STATUS_NAME]
        skip_ids = select(DialogStatusConfig.id).where(DialogStatusConfig.name.in_(skip_names))
        cutoff = msk_now() - timedelta(hours=_MIN_AGE_HOURS)
        rows = (await db.execute(
            select(Dialog.id, VkGroup.platform)
            .join(Client, Dialog.client_id == Client.id)
            .outerjoin(VkGroup, Client.vk_group_id == VkGroup.id)
            .where(
                Dialog.ai_paused == False,
                Dialog.vk_blocked == False,
                Dialog.is_test == False,
                Dialog.id.not_in(dialogs_on_inactive_channels()),
                Dialog.last_message_at.isnot(None),
                Dialog.last_message_at < cutoff,
                Dialog.current_status_id.not_in(skip_ids)
                | Dialog.current_status_id.is_(None),
            )
            .order_by(Dialog.id)
        )).all()

        keep: list[int] = []
        for dialog_id, platform in rows:
            last = await db.scalar(
                select(Message)
                .where(Message.dialog_id == dialog_id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            if last is None:
                continue
            if not is_non_broadcast_curator_message(last) and not (
                include_ai_last and last.role == MessageRole.ai and is_pingable_outbound(last)
            ):
                continue
            # В ВК диалог заводит либо сообщение клиента, либо рассылка. Пинговать
            # второе — писать незнакомому человеку (то же правило в discover()).
            if platform != "max":
                client_msgs = await db.scalar(
                    select(func.count()).where(
                        Message.dialog_id == dialog_id,
                        Message.role == MessageRole.client,
                    )
                )
                if not client_msgs:
                    continue
            keep.append(dialog_id)
        return keep


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-curator",
        action="store_true",
        help="взять и диалоги в статусе «Нужен куратор» (их ведёт человек)",
    )
    parser.add_argument(
        "--include-ai-last",
        action="store_true",
        help="взять и диалоги, где последним писал ИИ (не только менеджер)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    ids = await _candidates(args.include_ai_last, args.include_curator)
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
            # В сухом прогоне делаем ровно ту же работу и откатываем: иначе
            # «кандидат» ничего не говорит о том, уйдёт клиенту пинг или нет —
            # у диалога без отправленной цены воронки не будет вовсе.
            what = await resume_after_handoff(db, dialog)
            if args.dry_run:
                await db.rollback()
            else:
                await db.commit()
            print(f"  диалог {dialog_id}: {what}")
            done += 1

    print(f"{'посчитано' if args.dry_run else 'обработано'}: {done}")


if __name__ == "__main__":
    asyncio.run(main())
