"""
FIREX v2 Intelligence Evidence Synthesizer
Prepares multimodal evidence payloads (base64 image, baseline metrics, GIS spatial context).
"""
import os
import base64
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

def encode_satellite_image(image_path: str) -> str:
    """
    Reads a local optical satellite crop and returns a base64 Data URI.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Satellite crop image not found at: {image_path}")
    
    with open(image_path, "rb") as f:
        data = f.read()
        if len(data) == 0:
            raise ValueError(f"Satellite crop file is empty: {image_path}")
        b64_str = base64.b64encode(data).decode("utf-8")
        
    return f"data:image/jpeg;base64,{b64_str}"

def extract_evidence_summary(package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts high-level statistical evidence signals to assist in verification and explainability.
    """
    inc = package.get("incident", {})
    gis = package.get("gis_context", {})
    hist = package.get("historical_features", {})

    frp = inc.get("max_frp_mw", 0.0)
    p95_ceiling = hist.get("p95_frp_mw", 0.0)
    median_frp = hist.get("median_frp_mw", 0.0)

    p95_ratio = (frp / p95_ceiling) if p95_ceiling > 0 else None
    median_ratio = (frp / median_frp) if median_frp > 0 else None

    return {
        "incident_code": inc.get("incident_code"),
        "observed_frp_mw": frp,
        "historical_median_mw": median_frp,
        "historical_p95_ceiling_mw": p95_ceiling,
        "frp_to_p95_ratio": round(p95_ratio, 2) if p95_ratio else None,
        "frp_to_median_ratio": round(median_ratio, 2) if median_ratio else None,
        "nearest_facility": gis.get("facility_name"),
        "facility_type": gis.get("facility_type"),
        "facility_distance_m": gis.get("facility_distance_m"),
        "is_inside_facility": gis.get("is_inside_facility", False),
        "is_persistent": hist.get("is_persistent", False),
        "history_reliability": hist.get("history_reliability_label", "NO_HISTORY")
    }
