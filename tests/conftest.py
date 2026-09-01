import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.db import get_session
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_settings = get_settings()
TEST_DB_URL: URL = make_url(_settings.database_url).set(database=_settings.postgres_test_db)


async def _create_test_database() -> None:
    admin_engine = create_async_engine(
        TEST_DB_URL.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_URL.database},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{TEST_DB_URL.database}"'))
    finally:
        await admin_engine.dispose()


def _upgrade_to_head() -> None:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DB_URL.render_as_string(hide_password=False))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    await _create_test_database()
    await asyncio.to_thread(_upgrade_to_head)

    test_engine = create_async_engine(TEST_DB_URL)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.clear()
