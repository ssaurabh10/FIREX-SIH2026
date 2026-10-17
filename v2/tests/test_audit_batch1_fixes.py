"""
Tests for Batch 1 Audit Remediations (N-01, N-02, N-03, N-06):
1. N-01: Authentication enforcement on state-mutating and billed AI routes.
2. N-02: ORM column alignment and fallback path resilience in AI Copilot.
3. N-03: Lattice formatting alignment for climatology fallback in severity service.
4. N-06: Commonpath directory containment in imagery cache serving.
"""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.core.config import settings
from app.api.chat import get_live_telemetry_snapshot
from app.gis.spatial import climatology_cell


def test_n01_auth_enforced_on_reinvestigate_and_imagery_and_chat():
    """
    Verifies N-01: When API_KEY_AUTH_ENABLED=True, endpoints require valid API key header.
    """
    client = TestClient(app)

    with patch.object(settings, "API_KEY_AUTH_ENABLED", True), \
         patch.object(settings, "ADMIN_API_KEY", "secret-test-key"):
        
        # 1. /api/investigation/{id}/reinvestigate
        res_reinv = client.post("/api/investigation/test_inc/reinvestigate")
        assert res_reinv.status_code == 401

        # 2. POST /api/imagery/incident/{id}
        res_img = client.post("/api/imagery/incident/test_inc")
        assert res_img.status_code == 401

        # 3. POST /api/chat
        res_chat = client.post("/api/chat", json={"message": "hello"})
        assert res_chat.status_code == 401

        # With valid key
        headers = {settings.API_KEY_HEADER: "secret-test-key"}
        # Chat with valid key should pass auth (even if mock or empty response)
        with patch("requests.post") as mock_req:
            mock_req.return_value.status_code = 200
            mock_req.return_value.json.return_value = {
                "choices": [{"message": {"content": "Test reply"}}]
            }
            res_chat_auth = client.post("/api/chat", json={"message": "hello"}, headers=headers)
            assert res_chat_auth.status_code == 200


def test_n02_chat_telemetry_snapshot_orm_attribute_alignment():
    """
    Verifies N-02: get_live_telemetry_snapshot extracts current_max_frp and state
    without raising AttributeError.
    """
    mock_db = MagicMock()
    mock_incident = MagicMock()
    mock_incident.id = "INC_TEST_001"
    mock_incident.place_name = "Vadodara Petrochemical Complex"
    mock_incident.latitude = 22.3072
    mock_incident.longitude = 73.1812
    mock_incident.current_max_frp = 45.2
    mock_incident.classification = "GAS_FLARE"
    mock_incident.pattern = "NORMAL_PERSISTENT"
    mock_incident.state = "Gujarat"

    # Ensure c.max_frp or c.frp is not accessed or does not exist
    del mock_incident.max_frp
    del mock_incident.frp

    mock_db.query.return_value.all.return_value = [mock_incident]

    snapshot = get_live_telemetry_snapshot(mock_db)
    assert snapshot["total_count"] == 1
    inc = snapshot["all_incidents"][0]
    assert inc["frp"] == 45.2
    assert inc["state"] == "Gujarat"


def test_n03_climatology_cell_lattice_alignment():
    """
    Verifies N-03: climatology_cell generates exact $0.02 lattice key with :.2f padding.
    """
    # Test coordinates with trailing zeros
    cell_lat, cell_lon, spatial_key = climatology_cell(21.1001, 78.5002)
    assert spatial_key == "GRID_21.10_78.50"
    assert f"{cell_lat:.2f}" == "21.10"
    assert f"{cell_lon:.2f}" == "78.50"


def test_n06_serve_cached_image_commonpath_containment():
    """
    Verifies N-06: serve_cached_image rejects directory traversal or prefix matching.
    """
    client = TestClient(app)
    # Attempt directory traversal
    res = client.get("/api/imagery/cache/..%2F..%2Fetc/passwd")
    assert res.status_code == 404
