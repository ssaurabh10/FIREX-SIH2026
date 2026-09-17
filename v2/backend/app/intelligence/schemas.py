"""
FIREX v2 Intelligence Schemas (Pydantic V2)
Strictly adheres to Section 16 & Section 35 of FIREX-SIH2026 Blueprint.
"""
from typing import List, Optional, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field

# Core PS-focused classification taxonomy
TaxonomyClass = Literal[
    "industrial_fire",
    "gas_flare",
    "wildfire",
    "agricultural_burning",
    "mining_related",
    "uncertain"
]

class AlternativeHypothesis(BaseModel):
    classification: TaxonomyClass = Field(
        ...,
        description="Secondary plausible hypothesis for the thermal anomaly"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Confidence percentage (0.0 to 100.0) for alternative hypothesis"
    )

class ImageQualityAssessment(BaseModel):
    # Spec 6.2 serialises image_quality.score as 92.0, a JSON float literal, so the
    # field is a float: an int field could not reproduce the spec's own example and
    # int() coercion in the provider floored any fractional score a model returned.
    score: float = Field(
        80.0,
        ge=0.0,
        le=100.0,
        description="Estimated optical image quality score (0.0-100.0)"
    )
    cloud_cover: str = Field(
        "low",
        description="Cloud cover level (low, medium, high, obscured)"
    )
    visibility: str = Field(
        "good",
        description="Optical ground visibility (good, moderate, poor)"
    )

class AIInvestigationReport(BaseModel):
    """
    Standard AI Output Schema matching Section 16 of Blueprint.
    """
    classification: TaxonomyClass = Field(
        ...,
        description="Primary classified thermal source category"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Confidence percentage (0.0 to 100.0) for primary classification"
    )
    alternative: AlternativeHypothesis = Field(
        ...,
        description="Competing hypothesis"
    )
    visual_evidence: List[str] = Field(
        default_factory=list,
        description="Observed spatial and visual features inside reticle rings"
    )
    contextual_evidence: List[str] = Field(
        default_factory=list,
        description="GIS, facility proximity, and 365-day historical baseline evidence"
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        description="Known limits, obscuration, resolution constraints, or ambiguities"
    )
    image_quality: ImageQualityAssessment = Field(
        default_factory=ImageQualityAssessment,
        description="Visual quality assessment of the satellite crop"
    )
    needs_reinvestigation: bool = Field(
        False,
        description="True if image was obscured or evidence was inconclusive"
    )
    reasoning_summary: str = Field(
        "",
        description="Concise human-readable explanation synthesizing visual and baseline findings"
    )
    reasoning_details: Optional[Any] = Field(
        None,
        description="Preserved chain-of-thought reasoning trace from reasoning models"
    )
    
    # Metadata
    model_used: Optional[str] = None
    key_used: Optional[str] = None
    prompt_version: Optional[str] = None
    investigated_at: datetime = Field(default_factory=datetime.utcnow)

class InvestigationRequest(BaseModel):
    incident_id: str
    custom_radius_meters: Optional[float] = Field(None, ge=100.0, le=10000.0)
    force_refresh: bool = False
    operator_notes: Optional[str] = None

class InvestigationResponse(BaseModel):
    incident_id: str
    investigation_id: str
    status: str
    report: AIInvestigationReport
