"""
Cost guard backed by Redis.

- Accumulates LLM token cost in Redis (shared by all workers/instances)
- Returns HTTP 402 Payment Required when DAILY_BUDGET_USD (or MONTHLY_BUDGET_USD) is exceeded
- If Redis is unreachable the request fails with 503: spend is never tracked
  in per-process memory, so the budget cannot be bypassed by scaling out.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

# USD / 1K tokens (gpt-4o-mini reference pricing)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def _unavailable(exc: Exception) -> HTTPException:
    logger.error("cost_guard_redis_error: %s", type(exc).__name__)
    return HTTPException(status_code=503, detail="Cost guard unavailable")


def check_budget() -> None:
    """Check daily (and optional monthly) budget before calling LLM. Raise 402 if exceeded."""
    if r is None:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    try:
        daily_raw, monthly_raw = r.mget(_daily_key(), _monthly_key())
    except RedisError as exc:
        raise _unavailable(exc)

    if float(daily_raw or 0.0) >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")

    if (settings.monthly_budget_usd is not None
            and float(monthly_raw or 0.0) >= settings.monthly_budget_usd):
        raise HTTPException(status_code=402, detail="Monthly budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Record request cost into Redis after LLM call and return request cost in USD."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    if r is None:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    d_key, m_key = _daily_key(), _monthly_key()
    try:
        pipe = r.pipeline()  # MULTI/EXEC transaction by default
        pipe.incrbyfloat(d_key, cost)
        pipe.expire(d_key, 2 * 86400)
        pipe.incrbyfloat(m_key, cost)
        pipe.expire(m_key, 35 * 86400)
        pipe.execute()
    except RedisError as exc:
        raise _unavailable(exc)
    return cost
