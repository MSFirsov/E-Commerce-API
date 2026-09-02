from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import InvalidTokenError
from app.core.security import decode_access_token
from app.models import User

DbSession = Annotated[AsyncSession, Depends(get_session)]

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> User:
    if credentials is None:
        raise InvalidTokenError("Missing bearer token")

    payload = decode_access_token(credentials.credentials)
    user = await session.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise InvalidTokenError("Token does not match an active user")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
