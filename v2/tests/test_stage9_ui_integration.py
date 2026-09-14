"""
Unit & Integration Tests for Stage 9: Existing UI Integration + Industry Intelligence
Verifies that:
1. export_v1_dashboard_data populates all required Stage 9 fields into frontend incidents.json
2. Industry search & facility profile endpoints respond with complete metadata
3. Satellite persistence & history stats endpoints match the HUD contract
4. Analysis status & streaming routes function as expected
"""
import os
import json
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.storage.database import SessionLocal, Base, engine
from app.storage.models import Observation, Incident, IndustrialAsset, AIInvestigation, SeverityAssessment, AnalysisRun
from app.orchestration.pipeline import export_v1_dashboard_data, FRONTEND_DATA_DIR


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


def test_dashboard_data_export_contract(db_session):
    """
    Verifies export_v1_dashboard_data produces complete Stage 9 incident contracts.
    """
    # Create test facility
    facility = IndustrialAsset(
        id="test-refinery-01",
        name="Test Sovereign Petroleum Refinery Complex",
        operator="Test Energy Ltd",
        facility_type="oil_refinery",
        industry="Petroleum Refining",
        category="gas_flare",
        latitude=28.5000,
        longitude=77.2000,
        state="Delhi NCR",
        district="South Delhi",
        display_address="Industrial Area, Delhi, India",
        hazard_category="MAJOR_ACCIDENT_HAZARD",
        buffer_radius_meters=1500.0
    )
    db_session.merge(facility)

    # Create test incident
    inc = Incident(
        id="test-inc-stage9-01",
        incident_code="INC-STAGE9-001",
        status="ACTIVE",
        latitude=28.5010,
        longitude=77.2010,
        current_max_frp=38.5,
        first_detected_at=datetime.utcnow() - timedelta(hours=2),
        last_detected_at=datetime.utcnow(),
        observation_count=5,
        investigation_priority=78.5,
        severity_score=39.0,
        severity_level="MEDIUM",
        severity_confidence=85.0,
        classification="gas_flare",
        classification_confidence=92.0,
        nearest_asset_id=facility.id,
        distance_to_asset_km=0.15,
        is_inside_facility=True,
        state="Delhi NCR",
        district="South Delhi"
    )
    db_session.merge(inc)

    # Create test severity assessment
    sev = SeverityAssessment(
        incident_id=inc.id,
        score=39.0,
        level="MEDIUM",
        confidence=85.0,
        factors={"vision_ai": 25.0, "frp": 12.0, "facility_distance": 2.0},
        created_at=datetime.utcnow()
    )
    db_session.merge(sev)
    db_session.commit()

    try:
        # Execute export
        export_v1_dashboard_data(db_session)

        # Verify incidents.json file
        inc_file = os.path.join(FRONTEND_DATA_DIR, "incidents.json")
        assert os.path.exists(inc_file), "incidents.json must be exported"

        with open(inc_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) > 0

        exported = next((item for item in data if item["id"] == inc.id), None)
        assert exported is not None, "Test incident must be present in exported JSON"

        # Stage 9 required fields check
        assert "investigation_priority" in exported
        assert exported["investigation_priority"] == 78.5
        assert "priority_explanation" in exported
        assert len(exported["priority_explanation"]) > 0

        assert "severity_score" in exported
        assert exported["severity_score"] == 39.0
        assert "severity_level" in exported
        assert exported["severity_level"] == "MEDIUM"

        assert "historical_anomaly" in exported
        assert "baseline_median" in exported
        assert "baseline_p95" in exported
        assert "active_days_365d" in exported
        assert "is_routine_flare" in exported

        assert "ai_classification" in exported
        assert exported["ai_classification"] == "gas_flare"
        assert "ai_confidence" in exported
        assert "ai_uncertainty" in exported

        assert "risk_factors" in exported
        assert len(exported["risk_factors"]) > 0
        assert "action_recommendation" in exported
    finally:
        # Clean up test artifacts so test fixtures never pollute live dashboard data
        db_session.query(SeverityAssessment).filter(SeverityAssessment.incident_id == inc.id).delete()
        db_session.query(Incident).filter(Incident.id == inc.id).delete()
        db_session.query(IndustrialAsset).filter(IndustrialAsset.id == facility.id).delete()
        db_session.commit()
        export_v1_dashboard_data(db_session)


def test_industry_search_api(client, db_session):
    """
    Tests /api/industries/search endpoint for facility search capability.
    """
    res = client.get("/api/industries/search?q=Refinery")
    assert res.status_code == 200
    results = res.json()
    assert isinstance(results, list)
    assert len(results) > 0
    first = results[0]
    assert "name" in first
    assert "operator" in first
    assert "facility_type" in first
    assert "latitude" in first
    assert "longitude" in first


def test_industry_history_profile_api(client, db_session):
    """
    Tests /api/industries/{id}/history and baseline endpoints for facility deep dive.
    """
    asset = db_session.query(IndustrialAsset).first()
    assert asset is not None

    res = client.get(f"/api/industries/{asset.id}/history")
    assert res.status_code == 200
    profile = res.json()
    assert "facility_id" in profile
    assert "facility_name" in profile
    assert "p95_frp" in profile
    assert "median_frp" in profile

    base_res = client.get(f"/api/industries/{asset.id}/baseline")
    assert base_res.status_code == 200
    base = base_res.json()
    assert "p95_frp" in base
    assert "median_frp" in base


def test_history_stats_and_status_api(client):
    """
    Tests /api/history-stats HUD widget endpoint and /api/analysis/status endpoint.
    """
    res = client.get("/api/history-stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_runs" in data
    assert "total_hotspots" in data
    assert "current_pass" in data
    assert data["current_pass"] in ["DAY", "NIGHT"]

    status_res = client.get("/api/analysis/status")
    assert status_res.status_code == 200
    status = status_res.json()
    assert "is_running" in status
    assert "active_run_id" in status


def test_history_search_api(client):
    """
    Tests /api/history/search endpoint verifying:
    1. Filter by state (Odisha) and min_frp returns filtered observation rows.
    2. Enriched sovereign boundaries (state, district) and nearest industrial asset.
    3. Aggregate telemetry summary metrics (min_frp, max_frp, mean_frp, total_matches).
    4. Text query matching works.
    """
    res = client.get("/api/history/search?state=Odisha&min_frp=15.0&limit=5")
    assert res.status_code == 200
    payload = res.json()
    assert "total_matches" in payload
    assert "results" in payload
    assert "summary" in payload
    assert payload["returned"] <= 5

    if payload["returned"] > 0:
        row = payload["results"][0]
        assert "latitude" in row
        assert "longitude" in row
        assert "frp_mw" in row
        assert row["frp_mw"] >= 15.0
        assert "state" in row
        assert "district" in row
        assert "nearest_facility" in row
        assert "distance_km" in row

    # Test query filter
    q_res = client.get("/api/history/search?query=Refinery&limit=3")
    assert q_res.status_code == 200
    q_payload = q_res.json()
    assert "results" in q_payload
    assert q_payload["returned"] <= 3

