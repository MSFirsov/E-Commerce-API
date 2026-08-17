from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.modules import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    print(f"Запуск в окружении {settings.environment}")
    yield
    print("Завершение")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.include_router(health.router)

    return app
