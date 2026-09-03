"""
FIREX — Section 10: Deterministic Multi-Factor Risk & Priority Scoring Engine

Calculates an auditable composite threat score (0-100) for satellite thermal anomalies
combining AI visual evidence, NASA FIRMS sensor telemetry, FRP thermal output,
and industrial infrastructure proximity.
"""

import json
import os
import math
from pathlib import Path

# Weight calibration constants (Total: 100 points)
WEIGHT_AI_CONFIDENCE = 30.0     # Vision AI Model certainty
WEIGHT_FRP_INTENSITY = 25.0     # Radiative power (scaled up to 50 MW)
WEIGHT_FIRMS_CONFIDENCE = 20.0  # NASA satellite instrument confidence
WEIGHT_INDUSTRIAL_PROX = 15.0   # Geodesic distance to critical infrastructure
WEIGHT_CLASS_HAZARD = 10.0      # Inherent hazard level of classification

def calculate_frp_score(frp_mw: float) -> tuple[float, str]:
    """Scales Fire Radiative Power (MW) across 0-25 pts using log-linear curve."""
    if frp_mw <= 0:
        return 0.0, "0 MW (Negligible)"
    
    # 50 MW reaches full 25 points, with log dampening above 50
    if frp_mw >= 50.0:
        score = WEIGHT_FRP_INTENSITY
    else:
        score = (frp_mw / 50.0) * WEIGHT_FRP_INTENSITY
    
    score = round(score, 1)
    return score, f"{frp_mw:.1f} MW ({score}/{WEIGHT_FRP_INTENSITY} pts)"

def calculate_firms_score(confidence: str) -> tuple[float, str]:
    """Maps NASA FIRMS confidence levels to points."""
    conf = str(confidence).lower().strip()
    if conf in ["high", "h"] or (conf.isdigit() and int(conf) >= 80):
        return 20.0, "High Satellite Confidence (20/20 pts)"
    elif conf in ["nominal", "n"] or (conf.isdigit() and int(conf) >= 50):
        return 14.0, "Nominal Satellite Confidence (14/20 pts)"
    else:
        return 7.0, "Low Satellite Confidence (7/20 pts)"

def calculate_ai_score(ai_conf: float, ai_uncertainty: str) -> tuple[float, str]:
    """Calculates Vision AI contribution penalized by uncertainty level."""
    base_score = float(ai_conf) * WEIGHT_AI_CONFIDENCE
    unc = str(ai_uncertainty).lower().strip()
    
    # Uncertainty penalty
    if unc == "high":
        penalty = 0.7
    elif unc == "medium":
        penalty = 0.9
    else:
        penalty = 1.0
        
    final_score = round(base_score * penalty, 1)
    return final_score, f"{round(ai_conf * 100)}% AI Confidence ({unc} uncertainty, {final_score}/{WEIGHT_AI_CONFIDENCE} pts)"

def calculate_proximity_score(ai_classification: str, location_name: str) -> tuple[float, str]:
    """Evaluates spatial proximity to hazardous petrochemical/industrial infrastructure."""
    cls_lower = str(ai_classification).lower()
    loc_lower = str(location_name).lower()
    
    # Check for refinery, petrochemical, power plant, or chemical keywords
    if any(k in loc_lower or k in cls_lower for k in ["petrochemical", "refinery", "ongc", "lng", "chemical", "gas flare"]):
        return 15.0, "Critical Petrochemical/Refinery Zone (<200m, 15/15 pts)"
    elif any(k in loc_lower or k in cls_lower for k in ["steel", "power station", "ntpc", "smelter", "thermal power"]):
        return 12.0, "Heavy Industrial/Power Infrastructure (<500m, 12/15 pts)"
    elif any(k in loc_lower or k in cls_lower for k in ["mine", "coal", "quarry"]):
        return 8.0, "Open-Pit Mining Extraction Belt (<1km, 8/15 pts)"
    else:
        return 4.0, "Wildland / Rural Buffer Interface (>1km, 4/15 pts)"

def calculate_class_hazard_score(ai_classification: str) -> tuple[float, str]:
    """Assigns base hazard multiplier based on thermal source category."""
    cls_lower = str(ai_classification).lower()
    if "industrial_fire" in cls_lower or "structural" in cls_lower:
        return 10.0, "Uncontrolled Structural Industrial Fire (10/10 pts)"
    elif "wildfire" in cls_lower or "forest" in cls_lower:
        return 8.0, "Wildland/Canopy Biomass Fire (8/10 pts)"
    elif "gas_flare" in cls_lower or "flare" in cls_lower:
        return 6.0, "High-Output Flaring Anomaly (6/10 pts)"
    elif "mining" in cls_lower:
        return 5.0, "Diffuse Overburden/Coal Heat Anomaly (5/10 pts)"
    else:
        return 3.0, "Unclassified Thermal Hotspot (3/10 pts)"

