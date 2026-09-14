"""
FIREX v2 FastAPI Main Application Entrypoint
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import logger
from app.storage.database import engine, Base
from app.api import health, observations, industries, incidents, history, selection, imagery, investigation, severity, alerts, analysis

# Auto-create tables on startup (in development / SQLite fallback)
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized successfully.")
except Exception as e:
    logger.warning(f"Note on initial schema setup: {e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-Enabled Geospatial Industrial Fire & Persistent Thermal Source Intelligence Platform",
    docs_url="/docs",
    redoc_url="/redoc"
)

from app.core.ratelimit import RateLimitMiddleware
from fastapi.responses import JSONResponse
from fastapi import Request

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting Middleware (Stage 10 Hardening)
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)

# Global Unhandled Exception Error Boundary
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[GlobalBoundary] Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred within the sovereign processing engine.",
            "path": request.url.path
        }
    )

# Root route
@app.get("/")
def root():
    return {
        "message": "Welcome to FIREX v2 - Space-Borne Satellite AI Industrial Thermal Intelligence Platform",
        "docs": "/docs",
        "health": "/health",
        "api": "/api",
        "observations": "/observations",
        "industries": "/industries",
        "incidents": "/incidents",
        "history": "/history"
    }

# Register routers
app.include_router(health.router, tags=["Health"])
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(observations.router, tags=["Observations"])
app.include_router(observations.router, prefix="/api", tags=["Observations"])
app.include_router(industries.router, tags=["Industry Intelligence"])
app.include_router(industries.router, prefix="/api", tags=["Industry Intelligence"])
app.include_router(incidents.router, tags=["Incidents"])
app.include_router(incidents.router, prefix="/api", tags=["Incidents"])
app.include_router(history.router, tags=["Historical Behavior"])
app.include_router(history.router, prefix="/api", tags=["Historical Behavior"])
app.include_router(selection.router, tags=["Selection Engine"])
app.include_router(selection.router, prefix="/api", tags=["Selection Engine"])
app.include_router(imagery.router, tags=["Visual Context & Imagery"])
app.include_router(imagery.router, prefix="/api", tags=["Visual Context & Imagery"])
app.include_router(investigation.router, tags=["AI Investigation"])
app.include_router(investigation.router, prefix="/api", tags=["AI Investigation"])
app.include_router(severity.router, tags=["Severity Engine"])
app.include_router(severity.router, prefix="/api", tags=["Severity Engine"])
app.include_router(alerts.router, tags=["Alert Engine"])
app.include_router(alerts.router, prefix="/api", tags=["Alert Engine"])
app.include_router(analysis.router, tags=["Analysis & Orchestration"])
app.include_router(analysis.top_router, tags=["Analysis & Orchestration"])

# Static files for UI and Crops
import os
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
V2_CROPS_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "imagery_cache"))
V1_CROPS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "v1", "pipeline", "03_imagery", "crops"))

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.storage.database import get_db
from app.storage.models import Incident
from app.imagery.service import get_or_create_incident_imagery

@app.get("/crops/{incident_id}/{filename}")
def serve_crop_image(incident_id: str, filename: str, db: Session = Depends(get_db)):
    # 1. Check v2 imagery cache
    file_path = os.path.abspath(os.path.join(V2_CROPS_DIR, incident_id, filename))
    if file_path.startswith(V2_CROPS_DIR) and os.path.exists(file_path):
        media_type = "application/json" if filename.endswith(".json") else "image/jpeg"
        return FileResponse(file_path, media_type=media_type)

    # 2. Check v1 crops dir
    v1_path = os.path.abspath(os.path.join(V1_CROPS_DIR, incident_id, filename))
    if v1_path.startswith(V1_CROPS_DIR) and os.path.exists(v1_path):
        media_type = "application/json" if filename.endswith(".json") else "image/jpeg"
        return FileResponse(v1_path, media_type=media_type)

    # 3. Dynamic On-Demand Synthesis: if incident exists in DB, render high-res tiles now!
    inc = db.query(Incident).filter((Incident.id == incident_id) | (Incident.incident_code == incident_id)).first()
    if inc:
        try:
            get_or_create_incident_imagery(inc.id, db)
            if os.path.exists(file_path):
                return FileResponse(file_path, media_type="image/jpeg")
        except Exception as e:
            logger.error(f"[Crops] Dynamic rendering failed for {incident_id}: {e}")

    raise HTTPException(status_code=404, detail=f"Satellite crop for {incident_id} not found")

if os.path.exists(FRONTEND_DIR):
    app.mount("/console", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

@app.on_event("startup")
async def on_startup():
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION} in {settings.ENV} mode")

@app.on_event("shutdown")
async def on_shutdown():
    logger.info(f"Shutting down {settings.PROJECT_NAME}")

