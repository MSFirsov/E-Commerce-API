from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from app.core.config import get_settings

_settings = get_settings()

redis_client: Redis = Redis.from_url(
    _settings.redis_url,
    decode_responses=True,
    health_check_interval=30,
)


async def get_redis() -> Redis:
    return redis_client


RedisClient = Annotated[Redis, Depends(get_redis)]
