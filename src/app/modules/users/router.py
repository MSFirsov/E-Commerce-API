from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: CurrentUser) -> User:
    return current_user
