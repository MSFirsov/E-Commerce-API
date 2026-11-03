import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, InvalidCredentialsError, InvalidTokenError
from app.core.security import (
    REFRESH_FAMILY_MAX_TTL,
    REFRESH_GRACE_PERIOD,
    REFRESH_TOKEN_TTL,
    create_access_token,
    deny_access_token,
    generate_refresh_token,
    hash_password_async,
    hash_refresh_token,
    verify_password_async,
)
from app.models import RefreshToken, RevokeReason, User
from app.modules.auth.schemas import UserLogin, UserRegister

logger = logging.getLogger(__name__)

GRACE_KEY_PREFIX = "auth:grace:"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip: str | None = None


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


async def authenticate_user(
    session: AsyncSession,
    data: UserLogin,
    client: ClientInfo,
) -> TokenPair:
    email = data.email.lower()
    user = await session.scalar(select(User).where(User.email == email))

    password_matches = await verify_password_async(
        data.password,
        user.password_hash if user is not None else None,
    )

    if user is None or not user.is_active or not password_matches:
        raise InvalidCredentialsError("Invalid email or password")

    now = datetime.now(UTC)
    token, raw_token = _build_refresh_token(
        user_id=user.id,
        family_id=uuid.uuid4(),
        family_started_at=now,
        parent_id=None,
        now=now,
        client=client,
    )
    session.add(token)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(user_id=user.id, role=user.role),
        refresh_token=raw_token,
    )


async def rotate_refresh_token(
    session: AsyncSession,
    redis: Redis,
    raw_token: str,
    client: ClientInfo,
) -> TokenPair:
    token_hash = hash_refresh_token(raw_token)
    current = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )

    if current is None:
        raise InvalidTokenError("Refresh token is not recognised")

    now = datetime.now(UTC)

    if current.used_at is not None or current.revoked_at is not None:
        replayed = await _replay_grace_response(redis, token_hash, client)
        if replayed is not None:
            return replayed

        await _revoke_family(session, current.family_id, RevokeReason.REUSE_DETECTED, now)
        await session.commit()
        logger.warning(
            "Refresh token reuse detected, family %s revoked for user %s",
            current.family_id,
            current.user_id,
        )
        raise InvalidTokenError("Session has been terminated, sign in again")

    if current.expires_at <= now:
        raise InvalidTokenError("Refresh token expired")

    user = await session.get(User, current.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("Token does not match an active user")

    successor, raw_successor = _build_refresh_token(
        user_id=current.user_id,
        family_id=current.family_id,
        family_started_at=current.family_started_at,
        parent_id=current.id,
        now=now,
        client=client,
    )
    session.add(successor)
    await session.flush()

    current.used_at = now
    current.revoked_at = now
    current.revoked_reason = RevokeReason.ROTATED
    current.replaced_by_id = successor.id

    pair = TokenPair(
        access_token=create_access_token(user_id=user.id, role=user.role),
        refresh_token=raw_successor,
    )
    await _store_grace_response(redis, token_hash, pair, client)
    await session.commit()

    return pair


async def logout(
    session: AsyncSession,
    redis: Redis,
    raw_token: str,
) -> None:
    token_hash = hash_refresh_token(raw_token)
    current = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if current is None:
        return

    await _revoke_family(session, current.family_id, RevokeReason.LOGOUT, datetime.now(UTC))
    await session.commit()
    await redis.delete(f"{GRACE_KEY_PREFIX}{token_hash.hex()}")


async def logout_everywhere(
    session: AsyncSession,
    redis: Redis,
    user: User,
    access_payload: dict[str, Any],
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoked_reason=RevokeReason.LOGOUT)
    )
    await session.commit()
    await deny_access_token(redis, access_payload)


def _build_refresh_token(
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    family_started_at: datetime,
    parent_id: uuid.UUID | None,
    now: datetime,
    client: ClientInfo,
) -> tuple[RefreshToken, str]:
    family_deadline = family_started_at + REFRESH_FAMILY_MAX_TTL
    if family_deadline <= now:
        raise InvalidTokenError("Session lifetime exceeded, sign in again")

    raw_token = generate_refresh_token()
    token = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        family_id=family_id,
        family_started_at=family_started_at,
        parent_id=parent_id,
        issued_at=now,
        expires_at=min(now + REFRESH_TOKEN_TTL, family_deadline),
        user_agent=client.user_agent,
        ip=client.ip,
    )
    return token, raw_token


async def _revoke_family(
    session: AsyncSession,
    family_id: uuid.UUID,
    reason: RevokeReason,
    now: datetime,
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )


async def _store_grace_response(
    redis: Redis,
    token_hash: bytes,
    pair: TokenPair,
    client: ClientInfo,
) -> None:
    payload = json.dumps(
        {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "user_agent": client.user_agent,
        }
    )
    await redis.set(
        f"{GRACE_KEY_PREFIX}{token_hash.hex()}",
        payload,
        ex=int(REFRESH_GRACE_PERIOD.total_seconds()),
    )


async def _replay_grace_response(
    redis: Redis,
    token_hash: bytes,
    client: ClientInfo,
) -> TokenPair | None:
    cached = await redis.get(f"{GRACE_KEY_PREFIX}{token_hash.hex()}")
    if cached is None:
        return None

    stored = json.loads(cached)
    if stored["user_agent"] != client.user_agent:
        return None

    return TokenPair(
        access_token=stored["access_token"],
        refresh_token=stored["refresh_token"],
    )
