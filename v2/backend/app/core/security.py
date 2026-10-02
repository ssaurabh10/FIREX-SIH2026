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


import os
import tempfile

def validate_fixture_path(file_path: str) -> str:
    """
    Validates and contains caller-provided fixture file paths (Finding H-5).
    Ensures the path points to an existing CSV file within permitted project roots
    and explicitly blocks path traversal, sensitive filenames (.env, .db, keys),
    and system files.
    """
    if not file_path or not isinstance(file_path, str):
        raise ValueError("Invalid file path: path must be a non-empty string.")

    if "\0" in file_path:
        raise ValueError("Invalid file path: null byte detected.")

    real_path = os.path.realpath(os.path.abspath(file_path))

    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        raise ValueError(f"Fixture file does not exist or is not a regular file: {file_path}")

    base_name = os.path.basename(real_path).lower()
    if (
        base_name.startswith(".env")
        or base_name.endswith((".db", ".sqlite", ".sqlite3", ".key", ".pem", ".log"))
        or "passwd" in base_name
        or "shadow" in base_name
        or "win.ini" in base_name
        or "secret" in base_name
    ):
        raise ValueError(f"Access to sensitive file denied: {base_name}")

    if not real_path.lower().endswith(".csv"):
        raise ValueError(f"Unauthorized file type: only .csv fixture files are permitted ({file_path}).")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(os.path.dirname(current_dir))  # backend
    v2_dir = os.path.dirname(backend_dir)
    workspace_dir = os.path.dirname(v2_dir)
    temp_dir = os.path.realpath(tempfile.gettempdir())

    allowed_roots = [
        os.path.realpath(backend_dir),
        os.path.realpath(v2_dir),
        os.path.realpath(workspace_dir),
        temp_dir,
    ]
    if hasattr(settings, "ALLOWED_FIXTURE_DIRS") and settings.ALLOWED_FIXTURE_DIRS:
        for d in settings.ALLOWED_FIXTURE_DIRS:
            allowed_roots.append(os.path.realpath(d))

    contained = False
    for root in allowed_roots:
        try:
            if os.path.commonpath([real_path, root]) == root:
                contained = True
                break
        except (ValueError, Exception):
            continue

    if not contained:
        raise ValueError(
            f"Path containment violation: {file_path} is outside allowed fixture roots."
        )

    return real_path


def escape_like_pattern(pattern: str) -> str:
    """
    Escapes SQL LIKE / ILIKE wildcard characters (% and _) to prevent
    unintended wildcard matching and full table scans (Finding L-1).
    """
    if not pattern:
        return ""
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

