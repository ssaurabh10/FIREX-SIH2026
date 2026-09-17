"""
FIREX v2 Security & Authentication Utilities (Stage 10 Hardening)
Provides optional API Key authentication for sensitive operations,
allowing secure demonstration while keeping public dashboard reads unblocked.
"""
from fastapi import Request, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import settings
from app.core.logging import logger

api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)

def verify_api_key(request: Request) -> bool:
    """
    Validates API key if API_KEY_AUTH_ENABLED is True.
    If disabled (default for local demonstration), returns True immediately.
    """
    if not settings.API_KEY_AUTH_ENABLED:
        return True

    header_key = request.headers.get(settings.API_KEY_HEADER)
    if not header_key or header_key != settings.ADMIN_API_KEY:
        logger.warning(f"[Security] Unauthorized access attempt from {request.client.host if request.client else 'unknown'}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing sovereign API key. Provide valid header X-FIREX-KEY."
        )
    return True
