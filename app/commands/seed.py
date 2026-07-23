"""python -m app.commands.seed — populate DB with initial data.

Чистая установка VK-версии: админ, дефолтное направление и базовый набор
статусов, на имена которых завязана логика (runner/ping/webhook):
«Поинтересовался» — стартовый статус нового диалога, «Ждем предоплату» /
«Заказ оформлен» — управление пинг-воронками, «ЧС» — стоп-статус,
«Нужен куратор» — эскалация. Скрипты, пинг-правила и группы ВК
добавляются через админку.
"""
import asyncio

from sqlalchemy import select

from app.auth.service import hash_password
from app.db.models import DialogStatusConfig, DialogType, User, UserRole
from app.db.session import AsyncSessionLocal

DEFAULT_STATUSES = [
    "Поинтересовался",
    "Есть расчет",
    "Горячий клиент",
    "Ждем предоплату",
    "Заказ оформлен",
    "Нужен куратор",
    "ЧС",
]


async def seed():
    async with AsyncSessionLocal() as session:
        # Admin user
        result = await session.execute(select(User).where(User.email == "admin@hemilton.ai"))
        if not result.scalar_one_or_none():
            session.add(User(
                email="admin@hemilton.ai",
                password_hash=hash_password("admin1234"),
                role=UserRole.admin,
            ))
            print("[seed] Created admin user: admin@hemilton.ai / admin1234")

        # Default dialog type (группы ВК ссылаются на направление через dialog_type_id)
        result = await session.execute(select(DialogType).limit(1))
        if not result.scalar_one_or_none():
            session.add(DialogType(name="default", display_name="Основное направление"))
            print("[seed] Created default dialog type")

        # Base statuses referenced by code
        existing = {
            name for (name,) in (await session.execute(select(DialogStatusConfig.name))).all()
        }
        for name in DEFAULT_STATUSES:
            if name not in existing:
                session.add(DialogStatusConfig(name=name, pattern="", is_active=True))
                print(f"[seed] Created status: {name}")

        await session.commit()
        print("[seed] Done.")


if __name__ == "__main__":
    asyncio.run(seed())
