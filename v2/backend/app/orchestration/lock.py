"""
FIREX v2 Analysis Run Lock Manager
Guarantees single active execution of the analysis pipeline.
Returns HTTP 409 Conflict if a run is already active.
"""
import threading
from typing import Optional, Dict, Any
from datetime import datetime

class AnalysisAlreadyRunningError(Exception):
    def __init__(self, active_run_id: str, started_at: datetime):
        self.active_run_id = active_run_id
        self.started_at = started_at
        super().__init__(f"Analysis run {active_run_id} is already in progress since {started_at.isoformat()}")

class AnalysisRunLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._is_running = False
        self._active_run_id: Optional[str] = None
        self._started_at: Optional[datetime] = None

    def acquire(self, run_id: str) -> bool:
        """
        Attempts to acquire the run lock for run_id.
        Raises AnalysisAlreadyRunningError if already locked.
        """
        with self._lock:
            if self._is_running:
                raise AnalysisAlreadyRunningError(
                    active_run_id=self._active_run_id or "unknown",
                    started_at=self._started_at or datetime.utcnow()
                )
            self._is_running = True
            self._active_run_id = run_id
            self._started_at = datetime.utcnow()
            return True

    def release(self, run_id: Optional[str] = None) -> bool:
        """
        Releases the lock if held by run_id (or unconditionally if run_id is None).
        """
        with self._lock:
            if not self._is_running:
                return False
            if run_id is not None and self._active_run_id != run_id:
                # Held by another run ID
                return False
            self._is_running = False
            self._active_run_id = None
            self._started_at = None
            return True

    def is_locked(self) -> bool:
        with self._lock:
            return self._is_running

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_running": self._is_running,
                "active_run_id": self._active_run_id,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "elapsed_seconds": (datetime.utcnow() - self._started_at).total_seconds() if self._started_at else 0.0
            }

    def force_unlock(self):
        """Administrative / test reset."""
        with self._lock:
            self._is_running = False
            self._active_run_id = None
            self._started_at = None

# Global singleton lock instance
pipeline_lock = AnalysisRunLock()
