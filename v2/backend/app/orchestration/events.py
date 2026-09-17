"""
FIREX v2 Server-Sent Events (SSE) Event Broadcaster
Manages real-time streaming of pipeline events to connected frontend clients.
Enforces the 11 blueprint event types:
1. ANALYSIS_STARTED
2. FIRMS_FETCHED
3. GIS_COMPLETED
4. CLUSTERING_COMPLETED
5. SELECTION_COMPLETED
6. IMAGERY_STARTED
7. AI_STARTED
8. AI_COMPLETED
9. SEVERITY_COMPLETED
10. ALERT_CREATED
11. ANALYSIS_COMPLETED
Also formats backward-compatible v1 stage progress for dashboard integration.
"""
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Blueprint event type definitions.
# F-055: the spec's SSE protocol (V2_LOGIC_SPECIFICATION.md:485-507) names every event in
# SCREAMING_SNAKE, and the string below is what lands on the `event:` line -- the dispatch
# key a spec-conformant subscriber switches on. These previously held dotted lowercase names
# ("analysis.started"), so the spec's uppercase spelling existed only as Python identifiers
# and every subscriber built to the spec table silently matched nothing. Only the values
# changed: the constant names are imported by the pipeline and remain as they were. The four
# events the spec never lists (GIS_COMPLETED, AI_STARTED, ALERT_CREATED, ANALYSIS_FAILED)
# take the same spelling so a subscriber needs one casing rule, not two.
EVENT_ANALYSIS_STARTED = "ANALYSIS_STARTED"
EVENT_FIRMS_FETCHED = "FIRMS_FETCHED"
EVENT_GIS_COMPLETED = "GIS_COMPLETED"
EVENT_CLUSTERING_COMPLETED = "CLUSTERING_COMPLETED"
EVENT_SELECTION_COMPLETED = "SELECTION_COMPLETED"
EVENT_IMAGERY_STARTED = "IMAGERY_STARTED"
EVENT_AI_STARTED = "AI_STARTED"
EVENT_AI_COMPLETED = "AI_COMPLETED"
EVENT_SEVERITY_COMPLETED = "SEVERITY_COMPLETED"
EVENT_ALERT_CREATED = "ALERT_CREATED"
EVENT_ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
EVENT_ANALYSIS_FAILED = "ANALYSIS_FAILED"

# Mapping blueprint events to v1 UI stages for clean, understandable progress
STAGE_MAPPING = {
    EVENT_ANALYSIS_STARTED: {"stage": 0, "pct": 5, "label": "Starting Analysis Pipeline"},
    EVENT_FIRMS_FETCHED: {"stage": 1, "pct": 20, "label": "Satellite Thermal Feed"},
    EVENT_GIS_COMPLETED: {"stage": 2, "pct": 35, "label": "History & Baseline Matching"},
    EVENT_CLUSTERING_COMPLETED: {"stage": 3, "pct": 50, "label": "Hotspot Clustering"},
    EVENT_SELECTION_COMPLETED: {"stage": 3, "pct": 65, "label": "Target Prioritization"},
    EVENT_IMAGERY_STARTED: {"stage": 4, "pct": 75, "label": "Satellite Imagery Preparation"},
    EVENT_AI_STARTED: {"stage": 5, "pct": 80, "label": "AI Vision Analysis"},
    EVENT_AI_COMPLETED: {"stage": 5, "pct": 90, "label": "AI Vision Verified"},
    EVENT_SEVERITY_COMPLETED: {"stage": 6, "pct": 95, "label": "Threat Risk Assessment"},
    EVENT_ALERT_CREATED: {"stage": 6, "pct": 98, "label": "Alerts Dispatched"},
    EVENT_ANALYSIS_COMPLETED: {"stage": 6, "pct": 100, "label": "Analysis Complete"},
    EVENT_ANALYSIS_FAILED: {"stage": 6, "pct": 100, "label": "Analysis Error"}
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
        pct = self.data.get("stage_pct") if self.data.get("stage_pct") is not None else compat["pct"]
        payload = {
            "event": self.event_type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "stage": compat["stage"],
            "pct": pct,
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
        # queue -> the loop it was subscribed on, or None when subscribe() was
        # called with no running loop at all (the CLI, and the tests that drive
        # the pipeline from a plain sync function).
        self._subscribers: Dict[asyncio.Queue, Optional[asyncio.AbstractEventLoop]] = {}
        self._history: List[PipelineEvent] = []
        self._max_history = 100

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        try:
            loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._subscribers[q] = loop
        logger.debug(f"[SSE] Client subscribed. Total subscribers: {len(self._subscribers)}")
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.pop(q, None)
        logger.debug(f"[SSE] Client unsubscribed. Remaining: {len(self._subscribers)}")

    def _enqueue(self, q: asyncio.Queue, sse_msg: str) -> None:
        """
        Hand one message to one subscriber, dropping that subscriber if its queue
        refuses it. Called either directly (already on the subscriber's loop) or
        through that loop's call_soon_threadsafe -- never from a foreign thread.
        """
        try:
            q.put_nowait(sse_msg)
        except Exception:
            self._subscribers.pop(q, None)

    def publish(self, event_type: str, data: Dict[str, Any], run_id: Optional[str] = None) -> PipelineEvent:
        event = PipelineEvent(event_type=event_type, data=data, run_id=run_id)
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        sse_msg = event.to_sse_format()
        try:
            running_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        for q, loop in list(self._subscribers.items()):
            # asyncio.Queue is not thread-safe, and publish is not always on the
            # loop that owns these queues: POST /api/analysis/run?stream=true runs
            # the pipeline through loop.run_in_executor, and GET
            # /api/trigger-sync-stream starts it on a bare threading.Thread. A
            # bare put_nowait from that worker still lands the message in the
            # queue, but it cannot wake the loop, so the subscriber waits out its
            # own keep-alive timeout before the event arrives.
            if loop is None or loop is running_loop:
                self._enqueue(q, sse_msg)
                continue
            try:
                loop.call_soon_threadsafe(self._enqueue, q, sse_msg)
            except RuntimeError:
                # That loop is closed and can serve no further messages.
                self._subscribers.pop(q, None)

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
