from collections.abc import Sequence

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import AdminUser, CurrentUser, DbSession
from app.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: CurrentUser) -> User:
    return current_user


@router.get("", response_model=list[UserPublic])
async def list_users(session: DbSession, admin: AdminUser) -> Sequence[User]:
    result = await session.scalars(select(User).order_by(User.created_at.desc()).limit(50))
    return result.all()
