from httpx import AsyncClient
from redis.asyncio import Redis

CREDENTIALS = {"email": "alice@example.com", "password": "correct-password"}


async def test_sixth_login_attempt_is_throttled(client: AsyncClient) -> None:
    await client.post("/auth/register", json=CREDENTIALS)

    for _ in range(5):
        allowed = await client.post("/auth/login", json=CREDENTIALS)
        assert allowed.status_code == 200

    throttled = await client.post("/auth/login", json=CREDENTIALS)
    assert throttled.status_code == 429
    assert throttled.json()["type"] == "/errors/too-many-requests"
    assert 0 < int(throttled.headers["retry-after"]) <= 60


async def test_failed_logins_count_towards_the_limit(client: AsyncClient) -> None:
    await client.post("/auth/register", json=CREDENTIALS)

    for _ in range(5):
        rejected = await client.post(
            "/auth/login",
            json={**CREDENTIALS, "password": "wrong-password"},
        )
        assert rejected.status_code == 401

    throttled = await client.post("/auth/login", json=CREDENTIALS)
    assert throttled.status_code == 429


async def test_register_limit_is_separate_from_login_limit(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    for index in range(3):
        created = await client.post(
            "/auth/register",
            json={"email": f"user{index}@example.com", "password": "correct-password"},
        )
        assert created.status_code == 201

    throttled = await client.post(
        "/auth/register",
        json={"email": "user4@example.com", "password": "correct-password"},
    )
    assert throttled.status_code == 429

    login = await client.post("/auth/login", json={**CREDENTIALS, "email": "user0@example.com"})
    assert login.status_code == 200

    assert await redis_client.exists("ratelimit:register:127.0.0.1") == 1
    assert await redis_client.exists("ratelimit:login:127.0.0.1") == 1
