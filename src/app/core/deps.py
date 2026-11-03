from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ForbiddenError, InvalidTokenError
from app.core.redis import RedisClient
from app.core.security import decode_access_token, is_access_token_denied
from app.models import User, UserRole

DbSession = Annotated[AsyncSession, Depends(get_session)]

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_access_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    redis: RedisClient,
) -> dict[str, Any]:
    if credentials is None:
        raise InvalidTokenError("Missing bearer token")

    payload = decode_access_token(credentials.credentials)

    if await is_access_token_denied(redis, payload["jti"]):
        raise InvalidTokenError("Token has been revoked")

    return payload


AccessPayload = Annotated[dict[str, Any], Depends(get_access_payload)]


async def get_current_user(session: DbSession, payload: AccessPayload) -> User:
    user = await session.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise InvalidTokenError("Token does not match an active user")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(current_user: CurrentUser) -> User:
    if current_user.role is not UserRole.ADMIN:
        raise ForbiddenError("Admin role is required")

    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
