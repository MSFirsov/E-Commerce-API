from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request, Response, status

from app.core.config import get_settings
from app.core.deps import AccessPayload, CurrentUser, DbSession
from app.core.errors import InvalidTokenError
from app.core.ratelimit import RateLimit
from app.core.redis import RedisClient
from app.core.security import REFRESH_TOKEN_TTL
from app.models import User
from app.modules.auth import service
from app.modules.auth.schemas import (
    RefreshRequest,
    TokenResponse,
    UserLogin,
    UserPublic,
    UserRegister,
)
from app.modules.auth.service import ClientInfo, TokenPair

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"

RefreshBody = Annotated[RefreshRequest | None, Body()]

_settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimit("register", times=3, seconds=3600))],
)
async def register(data: UserRegister, session: DbSession) -> User:
    return await service.register_user(session, data)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimit("login", times=5, seconds=60))],
)
async def login(
    data: UserLogin,
    request: Request,
    response: Response,
    session: DbSession,
) -> TokenResponse:
    pair = await service.authenticate_user(session, data, _client_info(request))
    return _token_response(response, pair)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimit("refresh", times=30, seconds=60))],
)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    redis: RedisClient,
    body: RefreshBody = None,
) -> TokenResponse:
    raw_token = _extract_refresh_token(request, body)
    pair = await service.rotate_refresh_token(session, redis, raw_token, _client_info(request))
    return _token_response(response, pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: DbSession,
    redis: RedisClient,
    body: RefreshBody = None,
) -> None:
    raw_token = _extract_refresh_token(request, body)
    await service.logout(session, redis, raw_token)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    session: DbSession,
    redis: RedisClient,
    current_user: CurrentUser,
    access_payload: AccessPayload,
) -> None:
    await service.logout_everywhere(session, redis, current_user, access_payload)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )


def _extract_refresh_token(request: Request, body: RefreshRequest | None) -> str:
    from_body = body.refresh_token if body is not None else None
    raw_token = from_body or request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise InvalidTokenError("Refresh token is missing")

    return raw_token


def _token_response(response: Response, pair: TokenPair) -> TokenResponse:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        pair.refresh_token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=_settings.auth_cookie_secure,
        samesite="lax",
    )
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token if _settings.auth_refresh_in_body else None,
    )
