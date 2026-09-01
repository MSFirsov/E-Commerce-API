from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.deps import DbSession
from app.core.errors import ServiceUnavailableError

router = APIRouter(prefix="", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(session: DbSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise ServiceUnavailableError("Database is not reachable") from exc
    return {"status": "ok", "database": "ok"}
