"""Перенос картинок скриптов и пингов на наш сервер.

Новые картинки забирает к себе сама админка (app.storage.rehost вызывается при
сохранении скрипта и пинг-правила), а этот перенос приводит к тому же виду то,
что накопилось раньше.

Зачем: ссылка на CDN ВК умирает молча — перезалитый по ней объект перестаёт
существовать, `messages.send` принимает его без ошибки и просто не кладёт в
сообщение. С 8 августа так ушли 85 сообщений с ценой и 28 с оформлением, все
без картинок. Картинки приветствия лежат у нас и не потерялись ни разу.

Разовой командой это уже пробовали 17 августа — и не выполнили: 21 августа цена
уходила без картинок в 64 случаях из 89, а приветствие с нашими ссылками
доехало с картинками все 90 раз из 90. Поэтому перенос теперь идёт сам при
старте приложения (`rehost_on_startup`, вызывается из lifespan): выкатка кода и
есть выполнение. Руками — по-прежнему можно:

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
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PingRule, Script, VkAttachmentCache
from app.db.session import AsyncSessionLocal
from app.storage.rehost import external_photo_urls, rehost_external_photos

logger = logging.getLogger(__name__)

# Поля с текстом, в которых живут токены картинок.
_FIELDS = {
    Script: ("phrase_text",),
    PingRule: ("phrase_text", "manual_text"),
}


async def rehost_all(db: AsyncSession, dry_run: bool = False) -> tuple[int, int]:
    """Перенести чужие картинки скриптов и пинг-правил к себе.

    Возвращает (сколько картинок, сколько записей). Ничего чужого в текстах нет —
    возвращает (0, 0), не сходив в сеть ни разу: на старте это обычный случай.
    """
    moved: dict[str, str] = {}
    touched_rows = 0

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
        return len(moved), touched_rows

    if moved:
        await db.execute(
            delete(VkAttachmentCache).where(
                VkAttachmentCache.source_url.in_(list(moved))
            )
        )
    await db.commit()
    return len(moved), touched_rows


async def rehost_on_startup() -> None:
    """Перенос при старте приложения. Упасть отсюда нельзя: без картинок диалог
    хуже, но без приложения — совсем никак."""
    from app.config import settings

    # Без публичного адреса наши ссылки получаются относительными («/media/…»),
    # а качает картинку по ним ВК со своей стороны. Молча превратить рабочие
    # ссылки в нерабочие хуже, чем не переносить вовсе.
    if not settings.MEDIA_PUBLIC_URL.strip():
        logger.warning(
            "перенос картинок пропущен: не задан MEDIA_PUBLIC_URL — "
            "наши ссылки получились бы относительными",
        )
        return
    try:
        async with AsyncSessionLocal() as db:
            moved, rows = await rehost_all(db)
    except Exception:
        logger.exception("перенос картинок при старте не удался")
        return
    if moved:
        logger.info(
            "картинки скриптов перенесены к нам: %d шт. в %d записях", moved, rows,
        )


async def main(dry_run: bool) -> int:
    async with AsyncSessionLocal() as db:
        moved, touched_rows = await rehost_all(db, dry_run)
    if dry_run:
        logger.info("СУХОЙ ПРОГОН: %d картинок в %d записях", moved, touched_rows)
    else:
        logger.info(
            "готово: перенесено %d картинок, обновлено записей %d", moved, touched_rows,
        )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="показать, что будет перенесено, и выйти",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
