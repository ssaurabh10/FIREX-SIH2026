"""
Health, Readiness and System Info API Endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.storage.database import get_db, check_db_connection
from app.core.config import settings
from datetime import datetime

router = APIRouter()

@router.get("/health")
def health_check():
    """
    Standard health endpoint returning service status, timestamp, and database connectivity.
    """
    db_status = check_db_connection()
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status
    }

@router.get("/status")
def system_status(db: Session = Depends(get_db)):
    """
    Detailed system metrics and configuration summary.
    """
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENV,
        "ai_model": settings.AI_MODEL_NAME,
        "firms_configured": bool(settings.FIRMS_MAP_KEY),
        "openrouter_keys_count": len(settings.OPENROUTER_API_KEYS),
        "database": check_db_connection()
    }
