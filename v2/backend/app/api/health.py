"""
Health, Readiness and System Info API Endpoints
"""
import ctypes
import sys
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.orm import Session
from app.storage.database import get_db, check_db_connection
from app.storage.models import Observation, Incident, IndustrialAsset
from app.core.config import settings
from app.core.cache import cache
from app.orchestration.lock import pipeline_lock
from datetime import datetime

try:  # POSIX only; `resource` does not exist on Windows, which is where this app runs
    import resource as _resource
except ImportError:
    _resource = None

router = APIRouter()

def _peak_rss_bytes() -> Optional[int]:
    """
    Peak resident set size of this process in bytes, using the standard library only.

    F-057: the spec's /health row promises "database status, memory metrics", but no memory
    figure was exposed anywhere in the API. ru_maxrss is the stdlib's RSS number, except its
    unit is platform-dependent -- getrusage(2) reports it in KiB on Linux but in bytes on
    macOS -- so it is normalised to bytes here and callers convert. The `resource` module
    is absent on Windows altogether, so the Windows path reads the same quantity
    (PeakWorkingSetSize) through psapi; no psutil, which is not a project dependency.
    """
    if _resource is not None:
        ru_maxrss = int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
        # Only the Linux-style KiB value needs scaling; Darwin already reports bytes.
        return ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024

    try:
        from ctypes import wintypes

        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        try:
            _get_process_memory_info = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        except OSError:  # psapi is not loadable on older/rooted Windows hosts
            _get_process_memory_info = ctypes.WinDLL("kernel32", use_last_error=True).K32GetProcessMemoryInfo
        _get_process_memory_info.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_ProcessMemoryCounters), wintypes.DWORD
        ]
        _get_process_memory_info.restype = wintypes.BOOL

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not _get_process_memory_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PeakWorkingSetSize)
    except Exception:
        return None

def _memory_metrics() -> Dict[str, Any]:
    """
    Memory figures for the liveness body. The unit is part of each key name so a consumer
    never has to know which platform produced the number.
    """
    peak_bytes = _peak_rss_bytes()
    if peak_bytes is None:
        return {"status": "unavailable"}
    return {
        "peak_rss_bytes": peak_bytes,
        "peak_rss_mb": round(peak_bytes / (1024 * 1024), 2),
        "source": "resource.getrusage(RUSAGE_SELF).ru_maxrss" if _resource is not None
                  else "psapi.GetProcessMemoryInfo(PeakWorkingSetSize)"
    }

@router.get("/health")
def health_check():
    """
    Standard liveness endpoint returning service status, timestamp, database connectivity,
    and process memory metrics.
    """
    db_status = check_db_connection()
    is_ok = db_status.get("status") in ("connected", "healthy")
    return {
        "status": "healthy" if is_ok else "degraded",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status,
        "memory": _memory_metrics()
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
