"""
API Key authentication.

- Client sends header: X-API-Key: <key>
- Must match AGENT_API_KEY environment variable
- Missing or invalid key -> HTTP 401
"""
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """FastAPI dependency to verify X-API-Key header."""
    expected = settings.agent_api_key
    if not api_key or not expected or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )
    return api_key
