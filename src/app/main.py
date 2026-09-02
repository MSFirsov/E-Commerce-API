from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import register_error_handlers
from app.core.request_id import request_id_middleware
from app.modules import auth, health, users


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    print(f"Запуск в окружении {settings.environment}")
    try:
        yield
    finally:
        await engine.dispose()
        print("Завершение")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.middleware("http")(request_id_middleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)

    return app
