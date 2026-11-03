import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import generate_refresh_token, hash_refresh_token
from app.models import RefreshToken, RevokeReason, User
from app.modules.auth import service
from app.modules.auth.service import ClientInfo, TokenPair

RACE_EMAIL = "race@example.com"
CLIENT = ClientInfo(user_agent="pytest-client", ip="127.0.0.1")


@pytest.fixture
async def committed_session_token(engine: AsyncEngine) -> AsyncIterator[str]:
    raw_token = generate_refresh_token()
    now = datetime.now(UTC)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(email=RACE_EMAIL, password_hash="not-a-real-hash")
        session.add(user)
        await session.flush()
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw_token),
                family_id=uuid.uuid4(),
                family_started_at=now,
                issued_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        await session.commit()

    try:
        yield raw_token
    finally:
        async with AsyncSession(engine) as session:
            await session.execute(delete(User).where(User.email == RACE_EMAIL))
            await session.commit()


async def test_parallel_refresh_returns_one_pair(
    engine: AsyncEngine,
    redis_client: Redis,
    committed_session_token: str,
) -> None:
    barrier = asyncio.Barrier(2)

    async def rotate() -> TokenPair:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("SELECT 1"))
            await barrier.wait()
            return await service.rotate_refresh_token(
                session,
                redis_client,
                committed_session_token,
                CLIENT,
            )

    first, second = await asyncio.gather(rotate(), rotate())

    assert first == second

    async with AsyncSession(engine) as session:
        issued = (
            await session.scalars(
                select(RefreshToken)
                .join(User, User.id == RefreshToken.user_id)
                .where(User.email == RACE_EMAIL)
                .order_by(RefreshToken.issued_at)
            )
        ).all()

    assert len(issued) == 2
    assert issued[0].revoked_reason is RevokeReason.ROTATED
    assert issued[1].token_hash == hash_refresh_token(first.refresh_token)
    assert issued[1].revoked_at is None
