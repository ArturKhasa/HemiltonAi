"""Разовая команда: перенести картинки скриптов и пингов на наш сервер.

Новые картинки забирает к себе сама админка (app.storage.rehost вызывается при
сохранении скрипта и пинг-правила), а эта команда приводит к тому же виду то,
что накопилось раньше.

Зачем: ссылка на CDN ВК умирает молча — перезалитый по ней объект перестаёт
существовать, `messages.send` принимает его без ошибки и просто не кладёт в
сообщение. С 8 августа так ушли 85 сообщений с ценой и 28 с оформлением, все
без картинок. Картинки приветствия лежат у нас и не потерялись ни разу.

    python -m app.commands.rehost_script_media --dry-run   # посмотреть
    python -m app.commands.rehost_script_media             # перенести

Строки кэша перезаливок по старым ссылкам удаляются: следующая отправка зальёт
картинку в ВК заново, уже с нашего адреса.
"""
import argparse
import asyncio
import logging
import sys

from sqlalchemy import delete, select

from app.db.models import PingRule, Script, VkAttachmentCache
from app.db.session import AsyncSessionLocal
from app.storage.rehost import external_photo_urls, rehost_external_photos

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Поля с текстом, в которых живут токены картинок.
_FIELDS = {
    Script: ("phrase_text",),
    PingRule: ("phrase_text", "manual_text"),
}


async def main(dry_run: bool) -> int:
    moved: dict[str, str] = {}
    touched_rows = 0

    async with AsyncSessionLocal() as db:
        for model, fields in _FIELDS.items():
            for row in (await db.execute(select(model))).scalars().all():
                changed = False
                for field in fields:
                    text = getattr(row, field) or ""
                    urls = external_photo_urls(text)
                    if not urls:
                        continue
                    if dry_run:
                        logger.info(
                            "%s id=%s: перенесли бы %d шт. — %s",
                            model.__name__, row.id, len(urls),
                            ", ".join(u[:60] for u in urls),
                        )
                        moved.update({u: "" for u in urls})
                        changed = True
                        continue
                    updated = await rehost_external_photos(text, moved)
                    if updated != text:
                        setattr(row, field, updated)
                        changed = True
                if changed:
                    touched_rows += 1

        if dry_run:
            logger.info(
                "СУХОЙ ПРОГОН: %d картинок в %d записях", len(moved), touched_rows,
            )
            return 0

        if moved:
            await db.execute(
                delete(VkAttachmentCache).where(
                    VkAttachmentCache.source_url.in_(list(moved))
                )
            )
        await db.commit()

    logger.info("готово: перенесено %d картинок, обновлено записей %d", len(moved), touched_rows)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="показать, что будет перенесено, и выйти",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
