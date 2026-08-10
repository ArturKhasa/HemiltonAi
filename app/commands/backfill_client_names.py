"""Разовая команда: проставить имена и фамилии клиентам, заведённым без них.

Имя из профиля ВК мы не запрашивали вовсе, и у всех боевых клиентов
`clients.name` пуст. Новых заполняет вебхук при первом сообщении
(app.vk.webhook._fill_client_name), а уже накопленным — эта команда.

    python -m app.commands.backfill_client_names

Идёт пачками по 100 идентификаторов: столько users.get принимает за раз.
"""
import asyncio
import logging

from sqlalchemy import or_, select

from app.db.models import Client, VkGroup
from app.db.session import AsyncSessionLocal
from app.vk.sender import vk_api_call

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Максимум, который VK users.get принимает за один вызов.
_BATCH = 100


async def _names_for(
    access_token: str, vk_user_ids: list[int],
) -> dict[int, tuple[str | None, str | None]]:
    rows = await vk_api_call(
        access_token, "users.get",
        {"user_ids": ",".join(str(i) for i in vk_user_ids), "fields": "first_name,last_name"},
    )
    names: dict[int, tuple[str | None, str | None]] = {}
    for row in rows or []:
        first = (row.get("first_name") or "").strip()
        last = (row.get("last_name") or "").strip()
        if (first or last) and row.get("id"):
            names[int(row["id"])] = (first or None, last or None)
    return names


async def main() -> None:
    filled = 0
    async with AsyncSessionLocal() as db:
        groups = (await db.execute(select(VkGroup))).scalars().all()
        for group in groups:
            if not group.access_token:
                logger.info("группа %s без токена — пропускаем", group.group_id)
                continue
            clients = (await db.execute(
                select(Client).where(
                    Client.vk_group_id == group.id,
                    Client.vk_user_id.isnot(None),
                    or_(
                        Client.name.is_(None), Client.name == "",
                        Client.last_name.is_(None),
                    ),
                )
            )).scalars().all()
            logger.info("группа %s: без имени %d клиентов", group.group_id, len(clients))

            for start in range(0, len(clients), _BATCH):
                chunk = clients[start:start + _BATCH]
                try:
                    names = await _names_for(
                        group.access_token, [c.vk_user_id for c in chunk],
                    )
                except Exception as exc:
                    logger.error("users.get упал на пачке %d: %s", start, exc)
                    continue
                for client in chunk:
                    found = names.get(int(client.vk_user_id))
                    if found:
                        client.name, client.last_name = found
                        filled += 1
                await db.commit()
    logger.info("готово: имён проставлено %d", filled)


if __name__ == "__main__":
    asyncio.run(main())
