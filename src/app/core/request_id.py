from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request, Response

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id.get()


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if 0 < len(incoming) <= 64 else str(uuid4())

    token = _request_id.set(request_id)
    try:
        response = await call_next(request)
    finally:
        _request_id.reset(token)

    response.headers[REQUEST_ID_HEADER] = request_id
    return response
