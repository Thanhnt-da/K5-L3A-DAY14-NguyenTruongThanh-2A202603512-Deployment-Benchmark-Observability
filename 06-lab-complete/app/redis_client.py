"""
Shared Redis client for rate limiter and cost guard.

- Reads REDIS_URL from config
- Does NOT ping Redis on import so the app starts cleanly even if Redis is unavailable
- redis_healthy() is used by GET /ready
"""
from typing import Optional

import redis

from app.config import settings

r: Optional[redis.Redis] = None
if settings.redis_url:
    r = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )


def redis_healthy() -> bool:
    """Return True if Redis responds to PING, False otherwise."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False
