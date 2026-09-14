"""
FIREX v2 Analysis & End-to-End Orchestration REST / SSE Router
Implements Section 23 & 25 of Blueprint:
- POST /analysis/run (and /api/analysis/run)
- GET /api/analysis/stream (and /api/trigger-sync-stream)
- GET /api/analysis/status
- GET /api/analysis/history
- POST /api/trigger-sync
"""
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.storage.models import AnalysisRun, Observation
from app.orchestration.lock import pipeline_lock, AnalysisAlreadyRunningError
from app.orchestration.events import event_broadcaster
from app.orchestration.pipeline import execute_analysis_pipeline

router = APIRouter(prefix="/api/analysis", tags=["analysis"])
# Top-level alias router for exact blueprint matching: POST /analysis/run
top_router = APIRouter(tags=["analysis-root"])

class AnalysisRunRequest(BaseModel):
    firms_csv: Optional[str] = None
    file_path: Optional[str] = None
    force_reinvestigate: bool = False
    max_ai_targets: int = 5
    export_to_dashboard: bool = True


@router.get("/status")
def get_analysis_status(db: Session = Depends(get_db)):
    """Returns current pipeline execution status and metadata on the latest run."""
    lock_info = pipeline_lock.get_status()
    latest_run = db.query(AnalysisRun).order_by(AnalysisRun.started_at.desc()).first()

    return {
        "is_running": lock_info["is_running"],
        "active_run_id": lock_info["active_run_id"],
        "elapsed_seconds": lock_info["elapsed_seconds"],
        "latest_run": {
            "id": latest_run.id,
            "status": latest_run.status,
            "started_at": latest_run.started_at.isoformat() if latest_run.started_at else None,
            "completed_at": latest_run.completed_at.isoformat() if latest_run.completed_at else None,
            "duration_seconds": latest_run.duration_seconds,
            "new_observations": latest_run.new_observations_count,
            "incidents_updated": latest_run.incidents_updated_count,
            "new_incidents": latest_run.new_incidents_count,
            "investigations_count": latest_run.investigations_count,
            "alerts_count": latest_run.alerts_count,
            "summary": latest_run.summary_json,
            "error_message": latest_run.error_message
        } if latest_run else None
    }


@router.get("/history")
def get_analysis_history(limit: int = 15, db: Session = Depends(get_db)):
    """Returns recent analysis runs history."""
    runs = db.query(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_seconds": r.duration_seconds,
            "new_observations": r.new_observations_count,
            "incidents_updated": r.incidents_updated_count,
            "new_incidents": r.new_incidents_count,
            "investigations_count": r.investigations_count,
            "alerts_count": r.alerts_count,
            "summary": r.summary_json
        }
        for r in runs
    ]


@router.get("/stream")
async def stream_analysis_events(request: Request):
    """
    Subscribes to live Server-Sent Events (SSE) from ongoing analysis runs.
    Wire format: text/event-stream
    """
    async def sse_event_generator():
        queue = event_broadcaster.subscribe()
        try:
            # Send initial ping event
            yield f"event: ping\ndata: {json.dumps({'message': 'Connected to FIREX live mission telemetry stream', 'lock': pipeline_lock.get_status()})}\n\n"
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield msg
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": heartbeat\n\n"
        finally:
            event_broadcaster.unsubscribe(queue)

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/run")
def run_analysis_pipeline(
    req: Optional[AnalysisRunRequest] = None,
    stream: bool = Query(False, description="Stream SSE events directly"),
    db: Session = Depends(get_db)
):
    """
    Initiates an end-to-end analysis run.
    Guards against concurrent runs with HTTP 409 Conflict.
    """
    if pipeline_lock.is_locked():
        status = pipeline_lock.get_status()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ANALYSIS_ALREADY_RUNNING",
                "message": f"Analysis run {status['active_run_id']} is already in progress.",
                "active_run": status
            }
        )

    req_data = req or AnalysisRunRequest()

    if stream:
        # If user requests direct streaming on POST, run in background thread and return SSE stream
        async def direct_stream():
            queue = event_broadcaster.subscribe()
            # Launch execution in background worker thread
            asyncio.get_event_loop().run_in_executor(
                None,
                execute_analysis_pipeline,
                db,
                req_data.firms_csv,
                req_data.file_path,
                req_data.force_reinvestigate,
                req_data.max_ai_targets,
                req_data.export_to_dashboard
            )
            try:
                while True:
                    msg = await queue.get()
                    yield msg
                    if "analysis.completed" in msg or "analysis.failed" in msg:
                        break
            finally:
                event_broadcaster.unsubscribe(queue)

        return StreamingResponse(
            direct_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    try:
        summary = execute_analysis_pipeline(
            db=db,
            firms_csv=req_data.firms_csv,
            file_path=req_data.file_path,
            force_reinvestigate=req_data.force_reinvestigate,
            max_ai_targets=req_data.max_ai_targets,
            export_to_dashboard=req_data.export_to_dashboard
        )
        return summary
    except AnalysisAlreadyRunningError as e:
        raise HTTPException(
            status_code=409,
            detail={"error": "ANALYSIS_ALREADY_RUNNING", "message": str(e)}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "ANALYSIS_RUN_FAILED", "message": str(e)}
        )


