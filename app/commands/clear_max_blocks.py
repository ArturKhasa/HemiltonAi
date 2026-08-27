"""Разовая команда: снять с MAX-диалогов отметку «отправка запрещена».

До 27.08 отметку `dialogs.vk_blocked` ставило само событие MAX (`bot_stopped`
и `dialog_removed`), а не отказ мессенджера на отправку. К обеду 27.08 «в
блоке» оказались 162 MAX-диалога из 361, и снять отметку было нечем: она
запрещает отправку насовсем. Проверка по истории MAX показала, что в 17 из 60
таких диалогов после отметки боту приходили новые исходящие — до шестнадцати
штук, — то есть писать этим клиентам можно было всё это время.

Событие отметку больше не ставит (app.max.webhook.handle_bot_stopped), но
накопленные снимать некому. Отсюда команда:

    python -m app.commands.clear_max_blocks          # показать, сколько снимет
    python -m app.commands.clear_max_blocks --apply  # снять

Ошибиться она не даёт: клиент, который бота правда остановил, вернёт отказ на
первой же отправке, и диалог пометится снова — уже по факту, а не по догадке.
"""
import argparse
import asyncio
import logging

from sqlalchemy import select, update

from app.db.models import Client, Dialog, VkGroup
from app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _max_dialog_ids():
    return (
        select(Dialog.id)
        .join(Client, Dialog.client_id == Client.id)
        .join(VkGroup, Client.vk_group_id == VkGroup.id)
        .where(VkGroup.platform == "max", Dialog.vk_blocked == True)  # noqa: E712
    )


async def run(apply: bool) -> int:
    async with AsyncSessionLocal() as db:
        ids = list((await db.execute(_max_dialog_ids())).scalars().all())
        if not ids:
            logger.info("MAX-диалогов с отметкой «отправка запрещена» нет")
            return 0
        if not apply:
            logger.info("нашлось %d диалогов; запустите с --apply, чтобы снять", len(ids))
            return len(ids)
        await db.execute(
            update(Dialog).where(Dialog.id.in_(ids)).values(vk_blocked=False)
        )
        await db.commit()
        logger.info("отметка снята у %d MAX-диалогов", len(ids))
        return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="снять отметки, а не только посчитать")
    args = parser.parse_args()
    asyncio.run(run(args.apply))


if __name__ == "__main__":
    main()
