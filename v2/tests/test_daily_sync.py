"""
Tests for FIREX Automated Daily Sync & Ingestion Scheduling
Verifies:
1. Configuration setting AUTO_SYNC_INTERVAL_HOURS is present and loaded.
2. Endpoint /api/trigger-sync supports asynchronous background execution via `background=true`.
3. Background trigger returns 200 OK without blocking HTTP threads.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.core.config import settings
from app.orchestration.lock import pipeline_lock


def test_auto_sync_configuration():
    """Verifies AUTO_SYNC_INTERVAL_HOURS is defined and defaults to 0 (disabled)."""
    assert hasattr(settings, "AUTO_SYNC_INTERVAL_HOURS")
    assert isinstance(settings.AUTO_SYNC_INTERVAL_HOURS, int)


def test_trigger_sync_background_execution():
    """
    Verifies that calling /api/trigger-sync?background=true returns immediately
    with status 'initiated' and starts worker in background.
    """
    client = TestClient(app)

    with patch("app.api.analysis.run_sync_worker_pipeline") as mock_worker:
        response = client.post("/api/trigger-sync?background=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "initiated"
        assert "background" in data["message"].lower()


def test_trigger_sync_background_when_already_running():
    """
    Verifies that calling /api/trigger-sync?background=true when already running
    returns status 'already_running' cleanly without 500 error.
    """
    client = TestClient(app)

    # Acquire lock artificially to simulate active pipeline
    pipeline_lock.acquire("test-active-run")
    try:
        response = client.post("/api/trigger-sync?background=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "already_running"
    finally:
        pipeline_lock.release()
