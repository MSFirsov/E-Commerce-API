import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.request_id import get_request_id

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code = 500
    error_type = "internal-error"
    title = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    error_type = "not-found"
    title = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    error_type = "conflict"
    title = "Conflicting state"


class UnauthorizedError(AppError):
    status_code = 401
    error_type = "unauthorized"
    title = "Authentication required"


class ForbiddenError(AppError):
    status_code = 403
    error_type = "forbidden"
    title = "Access denied"


class ServiceUnavailableError(AppError):
    status_code = 503
    error_type = "service-unavailable"
    title = "Service unavailable"


def problem_response(
    request: Request,
    status_code: int,
    error_type: str,
    title: str,
    detail: str,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"/errors/{error_type}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": get_request_id(),
        **extra,
    }
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_JSON)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_type=exc.error_type,
        title=exc.title,
        detail=exc.detail,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_type="http-error",
        title=exc.detail if isinstance(exc.detail, str) else "HTTP error",
        detail=str(exc.detail),
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=422,
        error_type="validation-error",
        title="Request validation failed",
        detail="Request body or parameters did not pass validation",
        errors=jsonable_encoder(exc.errors()),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return problem_response(
        request,
        status_code=500,
        error_type="internal-error",
        title="Internal server error",
        detail="Unexpected error, the incident is logged",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