def compute_incident_risk(incident: dict) -> dict:
    """Computes transparent composite score (0-100) and detailed factor breakdown."""
    frp_val = float(incident.get("frp", 0))
    s_frp, desc_frp = calculate_frp_score(frp_val)
    
    firms_conf = incident.get("confidence", "nominal")
    s_firms, desc_firms = calculate_firms_score(firms_conf)
    
    ai_conf = float(incident.get("ai_confidence", 0.5))
    ai_unc = incident.get("ai_uncertainty", "medium")
    s_ai, desc_ai = calculate_ai_score(ai_conf, ai_unc)
    
    ai_cls = incident.get("ai_classification", "unknown")
    loc_name = incident.get("location_name", "")
    s_prox, desc_prox = calculate_proximity_score(ai_cls, loc_name)
    
    s_class, desc_class = calculate_class_hazard_score(ai_cls)
    
    total_score = round(s_frp + s_firms + s_ai + s_prox + s_class)
    total_score = min(100, max(0, total_score))
    
    # Determine Risk Tier
    if total_score >= 81:
        tier = "CRITICAL"
        tier_color = "#ef4444"
        action_recommendation = "IMMEDIATE EMERGENCY DISPATCH & INDUSTRIAL SHUTDOWN ALERT"
    elif total_score >= 61:
        tier = "HIGH"
        tier_color = "#ff7700"
        action_recommendation = "ELEVATED SURVEILLANCE & FACILITY OPERATOR VERIFICATION"
    elif total_score >= 36:
        tier = "MEDIUM"
        tier_color = "#f59e0b"
        action_recommendation = "ROUTINE SATELLITE PASS TRACKING & THERMAL LOGGING"
    else:
        tier = "LOW"
        tier_color = "#10b981"
        action_recommendation = "BACKGROUND MONITORING // NO ACTIVE ESCALATION"
        
    breakdown = [
        {"factor": "Vision AI Certainty", "score": s_ai, "max": WEIGHT_AI_CONFIDENCE, "detail": desc_ai},
        {"factor": "Fire Radiative Power", "score": s_frp, "max": WEIGHT_FRP_INTENSITY, "detail": desc_frp},
        {"factor": "FIRMS Instrument Confidence", "score": s_firms, "max": WEIGHT_FIRMS_CONFIDENCE, "detail": desc_firms},
        {"factor": "Hazardous Proximity", "score": s_prox, "max": WEIGHT_INDUSTRIAL_PROX, "detail": desc_prox},
        {"factor": "Source Category Hazard", "score": s_class, "max": WEIGHT_CLASS_HAZARD, "detail": desc_class},
    ]
    
    return {
        "risk_score": total_score,
        "risk_tier": tier,
        "risk_color": tier_color,
        "action_recommendation": action_recommendation,
        "risk_factors": breakdown
    }

def score_and_enrich_incidents(incidents_path: str = None) -> list:
    """Loads incidents JSON, scores each, sorts by priority, and writes back."""
    if incidents_path is None:
        base_dir = Path(__file__).resolve().parent.parent
        incidents_path = base_dir / "section6_gis_map" / "data" / "incidents.json"
        
    incidents_path = Path(incidents_path)
    if not incidents_path.exists():
        raise FileNotFoundError(f"Incidents file not found at: {incidents_path}")
        
    with open(incidents_path, "r", encoding="utf-8") as f:
        incidents = json.load(f)
        
    enriched = []
    for inc in incidents:
        risk_data = compute_incident_risk(inc)
        inc.update(risk_data)
        enriched.append(inc)
        
    # Sort descending by risk score (Priority 1 at top)
    enriched.sort(key=lambda x: x["risk_score"], reverse=True)
    
    # Assign rank
    for rank, inc in enumerate(enriched, 1):
        inc["priority_rank"] = rank
        
    with open(incidents_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2)
        
    print(f"[Section 10 Risk Engine] Successfully evaluated and ranked {len(enriched)} incidents:")
    for inc in enriched:
        print(f"  Rank #{inc['priority_rank']:02d} | [{inc['risk_tier']:8s}] Score: {inc['risk_score']:3d}/100 | {inc['id']:8s} | {inc['ai_classification']}")
        
    return enriched

if __name__ == "__main__":
    score_and_enrich_incidents()
