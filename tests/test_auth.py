import base64
import time
from uuid import UUID

import jwt
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER, create_access_token
from app.models import User

REGISTER_PAYLOAD = {
    "email": "Alice@example.com",
    "password": "correct-password",
    "full_name": "Alice",
}


def _drop_volatile(body: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in body.items() if k not in ("instance", "request_id")}


async def test_register_then_login_then_me(client: AsyncClient) -> None:
    register_response = await client.post("/auth/register", json=REGISTER_PAYLOAD)
    assert register_response.status_code == 201
    body = register_response.json()
    assert body["email"] == REGISTER_PAYLOAD["email"].lower()
    assert "password_hash" not in body
    assert "password" not in body

    login_response = await client.post(
        "/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    me_response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["email"] == REGISTER_PAYLOAD["email"].lower()
    assert "password_hash" not in me_body


async def test_register_duplicate_email_case_insensitive(client: AsyncClient) -> None:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)

    duplicate = await client.post(
        "/auth/register",
        json={**REGISTER_PAYLOAD, "email": REGISTER_PAYLOAD["email"].upper()},
    )
    assert duplicate.status_code == 409


async def test_login_response_identical_for_wrong_password_and_unknow_email(
    client: AsyncClient,
) -> None:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)

    wrong_password = await client.post(
        "/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "definitely-wrong-password"},
    )
    unknown_email = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "definitely-wrong-password"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert _drop_volatile(wrong_password.json()) == _drop_volatile(unknown_email.json())


async def test_me_without_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_me_with_expired_token_gives_distinct_error_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    user = await db_session.scalar(
        select(User).where(User.email == REGISTER_PAYLOAD["email"].lower())
    )
    assert user is not None

    settings = get_settings()
    expired_payload = {
        "sub": str(user.id),
        "jti": "expired-token",
        "iat": int(time.time()) - 3600,
        "exp": int(time.time()) - 1800,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "typ": "access",
        "role": user.role,
    }
    expired_token = jwt.encode(
        expired_payload,
        settings.secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.json()["type"] == "/errors/token-expired"


async def test_me_rejects_token_signed_with_wrong_secret(client: AsyncClient) -> None:
    forged_token = jwt.encode(
        {
            "sub": str(UUID(int=0)),
            "jti": "forged",
            "iat": int(time.time()),
            "exp": int(time.time()) + 900,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "typ": "access",
            "role": "customer",
        },
        "someone-elses-secret-that-is-long-enough-for-hmac",
        algorithm=JWT_ALGORITHM,
    )

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert response.status_code == 401
    assert response.json()["type"] == "/errors/invalid-token"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


async def test_me_rejects_alg_none_token(client: AsyncClient) -> None:
    header = _b64url(b'{"alg":"none","typ":"JWT"}')
    now = int(time.time())
    payload = _b64url(
        (
            f'{{"sub":"{UUID(int=0)}","typ":"access","iss":"{JWT_ISSUER}",'
            f'"aud":"{JWT_AUDIENCE}","iat":{now},"exp":{now + 900}}}'
        ).encode()
    )
    alg_none_token = f"{header}.{payload}."

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {alg_none_token}"},
    )
    assert response.status_code == 401
    assert response.json()["type"] == "/errors/invalid-token"


async def test_access_token_has_expected_claims() -> None:
    token = create_access_token(user_id=UUID(int=0), role="customer")

    decoded = jwt.decode(token, options={"verify_signature": False})

    assert decoded["typ"] == "access"
    assert decoded["iss"] == JWT_ISSUER
    assert decoded["aud"] == JWT_AUDIENCE
    assert decoded["role"] == "customer"
    assert {"sub", "jti", "iat", "exp"} <= decoded.keys()
