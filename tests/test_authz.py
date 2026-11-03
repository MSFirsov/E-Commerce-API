from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import create_admin
from app.models import RefreshToken, RevokeReason, User, UserRole

CUSTOMER = {"email": "customer@example.com", "password": "correct-password"}
ADMIN = {"email": "boss@example.com", "password": "admin-password"}


async def access_token(client: AsyncClient, credentials: dict[str, str]) -> str:
    response = await client.post("/auth/login", json=credentials)
    assert response.status_code == 200
    token: str = response.json()["access_token"]
    return token


async def test_customer_cannot_list_users(client: AsyncClient) -> None:
    await client.post("/auth/register", json=CUSTOMER)
    token = await access_token(client, CUSTOMER)

    response = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["type"] == "/errors/forbidden"


async def test_admin_can_list_users(client: AsyncClient, db_session: AsyncSession) -> None:
    await client.post("/auth/register", json=CUSTOMER)
    await create_admin(db_session, ADMIN["email"], ADMIN["password"])
    token = await access_token(client, ADMIN)

    response = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    emails = {user["email"] for user in response.json()}
    assert emails == {CUSTOMER["email"], ADMIN["email"]}


async def test_anonymous_request_is_401_not_403(client: AsyncClient) -> None:
    response = await client.get("/users")
    assert response.status_code == 401


async def test_create_admin_promotes_existing_user_and_revokes_sessions(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await client.post("/auth/register", json=CUSTOMER)
    await client.post("/auth/login", json=CUSTOMER)

    user, created = await create_admin(db_session, CUSTOMER["email"].upper(), "ignored-password")
    assert created is False
    assert user.role is UserRole.ADMIN

    token = await db_session.scalar(select(RefreshToken))
    assert token is not None
    assert token.revoked_reason is RevokeReason.ADMIN

    refreshed = await client.post("/auth/refresh")
    assert refreshed.status_code == 401


async def test_create_admin_creates_new_user(db_session: AsyncSession) -> None:
    user, created = await create_admin(db_session, "New@Example.com", "admin-password")

    assert created is True
    assert user.email == "new@example.com"
    assert user.role is UserRole.ADMIN

    stored = await db_session.scalar(select(User).where(User.id == user.id))
    assert stored is not None
    assert stored.password_hash.startswith("$argon2")
