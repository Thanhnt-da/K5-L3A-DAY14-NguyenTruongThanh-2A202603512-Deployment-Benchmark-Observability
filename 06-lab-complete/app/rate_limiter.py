"""
Sliding-window rate limiter backed by Redis sorted sets.

- Max RATE_LIMIT_PER_MINUTE requests per 60 seconds per API key
- Returns HTTP 429 with Retry-After header when exceeded
- State persists in Redis across workers and restarts
"""
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def _check_in_memory(key: str, limit: int, now: float) -> None:
    window = _fallback_windows[key]
    cutoff = now - WINDOW_SECONDS
    while window and window[0] <= cutoff:
        window.popleft()

    if len(window) >= limit:
        retry_after = max(1, int(window[0] + WINDOW_SECONDS - now) + 1)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)


def check_rate_limit(key: str) -> None:
    """Enforce sliding-window rate limit for the given API key."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{key}"

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = pipe.execute()

            if count >= limit:
                oldest = r.zrange(redis_key, 0, 0, withscores=True)
                if oldest:
                    retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
                else:
                    retry_after = WINDOW_SECONDS
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()
            return
        except HTTPException:
            raise
        except RedisError as exc:
            logger.warning("redis_rate_limit_fallback: %s", exc)

    _check_in_memory(key, limit, now)
