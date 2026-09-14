"""
FIREX v2 Baseline Automated Test Suite for Stage 0
Verifies:
1. Health endpoint returns 200 and healthy DB connection.
2. Status endpoint returns environment configurations.
3. Database tables are all created according to the Section 10 data model.
4. Static frontend loads with 200 OK.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from app.main import app
from app.storage.database import engine

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"]["status"] == "connected"

def test_api_status_endpoint():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["firms_configured"] is True
    assert data["openrouter_keys_count"] >= 1

def test_database_schema_tables():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected_tables = {
        "observations",
        "incidents",
        "incident_observations",
        "industrial_assets",
        "imagery_records",
        "ai_investigations",
        "historical_baselines",
        "severity_assessments",
        "alert_records",
        "incident_events"
    }
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"

def test_frontend_console_mount():
    response = client.get("/console/")
    assert response.status_code == 200
    assert "<title>FIREX Thermal Watch</title>" in response.text
