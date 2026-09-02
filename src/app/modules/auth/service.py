from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, InvalidCredentialsError
from app.core.security import (
    create_access_token,
    hash_password_async,
    verify_password_async,
)
from app.models import User
from app.modules.auth.schemas import UserLogin, UserRegister


async def register_user(session: AsyncSession, data: UserRegister) -> User:
    email = data.email.lower()

    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError("User with this email already exists")

    password_hash = await hash_password_async(data.password)
    user = User(email=email, password_hash=password_hash, full_name=data.full_name)

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, data: UserLogin) -> str:
    email = data.email.lower()
    user = await session.scalar(select(User).where(User.email == email))

    password_matches = await verify_password_async(
        data.password,
        user.password_hash if user is not None else None,
    )

    if user is None or not user.is_active or not password_matches:
        raise InvalidCredentialsError("Invalid email or password")

    return create_access_token(user_id=user.id, role=user.role)
