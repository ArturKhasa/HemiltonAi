"""python -m app.commands.resync_statuses — пересчитать статусы по фактам.

До 27.08 статус ставила только модель, и только на том пути, где она вообще
запускалась. В базе из-за этого 834 диалога с тремя и более сообщениями клиента
стоят в «Поинтересовался», хотя расчёт им отправлен, а 39 диалогов стоят в
«Горячем» на стадии `pricing` — по старому смыслу статуса, который теперь
означает «отправлены способы оплаты».

Команда прогоняет по существующим диалогам ту же лестницу, что работает на
живом трафике (`app.sales.status_flow`), — и вперёд, и назад: заказчик 27.08
решил пересчитывать, а не оставлять старые значения.

ВАЖНО: перед первым прогоном по накопленной истории надо один раз выполнить
`python -m app.commands.mark_broadcasts` — иначе массовые рассылки с ценой в
тексте будут прочитаны как отправленный расчёт, и в «Есть расчет» уедут 78 тысяч
диалогов, где расчёта не было.

    python -m app.commands.resync_statuses --dry-run          # только посчитать
    python -m app.commands.resync_statuses --days 30          # свежие диалоги
    python -m app.commands.resync_statuses                    # вся база

Боковые статусы («Нужен куратор», «Спам», «ЧС») не трогаются никогда: они не
выводятся из переписки, и снять их может только человек.
"""
import argparse
import asyncio
import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from app.db.models import Dialog, DialogStatusConfig, Message
from app.db.session import AsyncSessionLocal
from app.sales.status_flow import earned_status
from app.sales.status_names import SIDE_STATUSES, is_ladder
from app.utils.time import msk_now

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_BATCH = 500


async def resync(days: int | None, dry_run: bool, backwards: bool) -> Counter:
    moves: Counter = Counter()
    async with AsyncSessionLocal() as db:
        by_name = {
            s.name: s for s in (await db.execute(select(DialogStatusConfig))).scalars().all()
        }
        by_id = {s.id: s for s in by_name.values()}

        q = select(Dialog.id).order_by(Dialog.id)
        if days is not None:
            cutoff = msk_now() - timedelta(days=days)
            q = q.where(func.coalesce(Dialog.last_message_at, Dialog.created_at) >= cutoff)
        # Диалог без единого сообщения считать нечего: он останется стартовым.
        q = q.where(select(Message.id).where(Message.dialog_id == Dialog.id).exists())
        dialog_ids = list((await db.execute(q)).scalars().all())

    print(f"диалогов к пересчёту: {len(dialog_ids)}")

    for start in range(0, len(dialog_ids), _BATCH):
        chunk = dialog_ids[start:start + _BATCH]
        async with AsyncSessionLocal() as db:
            dialogs = list((await db.execute(
                select(Dialog).where(Dialog.id.in_(chunk))
            )).scalars().all())
            for dialog in dialogs:
                current = by_id.get(dialog.current_status_id)
                current_name = current.name if current else None
                if current_name in SIDE_STATUSES:
                    moves["пропущен: боковой статус"] += 1
                    continue
                if current_name is not None and not is_ladder(current_name):
                    moves["пропущен: статус не из лестницы"] += 1
                    continue

                target = await earned_status(db, dialog)
                if target == current_name:
                    moves["без изменений"] += 1
                    continue
                row = by_name.get(target)
                if row is None or not row.is_active:
                    moves[f"статус не заведён: {target}"] += 1
                    continue
                if not backwards and current_name is not None:
                    from app.sales.status_names import rank

                    if rank(target) < rank(current_name):
                        moves[f"пропущен откат: {current_name} -> {target}"] += 1
                        continue

                moves[f"{current_name} -> {target}"] += 1
                if not dry_run:
                    dialog.current_status_id = row.id
            if not dry_run:
                await db.commit()
        print(f"  обработано {min(start + _BATCH, len(dialog_ids))}/{len(dialog_ids)}")

    return moves


def main() -> None:
    parser = argparse.ArgumentParser(description="Пересчёт статусов диалогов по фактам переписки")
    parser.add_argument("--days", type=int, default=None,
                        help="только диалоги с активностью за последние N дней (по умолчанию — все)")
    parser.add_argument("--dry-run", action="store_true", help="посчитать, но ничего не менять")
    parser.add_argument("--forward-only", action="store_true",
                        help="не откатывать статус назад (по умолчанию откат разрешён: "
                             "смысл «Горячего» изменился, и старые значения надо поправить)")
    args = parser.parse_args()

    moves = asyncio.run(resync(args.days, args.dry_run, backwards=not args.forward_only))

    print("\nИтог:" + (" (dry-run, ничего не записано)" if args.dry_run else ""))
    for label, count in moves.most_common():
        print(f"  {count:>7}  {label}")


if __name__ == "__main__":
    main()
