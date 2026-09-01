from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_db_reaches_database(client: AsyncClient) -> None:
    response = await client.get("/health/db")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_request_id_is_echoed_back(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "fixed-id-for-test"})

    assert response.headers["X-Request-ID"] == "fixed-id-for-test"


async def test_unknown_path_returns_problem_details(client: AsyncClient) -> None:
    response = await client.get("/no-such-path")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "/errors/http-error"
    assert body["status"] == 404
    assert body["instance"] == "/no-such-path"
    assert body["request_id"]
