from fastapi import APIRouter, status

from app.core.deps import DbSession
from app.models import User
from app.modules.auth import service
from app.modules.auth.schemas import TokenResponse, UserLogin, UserPublic, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, session: DbSession) -> User:
    return await service.register_user(session, data)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, session: DbSession) -> TokenResponse:
    access_token = await service.authenticate_user(session, data)
    return TokenResponse(access_token=access_token)
