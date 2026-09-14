"""
FIREX v2 Server-Sent Events (SSE) Event Broadcaster
Manages real-time streaming of pipeline events to connected frontend clients.
Enforces the 11 blueprint event types:
1. analysis.started
2. firms.fetched
3. gis.completed
4. clustering.completed
5. selection.completed
6. imagery.started
7. ai.started
8. ai.completed
9. severity.completed
10. alert.created
11. analysis.completed
Also formats backward-compatible v1 stage progress for dashboard integration.
"""
import json
import asyncio
import logging
from typing import Dict, Any, List, Set, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Blueprint event type definitions
EVENT_ANALYSIS_STARTED = "analysis.started"
EVENT_FIRMS_FETCHED = "firms.fetched"
EVENT_GIS_COMPLETED = "gis.completed"
EVENT_CLUSTERING_COMPLETED = "clustering.completed"
EVENT_SELECTION_COMPLETED = "selection.completed"
EVENT_IMAGERY_STARTED = "imagery.started"
EVENT_AI_STARTED = "ai.started"
EVENT_AI_COMPLETED = "ai.completed"
EVENT_SEVERITY_COMPLETED = "severity.completed"
EVENT_ALERT_CREATED = "alert.created"
EVENT_ANALYSIS_COMPLETED = "analysis.completed"
EVENT_ANALYSIS_FAILED = "analysis.failed"

# Mapping blueprint events to v1 UI stages for zero-breakage dashboard compatibility
STAGE_MAPPING = {
    EVENT_ANALYSIS_STARTED: {"stage": 0, "pct": 5, "label": "Initializing Mission Orbit Pipeline"},
    EVENT_FIRMS_FETCHED: {"stage": 1, "pct": 20, "label": "FIRMS Ingestion & Sovereign Filter"},
    EVENT_GIS_COMPLETED: {"stage": 2, "pct": 35, "label": "GIS Spatial Context & Asset Enrichment"},
    EVENT_CLUSTERING_COMPLETED: {"stage": 3, "pct": 50, "label": "Spatial-Temporal Clustering & Association"},
    EVENT_SELECTION_COMPLETED: {"stage": 3, "pct": 65, "label": "Incident Triage & Investigation Selection"},
    EVENT_IMAGERY_STARTED: {"stage": 4, "pct": 75, "label": "High-Res Optical Satellite Tile Synthesis"},
    EVENT_AI_STARTED: {"stage": 5, "pct": 85, "label": "Multimodal AI Vision Scene Analysis"},
    EVENT_AI_COMPLETED: {"stage": 5, "pct": 90, "label": "AI Scene Classification & Reasoning"},
    EVENT_SEVERITY_COMPLETED: {"stage": 6, "pct": 95, "label": "Operational Threat Severity Assessment"},
    EVENT_ALERT_CREATED: {"stage": 6, "pct": 98, "label": "Incident Alert Dispatch"},
    EVENT_ANALYSIS_COMPLETED: {"stage": 6, "pct": 100, "label": "Analysis Complete & Feeds Published"},
    EVENT_ANALYSIS_FAILED: {"stage": 6, "pct": 100, "label": "Analysis Run Error"}
}

class PipelineEvent:
    def __init__(self, event_type: str, data: Dict[str, Any], run_id: Optional[str] = None):
        self.event_type = event_type
        self.data = data
        self.run_id = run_id
        self.timestamp = datetime.utcnow().isoformat()

    def to_sse_format(self) -> str:
        """
        Standard SSE wire protocol:
        event: <type>\n
        data: <json>\n\n
        """
        # Inject v1 compatibility fields into data
        compat = STAGE_MAPPING.get(self.event_type, {"stage": 0, "pct": 0, "label": self.event_type})
        payload = {
            "event": self.event_type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "stage": compat["stage"],
            "pct": compat["pct"],
            "label": compat["label"],
            "detail": self.data.get("message") or compat["label"],
            "data": self.data,
            "done": (self.event_type in [EVENT_ANALYSIS_COMPLETED, EVENT_ANALYSIS_FAILED])
        }
        # Merge top level for v1 UI listeners expecting data.stage etc.
        for k, v in self.data.items():
            if k not in payload:
                payload[k] = v

        return f"event: {self.event_type}\ndata: {json.dumps(payload)}\n\n"

class AnalysisEventBroadcaster:
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._history: List[PipelineEvent] = []
        self._max_history = 100

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        logger.debug(f"[SSE] Client subscribed. Total subscribers: {len(self._subscribers)}")
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)
        logger.debug(f"[SSE] Client unsubscribed. Remaining: {len(self._subscribers)}")

    def publish(self, event_type: str, data: Dict[str, Any], run_id: Optional[str] = None) -> PipelineEvent:
        event = PipelineEvent(event_type=event_type, data=data, run_id=run_id)
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        sse_msg = event.to_sse_format()
        dead_queues = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(sse_msg)
            except Exception:
                dead_queues.append(q)

        for dq in dead_queues:
            self._subscribers.discard(dq)

        return event

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [
            {
                "event": e.event_type,
                "data": e.data,
                "run_id": e.run_id,
                "timestamp": e.timestamp
            }
            for e in self._history[-limit:]
        ]

    def clear(self):
        self._history.clear()

# Global singleton broadcaster
event_broadcaster = AnalysisEventBroadcaster()
