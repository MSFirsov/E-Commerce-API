from fastapi import Request

from app.core.config import get_settings
from app.core.errors import TooManyRequestsError
from app.core.redis import RedisClient

_settings = get_settings()

FIXED_WINDOW_SCRIPT = """
local hits = redis.call('INCR', KEYS[1])
if hits == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {hits, redis.call('TTL', KEYS[1])}
"""


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class RateLimit:
    def __init__(self, scope: str, times: int, seconds: int) -> None:
        self.scope = scope
        self.times = times
        self.seconds = seconds

    async def __call__(self, request: Request, redis: RedisClient) -> None:
        if not _settings.rate_limit_enabled:
            return

        key = f"ratelimit:{self.scope}:{client_ip(request)}"
        script = redis.register_script(FIXED_WINDOW_SCRIPT)
        hits, ttl = await script(keys=[key], args=[self.seconds])

        if hits > self.times:
            raise TooManyRequestsError(
                f"Rate limit is {self.times} requests per {self.seconds} seconds",
                retry_after=max(ttl, 1),
            )
