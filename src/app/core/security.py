import time
import uuid
from typing import Any

import anyio
import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.errors import InvalidTokenError, TokenExpiredError

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "e-commerce-api"
JWT_AUDIENCE = "e-commerce-api-clients"
ACCESS_TOKEN_TTL_SECONDS = 15 * 60

_settings = get_settings()
_password_hash = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = _password_hash.hash("dummy-password-for-timing-parity")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    return _password_hash.verify(password, password_hash or _DUMMY_PASSWORD_HASH)


async def hash_password_async(password: str) -> str:
    return await anyio.to_thread.run_sync(hash_password, password)


async def verify_password_async(password: str, password_hash: str | None) -> bool:
    return await anyio.to_thread.run_sync(verify_password, password, password_hash)


def create_access_token(*, user_id: uuid.UUID, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "typ": "access",
        "role": role,
    }
    return jwt.encode(payload, _settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            _settings.secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("Access token is invalid") from exc

    if payload.get("typ") != "access":
        raise InvalidTokenError("Token is not an access token")

    return payload
