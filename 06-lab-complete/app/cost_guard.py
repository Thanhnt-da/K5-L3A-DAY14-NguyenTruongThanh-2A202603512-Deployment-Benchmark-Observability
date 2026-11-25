"""
Cost guard backed by Redis.

- Accumulates LLM token cost in Redis
- Returns HTTP 402 Payment Required when DAILY_BUDGET_USD (or MONTHLY_BUDGET_USD) is exceeded
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

_fallback_daily: dict[str, float] = {}
_fallback_monthly: dict[str, float] = {}


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def _get_spend(redis_key: str, fallback_store: dict[str, float]) -> float:
    if r is not None:
        try:
            val = r.get(redis_key)
            return float(val) if val is not None else 0.0
        except RedisError as exc:
            logger.warning("redis_cost_read_fallback: %s", exc)
    return fallback_store.get(redis_key, 0.0)


def check_budget() -> None:
    """Check daily (and optional monthly) budget before calling LLM. Raise 402 if exceeded."""
    d_key = _daily_key()
    daily_spend = _get_spend(d_key, _fallback_daily)
    if daily_spend >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="Daily budget exceeded",
        )

    if settings.monthly_budget_usd is not None:
        m_key = _monthly_key()
        monthly_spend = _get_spend(m_key, _fallback_monthly)
        if monthly_spend >= settings.monthly_budget_usd:
            raise HTTPException(
                status_code=402,
                detail="Monthly budget exceeded",
            )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Record request cost into Redis after LLM call and return request cost in USD."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    d_key = _daily_key()
    m_key = _monthly_key()

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(d_key, cost)
            pipe.expire(d_key, 2 * 86400)
            pipe.incrbyfloat(m_key, cost)
            pipe.expire(m_key, 35 * 86400)
            pipe.execute()
            return cost
        except RedisError as exc:
            logger.warning("redis_cost_write_fallback: %s", exc)

    _fallback_daily[d_key] = _fallback_daily.get(d_key, 0.0) + cost
    _fallback_monthly[m_key] = _fallback_monthly.get(m_key, 0.0) + cost
    return cost
