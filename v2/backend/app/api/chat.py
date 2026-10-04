"""
FIREX v2 AI Tactical Copilot API Endpoints (Step 2)
Provides intelligent mission chat, ground-truth retrieval, telemetry analysis, and map action dispatch.
"""
import os
import re
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.storage.models import Incident
from app.core.config import settings
from app.intelligence.db_grounding import execute_tool_grounding, get_incident_dossier_tool, search_facility_assets_tool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["AI Copilot"])

# --- Request / Response Schemas ---

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []

class ChatAction(BaseModel):
    type: str  # 'select_incident', 'fly_to', 'set_filter', 'set_basemap'
    payload: Dict[str, Any]

class ChatResponse(BaseModel):
    reply: str
    actions: List[Dict[str, Any]] = []
    telemetry: Dict[str, Any] = {}
    status: str = "ok"


# --- Ground-Truth Retrieval Utilities ---

def get_live_telemetry_snapshot(db: Optional[Session] = None) -> Dict[str, Any]:
    """Reads active incidents from DB or incidents.json to supply ground truth context."""
    incidents = []
    # 1. Try DB
    if db:
        try:
            db_cases = db.query(Incident).all()
            if db_cases:
                for c in db_cases:
                    incidents.append({
                        "id": c.id,
                        "location": getattr(c, "place_name", "") or getattr(c, "site_name", "") or f"{c.latitude:.3f}, {c.longitude:.3f}",
                        "lat": c.latitude,
                        "lon": c.longitude,
                        "frp": float(c.max_frp or c.frp or 0),
                        "classification": str(getattr(c, "classification", "") or "UNKNOWN"),
                        "pattern": str(getattr(c, "pattern", "") or "NORMAL"),
                        "state": getattr(c, "state_name", "") or "India"
                    })
        except Exception as e:
            logger.debug(f"[ChatTelemetry] DB query fallback: {e}")

    # 2. Try JSON file fallback
    if not incidents:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        json_path = os.path.join(base_dir, "data", "incidents.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for it in raw:
                    incidents.append({
                        "id": it.get("id", ""),
                        "location": it.get("location", it.get("place", "India")),
                        "lat": float(it.get("lat", it.get("latitude", 0))),
                        "lon": float(it.get("lon", it.get("longitude", 0))),
                        "frp": float(it.get("frp", 0) or 0),
                        "classification": str(it.get("classification", "UNKNOWN")),
                        "pattern": str(it.get("pattern", "NORMAL")),
                        "state": it.get("state", "India")
                    })
            except Exception as e:
                logger.warning(f"[ChatTelemetry] Failed to load incidents.json: {e}")

    surges = [i for i in incidents if i["pattern"] == "CRITICAL_SURGE"]
    top_by_frp = sorted(incidents, key=lambda x: x["frp"], reverse=True)[:6]

    return {
        "total_count": len(incidents),
        "surge_count": len(surges),
        "top_incidents": top_by_frp,
        "all_incidents": incidents
    }


def find_matching_incident(query: str, incidents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Identifies if the query targets a specific incident ID, city, or coordinate."""
    q = query.lower()

    # Match ID pattern like #0640ce6d or 0640ce6d
    id_match = re.search(r"#?([a-f0-9]{8})", q)
    if id_match:
        target_prefix = id_match.group(1)
        for inc in incidents:
            if inc["id"].lower().startswith(target_prefix):
                return inc

    # Match location keyword
    for inc in incidents:
        loc = inc.get("location", "").lower()
        if len(loc) > 3 and loc in q:
            return inc

    return None


@router.post("", response_model=ChatResponse, summary="Send message to FIREX AI Tactical Copilot")
def chat_endpoint(request: ChatRequest, db: Session = Depends(get_db)):
    """
    Step 2 Tactical Copilot Endpoint:
    - Ingests user prompt & multi-turn history
    - Enriches prompt with verified ground truth from active satellite telemetry
    - Performs LLM inference via OpenRouter with multi-model failover
    - Emits structured frontend map actions for instant dispatch
    """
    user_msg = request.message.strip()
    history = request.history or []

    telemetry = get_live_telemetry_snapshot(db)
    total_count = telemetry["total_count"]
    surge_count = telemetry["surge_count"]
    top_incidents = telemetry["top_incidents"]
    all_incidents = telemetry["all_incidents"]

    # Step 3: Autonomous Database Grounding & Tool Execution
    tool_grounding = execute_tool_grounding(user_msg)
    tool_context = tool_grounding.get("grounding_context", "")
    actions = tool_grounding.get("actions", [])

    # Prepare ground-truth context
    top_lines = []
    for it in top_incidents:
        top_lines.append(
            f"- #{it['id'][:8]} | {it['location']} | {it['classification']} | FRP: {it['frp']:.1f} MW | Pattern: {it['pattern']}"
        )
    top_summary = "\n".join(top_lines)

    system_prompt = f"""You are the FIREX Assistant — the dedicated AI helper for the FIREX Prototype (SIH 2026 Problem Statement 162: Autonomous Thermal Anomaly Detection & Monitoring Platform for India).

CORE PROTOTYPE DOMAIN KNOWLEDGE (Use these definitions in your answers):
1. What is FRP?
   - FRP stands for "Fire Radiative Power", measured in Megawatts (MW).
   - It quantifies the rate of radiant heat energy emitted by a thermal anomaly, detected by satellite infrared sensors (NASA VIIRS 375m band I4 at 3.9 μm).
   - In FIREX, FRP indicates fire intensity, fuel combustion rate, and is compared against the 365-day historical baseline to detect surges. Higher FRP = more intense fire.

2. What is the 365-Day Diurnal P95 Baseline?
   - For every 0.02° grid cell across India (~2.2 km), FIREX maintains a 365-day historical baseline of FRP percentiles (P50, P90, P95) separated by Day passes (~13:30 IST) and Night passes (~01:30 IST).
   - This eliminates false alarms on routine industrial sources (petroleum refineries in Jamnagar/Vadodara, steel plants like JSW Steel Vijayanagar, blast furnaces, brick kilns) because their normal heat stays within their historical P95 baseline.

3. What is a Critical Surge?
   - An anomaly where detected FRP exceeds 2.5 times (>2.5x) the location's historical 365-day P95 envelope. This flags uncontrolled wildfires, crop burn spikes, or industrial flaring blowouts.

4. Multi-Factor Priority Score (0–100):
   - Combines FRP anomaly surge ratio, proximity (<5 km) to monitored industrial assets/refineries, diurnal pass timing, and AI optical validation. High score = higher investigation priority.

5. Prototype Features & UI:
   - Live Map: Leaflet GIS displaying active thermal hotspots, basemap switcher (Canvas vs Satellite Imagery), and FRP filters (All, ≥2 MW, ≥5 MW).
   - Left Sidebar (Priority Incidents): Queue of ranked incidents with category badges (Agricultural, Industrial, Flare, Wildfire, Mining, Surge).
   - Tactical Dossier: Slide-out panel showing optical Sentinel-2 crop, thermal bounding box, diurnal FRP comparison graph, and nearest monitored industrial asset.

6. Current Live Satellite Pass Telemetry:
   - Active Qualified Hotspots: {total_count} across India
   - Critical Surge Hotspots: {surge_count}
   - Top Detected Hotspots Right Now:
{top_summary}

CONVERSATION GUIDELINES:
- Ground your answers around the FIREX prototype, its metrics (FRP in MW, P95 baseline, false alarm suppression), and live telemetry.
- When asked "what is frp?", explain clearly that it stands for Fire Radiative Power (MW), measures radiant heat energy, and is used in FIREX to measure fire intensity and detect surges against historical baselines.
- Keep answers clear, natural, and concise (2 to 4 sentences).
- Do not use robotic military prefixes (e.g. do not say "SITREP").
- Do not offer options or buttons to edit/filter the map.
"""

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-6:]:
        role = "user" if h.role == "user" else "assistant"
        messages.append({"role": role, "content": h.content})
    messages.append({"role": "user", "content": user_msg})

    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    candidate_models = [
        "dots-studio/dots-3-note-preview:free",
        "meta-llama/llama-3.1-8b-instruct",
        "meta-llama/llama-3.2-3b-instruct",
        "mistralai/mistral-small-24b-instruct-2501",
        "meta-llama/llama-3.2-1b-instruct"
    ]

    import requests

    reply_text = None
    last_err = None
    for model_name in candidate_models:
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://firex-mission.internal",
                    "X-Title": "FIREX Assistant"
                },
                json={
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.4,
                    "max_tokens": 250
                },
                timeout=12
            )
            if res.status_code == 200:
                data = res.json()
                choice = data.get("choices", [{}])[0]
                reply_text = choice.get("message", {}).get("content", "").strip()
                if reply_text:
                    logger.info(f"[ChatAPI] Model {model_name} answered successfully.")
                    break
            else:
                last_err = f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            last_err = str(e)
            logger.debug(f"[ChatAPI] Model {model_name} attempt error: {e}")

    if not reply_text:
        reply_text = f"API Error: Unable to retrieve response from AI model ({last_err}). Please check your connection or key."

    return ChatResponse(
        reply=reply_text,
        actions=[],
        telemetry={
            "total_targets": total_count,
            "surge_targets": surge_count
        },
        status="ok"
    )


def generate_tactical_offline_reply(query: str, telemetry: Dict[str, Any], target_inc: Optional[Dict[str, Any]] = None) -> str:
    """Deterministic conversational response when external model calls are unavailable."""
    q = query.lower().strip()
    tokens = [w.strip(".,!?:;\"'()[]{}") for w in q.split()]
    greetings = {"hi", "hello", "hey", "hii", "heyy", "namaste", "hola", "yo"}

    if any(t in greetings for t in tokens) and len(tokens) <= 3:
        return "Hello! How can I help you today? You can ask me about current fire hotspots across India, our detection pipeline, or how we prevent false alarms."

    if "how are you" in q:
        return "I'm doing well, thank you! Ready to help you with any questions about fire monitoring or the FIREX platform."

    if "who are you" in q or "what are you" in q:
        return "I'm the FIREX Assistant, an AI helper for India's thermal anomaly and wildfire monitoring platform. I can explain our detection system, active hotspots, and false-alarm suppression."

    if "thank" in q:
        return "You're very welcome! Let me know if you have any other questions."

    if target_inc:
        return f"Hotspot #{target_inc['id'][:8]} in {target_inc['location']} is classified as {target_inc['classification']}. It has a radiative power of {target_inc['frp']:.1f} MW and is operating within its {target_inc['pattern']} baseline."

    if "surge" in q or "critical" in q or "biggest" in q or "top" in q:
        top = telemetry.get("top_incidents", [])
        s_str = ", ".join([f"{s['location']} ({s['frp']:.1f} MW)" for s in top[:3]])
        return f"Currently, there are {telemetry.get('surge_count', 0)} critical surge fires detected out of {telemetry.get('total_count', 58)} active hotspots. The most intense detections are in {s_str}."

    if "ps162" in q or "problem statement" in q or "sih" in q:
        return "SIH Problem Statement 162 focuses on autonomous thermal anomaly detection across India. Traditional satellite alerts cause thousands of false alarms on routine industrial sites like refineries and kilns. FIREX solves this by comparing live detections against a 365-day historical baseline to filter out routine flaring and flag real fires."

    if "how it works" in q or "detect" in q or "pipeline" in q:
        return "FIREX ingests twice-daily NASA VIIRS satellite data over India, checks if the heat exceeds the 365-day normal baseline for that spot, checks nearby industrial sites, and runs AI visual checks to quickly separate controlled flares from dangerous wildfires."

    if "false alarm" in q or "accuracy" in q:
        return "We avoid false alarms by checking historical thermal data (the 365-day P95 baseline) for every coordinate. Known refinery flare stacks and brick kilns operate within predictable heat levels. If a flare is within its normal range, it's marked as routine rather than triggering an emergency alert."

    if "gujarat" in q or "refinery" in q or "jamnagar" in q:
        return "In Gujarat, detected hotspots around Jamnagar and Vadodara correspond to monitored petroleum refineries and industrial flares, which are operating within expected baseline limits."

    if "punjab" in q or "crop" in q or "agriculture" in q:
        return "Thermal hotspots detected in Punjab are primarily agricultural residue burns from seasonal stubble clearing, typically ranging between 10 and 35 MW."

    return f"FIREX is currently tracking {telemetry.get('total_count', 58)} active hotspots across India, including {telemetry.get('surge_count', 0)} critical surge events. Feel free to ask how our detection works, how we filter false alarms, or about specific regions."
