"""python -m app.commands.resync_statuses — пересчитать статусы по фактам.

До 27.08 статус ставила только модель, и только на том пути, где она вообще
запускалась. В базе из-за этого 834 диалога с тремя и более сообщениями клиента
стояли в «Поинтересовался», хотя расчёт им отправлен, а 39 диалогов стояли в
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

Прогон идёт пачками по 500 диалогов, каждая в своей сессии и со своим повтором:
первый прогон по проду оборвался на середине, когда pgbouncer закрыл соединение
посреди операции. Пачки независимы, повторить любую безопасно — лестница считает
статус заново и пишет только то, что отличается от текущего.
"""
import argparse
import asyncio
import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.db.models import Dialog, DialogStatusConfig, Message
from app.db.session import AsyncSessionLocal
from app.sales.status_flow import earned_status
from app.sales.status_names import SIDE_STATUSES, is_ladder, rank
from app.utils.time import msk_now

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_BATCH = 500
# Сколько раз повторять пачку, оборвавшуюся на связи, и с какой задержкой.
# Задержка растёт линейно: обрыв обычно означает, что пулу нужно время.
_RETRIES = 5
_RETRY_DELAY_SECONDS = 5
_CONNECTION_ERRORS = (DBAPIError, InterfaceError, OperationalError, OSError)


async def _load_targets(days: int | None) -> tuple[dict, dict, list[int]]:
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
        return by_name, by_id, list((await db.execute(q)).scalars().all())


async def _run_chunk(chunk, by_name, by_id, dry_run, backwards) -> Counter:
    """Одна пачка в своей сессии. Счётчики возвращаем, а не копим снаружи:
    оборвавшуюся пачку повторяют целиком, и её недосчитанные переходы не должны
    попасть в итоговую сводку дважды."""
    moves: Counter = Counter()
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
            if not backwards and current_name is not None and rank(target) < rank(current_name):
                moves[f"пропущен откат: {current_name} -> {target}"] += 1
                continue

            moves[f"{current_name} -> {target}"] += 1
            if not dry_run:
                dialog.current_status_id = row.id
        if not dry_run:
            await db.commit()
    return moves


async def _chunk_with_retry(chunk, by_name, by_id, dry_run, backwards) -> Counter:
    for attempt in range(1, _RETRIES + 1):
        try:
            return await _run_chunk(chunk, by_name, by_id, dry_run, backwards)
        except _CONNECTION_ERRORS as exc:
            if attempt == _RETRIES:
                raise
            delay = _RETRY_DELAY_SECONDS * attempt
            print(f"  связь оборвалась ({exc.__class__.__name__}), повтор через {delay} с")
            await asyncio.sleep(delay)
    return Counter()


async def resync(days: int | None, dry_run: bool, backwards: bool) -> Counter:
    by_name, by_id, dialog_ids = await _load_targets(days)
    print(f"диалогов к пересчёту: {len(dialog_ids)}")

    moves: Counter = Counter()
    for start in range(0, len(dialog_ids), _BATCH):
        chunk = dialog_ids[start:start + _BATCH]
        moves += await _chunk_with_retry(chunk, by_name, by_id, dry_run, backwards)
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
