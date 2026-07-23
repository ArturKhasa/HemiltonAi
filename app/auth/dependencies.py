from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import decode_token
from app.db.models import User, UserDialogType, UserRole
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise exc
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise exc
    return user


def require_role(*roles: str):
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker


async def get_allowed_type_ids(user: User, db: AsyncSession) -> list[int] | None:
    """Направления, доступные пользователю. None = без ограничений (админ).

    Пустой список = доступа нет ни к одному направлению.
    """
    if user.role == UserRole.admin:
        return None
    result = await db.execute(
        select(UserDialogType.type_id).where(UserDialogType.user_id == user.id)
    )
    return list(result.scalars().all())


async def ensure_type_access(user: User, type_id: int | None, db: AsyncSession) -> None:
    """403, если направление диалога пользователю не выдано."""
    allowed = await get_allowed_type_ids(user, db)
    if allowed is None:
        return
    if type_id is None or type_id not in allowed:
        raise HTTPException(status_code=403, detail="No access to this dialog type")
