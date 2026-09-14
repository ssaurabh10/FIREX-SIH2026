"""
Health, Readiness and System Info API Endpoints
"""
from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.orm import Session
from app.storage.database import get_db, check_db_connection
from app.storage.models import Observation, Incident, IndustrialAsset
from app.core.config import settings
from app.core.cache import cache
from app.orchestration.lock import pipeline_lock
from datetime import datetime

router = APIRouter()

@router.get("/health")
def health_check():
    """
    Standard liveness endpoint returning service status, timestamp, and database connectivity.
    """
    db_status = check_db_connection()
    is_ok = db_status.get("status") in ("connected", "healthy")
    return {
        "status": "healthy" if is_ok else "degraded",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status
    }

@router.get("/health/readiness")
def readiness_check(response: Response, db: Session = Depends(get_db)):
    """
    Kubernetes / deployment readiness probe verifying database connectivity,
    schema readiness, and core asset availability.
    """
    db_status = check_db_connection()
    if db_status.get("status") not in ("connected", "healthy"):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "reason": "Database connection failed", "database": db_status}

    try:
        asset_count = db.query(IndustrialAsset).count()
        incident_count = db.query(Incident).count()
        return {
            "status": "ready",
            "database": "connected",
            "assets_registered": asset_count,
            "incidents_loaded": incident_count,
            "cache_entries": cache.size(),
            "pipeline_busy": pipeline_lock.is_locked()
        }
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "reason": str(e)}

@router.get("/status")
def system_status(db: Session = Depends(get_db)):
    """
    Detailed system metrics, cache statistics, and configuration summary.
    """
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENV,
        "ai_model": settings.AI_MODEL_NAME,
        "firms_configured": bool(settings.FIRMS_MAP_KEY),
        "openrouter_keys_count": len(settings.OPENROUTER_API_KEYS),
        "database": check_db_connection(),
        "hardening": {
            "rate_limiting": settings.RATE_LIMIT_ENABLED,
            "rate_limit_per_minute": settings.RATE_LIMIT_PER_MINUTE,
            "cache_enabled": settings.CACHE_ENABLED,
            "cache_size": cache.size(),
            "pipeline_locked": pipeline_lock.is_locked()
        }
    }
