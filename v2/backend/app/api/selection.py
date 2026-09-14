"""
FIREX v2 Selection Engine API Router
Endpoints for candidate ranking and priority evaluation.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.selection.scoring import compute_investigation_priority
from app.selection.engine import select_investigation_candidates, evaluate_incident_selection

router = APIRouter(prefix="/selection", tags=["Selection Engine"])

class ScoreEvaluationRequest(BaseModel):
    frp_mw: float
    confidence_raw: Optional[str] = "nominal"
    instrument: Optional[str] = "VIIRS"
    confidence_score: Optional[float] = None
    persistence_score: float = 0.0
    anomaly_score: float = 0.0
    has_history: bool = True
    historical_median_frp: Optional[float] = None

@router.get("/candidates", summary="Get prioritized incident candidates for investigation")
def get_candidates(
    min_priority: float = Query(35.0, description="Minimum priority score threshold (0-100)"),
    limit: int = Query(25, description="Maximum number of candidates to return"),
    status: Optional[str] = Query("ACTIVE", description="Filter by incident status"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    return select_investigation_candidates(
        db=db,
        min_priority=min_priority,
        limit=limit,
        status=status
    )

@router.get("/evaluate/{incident_id}", summary="Evaluate investigation priority for an existing incident")
def evaluate_incident(
    incident_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    res = evaluate_incident_selection(incident_id, db)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@router.post("/score", summary="Interactive calculation of investigation priority formula")
def evaluate_score(req: ScoreEvaluationRequest) -> Dict[str, Any]:
    return compute_investigation_priority(
        frp_mw=req.frp_mw,
        confidence_raw=req.confidence_raw,
        instrument=req.instrument,
        confidence_score=req.confidence_score,
        persistence_score=req.persistence_score,
        anomaly_score=req.anomaly_score,
        has_history=req.has_history,
        historical_median_frp=req.historical_median_frp
    )
