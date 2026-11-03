from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import REFRESH_FAMILY_MAX_TTL, hash_refresh_token
from app.models import RefreshToken, RevokeReason, User
from app.modules.auth.router import REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH
from app.modules.auth.service import GRACE_KEY_PREFIX

REGISTER_PAYLOAD = {
    "email": "alice@example.com",
    "password": "correct-password",
    "full_name": "Alice",
}
LOGIN_PAYLOAD = {"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]}


def refresh_cookie(client: AsyncClient) -> str:
    cookie = client.cookies.get(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    assert cookie is not None
    return cookie


async def register_and_login(client: AsyncClient) -> str:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/auth/login", json=LOGIN_PAYLOAD)
    assert response.status_code == 200
    return refresh_cookie(client)


async def expire_grace(redis: Redis, raw_token: str) -> None:
    await redis.delete(f"{GRACE_KEY_PREFIX}{hash_refresh_token(raw_token).hex()}")


@pytest.fixture
async def first_refresh_token(client: AsyncClient) -> str:
    return await register_and_login(client)


async def test_login_sets_httponly_refresh_cookie(client: AsyncClient) -> None:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/auth/login", json=LOGIN_PAYLOAD)

    set_cookie = response.headers["set-cookie"]
    assert f"{REFRESH_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert f"Path={REFRESH_COOKIE_PATH}" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert response.json()["refresh_token"] is None


async def test_refresh_rotates_token(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    response = await client.post("/auth/refresh")
    assert response.status_code == 200

    rotated = refresh_cookie(client)
    assert rotated != first_refresh_token

    old = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(first_refresh_token)
        )
    )
    new = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(rotated))
    )
    assert old is not None and new is not None
    assert old.revoked_reason is RevokeReason.ROTATED
    assert old.replaced_by_id == new.id
    assert new.parent_id == old.id
    assert new.family_id == old.family_id
    assert new.family_started_at == old.family_started_at


async def test_second_refresh_within_grace_returns_same_pair(
    client: AsyncClient,
    first_refresh_token: str,
) -> None:
    first = await client.post("/auth/refresh")
    second = await client.post("/auth/refresh", json={"refresh_token": first_refresh_token})

    assert second.status_code == 200
    assert second.json()["access_token"] == first.json()["access_token"]
    assert refresh_cookie(client) != first_refresh_token


async def test_reuse_after_grace_revokes_whole_family(
    client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    first_refresh_token: str,
) -> None:
    await client.post("/auth/refresh")
    rotated = refresh_cookie(client)
    await expire_grace(redis_client, first_refresh_token)

    reused = await client.post("/auth/refresh", json={"refresh_token": first_refresh_token})
    assert reused.status_code == 401

    after_reuse = await client.post("/auth/refresh", json={"refresh_token": rotated})
    assert after_reuse.status_code == 401

    family = (
        await db_session.scalars(
            select(RefreshToken).where(RefreshToken.revoked_reason == RevokeReason.REUSE_DETECTED)
        )
    ).all()
    assert len(family) == 1
    assert family[0].token_hash == hash_refresh_token(rotated)


async def test_grace_replay_requires_same_user_agent(
    client: AsyncClient,
    first_refresh_token: str,
) -> None:
    await client.post("/auth/refresh")

    from_other_device = await client.post(
        "/auth/refresh",
        json={"refresh_token": first_refresh_token},
        headers={"user-agent": "some-other-client"},
    )
    assert from_other_device.status_code == 401


async def test_unknown_refresh_token_revokes_nothing(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    response = await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401

    stored = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(first_refresh_token)
        )
    )
    assert stored is not None
    assert stored.revoked_at is None


async def test_expired_refresh_token_is_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    await db_session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    response = await client.post("/auth/refresh")
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


async def test_family_absolute_deadline_caps_new_token(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    started_at = datetime.now(UTC) - REFRESH_FAMILY_MAX_TTL + timedelta(days=1)
    await db_session.execute(update(RefreshToken).values(family_started_at=started_at))
    await db_session.commit()

    response = await client.post("/auth/refresh")
    assert response.status_code == 200

    rotated = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(refresh_cookie(client))
        )
    )
    assert rotated is not None
    assert rotated.expires_at == started_at + REFRESH_FAMILY_MAX_TTL


async def test_family_older_than_absolute_deadline_cannot_rotate(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    started_at = datetime.now(UTC) - REFRESH_FAMILY_MAX_TTL - timedelta(days=1)
    await db_session.execute(update(RefreshToken).values(family_started_at=started_at))
    await db_session.commit()

    response = await client.post("/auth/refresh")
    assert response.status_code == 401


async def test_logout_revokes_family_and_clears_cookie(
    client: AsyncClient,
    first_refresh_token: str,
) -> None:
    response = await client.post("/auth/logout")
    assert response.status_code == 204
    assert client.cookies.get(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH) is None

    reused = await client.post("/auth/refresh", json={"refresh_token": first_refresh_token})
    assert reused.status_code == 401


async def test_logout_with_unknown_token_is_idempotent(client: AsyncClient) -> None:
    response = await client.post("/auth/logout", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 204


async def test_logout_all_kills_every_device_and_current_access_token(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    phone_refresh = await register_and_login(client)
    laptop_login = await client.post("/auth/login", json=LOGIN_PAYLOAD)
    laptop_access = laptop_login.json()["access_token"]
    laptop_refresh = refresh_cookie(client)

    response = await client.post(
        "/auth/logout-all",
        headers={"Authorization": f"Bearer {laptop_access}"},
    )
    assert response.status_code == 204

    for token in (phone_refresh, laptop_refresh):
        refreshed = await client.post("/auth/refresh", json={"refresh_token": token})
        assert refreshed.status_code == 401

    denied = await client.get("/users/me", headers={"Authorization": f"Bearer {laptop_access}"})
    assert denied.status_code == 401
    assert denied.json()["type"] == "/errors/invalid-token"

    active = await db_session.scalar(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert active is None


async def test_refresh_without_token_is_401(client: AsyncClient) -> None:
    response = await client.post("/auth/refresh")
    assert response.status_code == 401


async def test_refresh_returns_token_in_body_when_enabled(
    client: AsyncClient,
    first_refresh_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "auth_refresh_in_body", True)

    response = await client.post("/auth/refresh")
    assert response.json()["refresh_token"] == refresh_cookie(client)


async def test_refresh_token_is_never_stored_in_plaintext(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    stored = await db_session.scalar(select(RefreshToken))
    assert stored is not None
    assert stored.token_hash == hash_refresh_token(first_refresh_token)
    assert first_refresh_token.encode() not in stored.token_hash


async def test_inactive_user_cannot_refresh(
    client: AsyncClient,
    db_session: AsyncSession,
    first_refresh_token: str,
) -> None:
    await db_session.execute(update(User).values(is_active=False))
    await db_session.commit()

    response = await client.post("/auth/refresh")
    assert response.status_code == 401
