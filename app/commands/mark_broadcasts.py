"""python -m app.commands.mark_broadcasts — пометить старые рассылки в базе.

Массовая рассылка и ответ менеджера лежат в `messages` одинаково — роль
`curator`. Живой трафик их различает по разлёту (`app.vk.broadcast`: один и тот
же текст в десяток диалогов за полчаса — рассылка) и с 27.08 пишет в метаданные
`broadcast: true`. На уже накопленной истории этой пометки нет, а разница
принципиальна: рассылок 637 807 сообщений из 667 561 с ролью `curator`, и цена в
них — обычное дело. «ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА» ушла в 58 238 диалогов,
«300 руб. — и скидка 25 %» — в 73 716. Без пометки лестница статусов
(`app.sales.status_flow`) прочитает их как отправленный клиенту расчёт и поднимет
в «Есть расчет» 78 тысяч диалогов, где никакого расчёта не было.

Тот же признак, что и на живом трафике, только посчитанный по всей базе: текст,
ушедший в 10 и больше разных диалогов, — рассылка. Ключ — первые 200 символов в
нижнем регистре, как в `app.vk.broadcast._key`.

Запускать ОДИН раз перед `python -m app.commands.resync_statuses`.

    python -m app.commands.mark_broadcasts --dry-run
    python -m app.commands.mark_broadcasts
"""
import argparse
import asyncio

from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.vk.broadcast import _KEY_LEN, _MIN_DIALOGS

# Ключ считаем так же, как живой детектор (app.vk.broadcast._key): срезаем
# обращение по имени в начале — персонализированная рассылка отличается только
# им. Без этого 33 тысячи её сообщений остались бы неопознанными.


def _key_expr(column: str) -> str:
    return (
        f"lower(left(regexp_replace({column}, "
        f"'^[[:space:]]*[А-ЯЁA-Z][а-яёa-z]+[[:space:]]*[,!][[:space:]]*', ''), {_KEY_LEN}))"
    )


_KEYS_SQL = f"""
    SELECT {_key_expr("text")} AS k
    FROM messages
    WHERE role = 'curator'
    GROUP BY 1
    HAVING count(DISTINCT dialog_id) >= {_MIN_DIALOGS}
"""

_COUNT_SQL = f"""
    WITH keys AS ({_KEYS_SQL})
    SELECT count(*)
    FROM messages m
    WHERE m.role = 'curator'
      AND {_key_expr("m.text")} IN (SELECT k FROM keys)
      AND coalesce((m.metadata ->> 'broadcast')::bool, false) = false
"""

# Пишем через слияние объектов: остальные ключи метаданных (delivered, VK id)
# должны остаться на месте. coalesce — на строки, где metadata пустая.
# Колонка в базе называется metadata, в моделях — msg_metadata.
_UPDATE_SQL = f"""
    WITH keys AS ({_KEYS_SQL}),
    target AS (
        SELECT m.id
        FROM messages m
        WHERE m.role = 'curator'
          AND {_key_expr("m.text")} IN (SELECT k FROM keys)
          AND coalesce((m.metadata ->> 'broadcast')::bool, false) = false
        LIMIT :batch
    )
    UPDATE messages
    SET metadata = coalesce(metadata::jsonb, '{{}}'::jsonb) || '{{"broadcast": true}}'::jsonb
    WHERE id IN (SELECT id FROM target)
"""

_BATCH = 20000


async def mark(dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        total = (await db.execute(text(_COUNT_SQL))).scalar_one()
        print(f"сообщений рассылок без пометки: {total}")
        if dry_run or not total:
            if dry_run:
                print("dry-run: ничего не записано")
            return

        done = 0
        while True:
            result = await db.execute(text(_UPDATE_SQL), {"batch": _BATCH})
            await db.commit()
            if not result.rowcount:
                break
            done += result.rowcount
            print(f"  помечено {done}/{total}")
        print(f"готово: {done}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Пометить исторические рассылки в messages")
    parser.add_argument("--dry-run", action="store_true", help="посчитать, но ничего не менять")
    args = parser.parse_args()
    asyncio.run(mark(args.dry_run))


if __name__ == "__main__":
    main()