# ---------------------------------------------------------------------------
# TOP-LEVEL BLUEPRINT & V1 COMPATIBILITY ROUTES
# ---------------------------------------------------------------------------
@top_router.post("/analysis/run")
def root_analysis_run(
    req: Optional[AnalysisRunRequest] = None,
    stream: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Blueprint Section 23 exact path: POST /analysis/run"""
    return run_analysis_pipeline(req=req, stream=stream, db=db)


@top_router.get("/api/trigger-sync-stream")
async def v1_trigger_sync_stream(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    v1 Dashboard compatibility endpoint.
    If idle, starts a pipeline run in a dedicated background worker thread with its own database session
    and streams real-time v1-formatted SSE events across all 5 analysis stages.
    """
    if not pipeline_lock.is_locked():
        def _bg_pipeline_worker():
            from app.storage.database import SessionLocal
            worker_db = SessionLocal()
            try:
                execute_analysis_pipeline(
                    db=worker_db,
                    firms_csv=None,
                    file_path=None,
                    force_reinvestigate=False,
                    max_ai_targets=5,
                    export_to_dashboard=True
                )
            except Exception as e:
                logger.error(f"[PipelineWorker] Error during sync stream execution: {e}", exc_info=True)
            finally:
                worker_db.close()

        import threading
        thread = threading.Thread(target=_bg_pipeline_worker, daemon=True, name="PipelineSyncWorker")
        thread.start()

    return await stream_analysis_events(request)


@top_router.post("/api/trigger-sync")
def v1_trigger_sync(db: Session = Depends(get_db)):
    """v1 Dashboard compatibility synchronous trigger."""
    return run_analysis_pipeline(req=None, stream=False, db=db)


@top_router.get("/api/history-stats")
def get_history_stats(db: Session = Depends(get_db)):
    """Returns persistent satellite overpass and run statistics for the console HUD widget."""
    total_runs = db.query(AnalysisRun).count()
    total_hotspots = db.query(Observation).count()
    latest_run = db.query(AnalysisRun).order_by(AnalysisRun.started_at.desc()).first()
    now = datetime.utcnow()
    ist_now = now + timedelta(hours=5, minutes=30)
    current_pass = "DAY" if 6 <= ist_now.hour < 18 else "NIGHT"
    return {
        "total_runs": total_runs,
        "total_hotspots": total_hotspots,
        "unique_dates": 365,
        "last_run": latest_run.started_at.strftime("%Y-%m-%d %H:%M:%S") if (latest_run and latest_run.started_at) else "Never",
        "current_pass": current_pass,
        "cadence": "2x Daily (12-Hour Cadence)",
        "overpass_times": "14:00 IST (Day) / 02:30 IST (Night)"
    }


@top_router.get("/api/console/feed")
def get_console_feed(db: Session = Depends(get_db)):
    """
    Returns real-time active sovereign incidents and ambient FIRMS detections directly from the database.
    Eliminates reliance on static json files and synchronizes directly with DB state.
    """
    from app.orchestration.pipeline import generate_console_feed_data
    return generate_console_feed_data(db)


