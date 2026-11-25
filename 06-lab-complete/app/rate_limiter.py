"""
Sliding-window rate limiter backed by Redis sorted sets.

- Max RATE_LIMIT_PER_MINUTE requests per 60 seconds per API key
- Returns HTTP 429 with Retry-After header when exceeded
- State lives ONLY in Redis (shared by all workers/instances, survives restarts).
  If Redis is unreachable the request fails with 503 instead of silently
  falling back to per-process memory.
- Check + record is a single atomic Lua script, so concurrent workers cannot
  both slip past the limit.
"""
import hashlib
import logging
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

# KEYS[1] = rate-limit key
# ARGV[1] = now (seconds, float)  ARGV[2] = window seconds
# ARGV[3] = limit                 ARGV[4] = unique member id
# Returns {allowed (1/0), retry_after_seconds}
_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = math.ceil(tonumber(oldest[2]) + window - now)
    if retry < 1 then retry = 1 end
  end
  return {0, retry}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('EXPIRE', key, window + 5)
return {1, 0}
"""

_script = r.register_script(_SLIDING_WINDOW_LUA) if r is not None else None


def _redis_key(api_key: str) -> str:
    # Never store the raw API key in Redis key names.
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:32]
    return f"ratelimit:{digest}"


def check_rate_limit(key: str) -> None:
    """Enforce sliding-window rate limit for the given API key."""
    if _script is None:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")

    now = time.time()
    try:
        allowed, retry_after = _script(
            keys=[_redis_key(key)],
            args=[now, WINDOW_SECONDS, settings.rate_limit_per_minute,
                  f"{now}:{uuid.uuid4().hex}"],
        )
    except RedisError as exc:
        logger.error("rate_limit_redis_error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")

    if not int(allowed):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(int(retry_after))},
        )
