"""
FIREX v2 Stage 6 Comprehensive Test Suite: Multimodal AI Investigation Engine
Tests taxonomy compliance, prompt rules, key pool rotation/failover, provider abstractions,
DB persistence, and FastAPI API routes.
"""
import os
import sys
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.core.config import settings
from app.storage.database import Base
from app.storage.models import Incident, AIInvestigation, IncidentEvent, IndustrialAsset
from app.intelligence.schemas import (
    AIInvestigationReport,
    AlternativeHypothesis,
    ImageQualityAssessment,
    TaxonomyClass
)
from app.intelligence.key_pool import KeyPoolManager
from app.intelligence.prompts import build_investigation_prompt, PROMPT_VERSION
from app.intelligence.provider import MockAIProvider, OpenRouterProvider
from app.intelligence.service import run_incident_investigation, get_incident_investigations
from app.main import app

# In-memory test database fixture
@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    yield session
    session.close()

# ---------------------------------------------------------------------------
# 1. KEY POOL ROTATION & FAILOVER TESTS
# ---------------------------------------------------------------------------
def test_key_pool_round_robin_rotation():
    keys = ["key-A-1234567890", "key-B-1234567890", "key-C-1234567890", "key-D-1234567890"]
    pool = KeyPoolManager(api_keys=keys)
    assert pool.total_keys == 4
    assert pool.get_current_key() == keys[0]

    # Advance after success
    pool.advance_after_success()
    assert pool.get_current_key() == keys[1]

    # Rotate on error
    idx, next_key = pool.rotate_key()
    assert idx == 2
    assert next_key == keys[2]

    # Advance through to wrap around
    pool.advance_after_success()
    assert pool.get_current_key() == keys[3]
    pool.advance_after_success()
    assert pool.get_current_key() == keys[0]


def test_key_pool_telemetry():
    keys = ["key-1-abcdefghij", "key-2-abcdefghij"]
    pool = KeyPoolManager(api_keys=keys)
    pool.record_call(0)
    pool.record_success(0)
    pool.rotate_key()

    assert pool.stats[0]["calls"] == 1
    assert pool.stats[0]["successes"] == 1
    assert pool.stats[0]["failovers"] == 1

# ---------------------------------------------------------------------------
# 2. TAXONOMY & SCHEMA VALIDATION TESTS
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("taxonomy_class", [
    "industrial_fire",
    "gas_flare",
    "wildfire",
    "agricultural_burning",
    "mining_related",
    "uncertain"
])
def test_all_six_taxonomy_classes_valid(taxonomy_class: TaxonomyClass):
    report = AIInvestigationReport(
        classification=taxonomy_class,
        confidence=85.0,
        alternative=AlternativeHypothesis(
            classification="uncertain",
            confidence=15.0
        ),
        visual_evidence=["Visual indicator observed."],
        contextual_evidence=["Contextual indicator verified."],
        reasoning_summary=f"Classified as {taxonomy_class}."
    )
    assert report.classification == taxonomy_class
    assert report.confidence == 85.0


def test_invalid_taxonomy_normalized():
    provider = OpenRouterProvider()
    assert provider._normalize_taxonomy("industrial fire") == "industrial_fire"
    assert provider._normalize_taxonomy("GAS-FLARE") == "gas_flare"
    assert provider._normalize_taxonomy("wild fire") == "wildfire"
    assert provider._normalize_taxonomy("invalid_alien_heat") == "uncertain"

# ---------------------------------------------------------------------------
# 3. PROMPT GENERATION & BLUEPRINT RULES TESTS
# ---------------------------------------------------------------------------
def test_prompt_generation_includes_baseline_and_gis():
    mock_pkg = {
        "incident": {
            "incident_code": "INC-TEST-001",
            "latitude": 20.9650,
            "longitude": 86.0110,
            "max_frp_mw": 55.0,
            "mean_frp_mw": 35.0,
            "satellite": "VIIRS_NOAA20",
            "observation_count": 4
        },
        "gis_context": {
            "facility_name": "TATA Steel Kalinganagar",
            "facility_type": "steel_plant",
            "industry": "Iron & Steel",
            "facility_distance_m": 0.0,
            "is_inside_facility": True,
            "state": "Odisha",
            "district": "Jajpur"
        },
        "historical_features": {
            "median_frp_mw": 2.88,
            "p95_frp_mw": 11.08,
            "history_reliability_label": "STRONG",
            "is_persistent": True
        },
        "visual_context": {
            "radius_meters": 1000.0,
            "zoom_level": 16,
            "provider": "Google Satellite"
        }
    }

    prompt = build_investigation_prompt(mock_pkg)
    assert "INC-TEST-001" in prompt
    assert "TATA Steel Kalinganagar" in prompt
    assert "55.0 MW" in prompt
    assert "11.1 MW" in prompt  # P95 baseline ceiling formatted to 1 decimal place
    assert "2.9 MW" in prompt   # Median baseline formatted to 1 decimal place
    assert "industrial_fire" in prompt
    assert "gas_flare" in prompt
    assert "mining_related" in prompt

# ---------------------------------------------------------------------------
# 4. MOCK PROVIDER CLASSIFICATION ENGINE TESTS
# ---------------------------------------------------------------------------
def test_mock_provider_classifications():
    provider = MockAIProvider()

    # Industrial fire (steel + spike)
    r1 = provider.investigate("Incident at TATA Steel with 55.0 MW spike", "")
    assert r1.classification == "industrial_fire"
    assert r1.confidence > 80.0

    # Gas flare (routine refinery)
    r2 = provider.investigate("Incident at Jamnagar Refinery flare unit with 8.0 MW", "")
    assert r2.classification == "gas_flare"

    # Wildfire (forest canopy)
    r3 = provider.investigate("Wildfire detection in Nilgiri forest canopy", "")
    assert r3.classification == "wildfire"

    # Agricultural burning (crop stubble)
    r4 = provider.investigate("Crop residue burning in Punjab agricultural fields", "")
    assert r4.classification == "agricultural_burning"

    # Mining (open cast coal pit)
    r5 = provider.investigate("Open cast coal mine quarry pit anomaly", "")
    assert r5.classification == "mining_related"

    # Uncertain
    r6 = provider.investigate("Indistinguishable heat in cloudy area", "")
    assert r6.classification == "uncertain"

# ---------------------------------------------------------------------------
# 5. OPENROUTER JSON PARSER & MARKDOWN STRIPPER TESTS
# ---------------------------------------------------------------------------
def test_openrouter_json_parsing_with_code_fences():
    provider = OpenRouterProvider()
    raw_markdown = """```json
{
  "classification": "industrial_fire",
  "confidence": 92.5,
  "alternative": {
    "classification": "gas_flare",
    "confidence": 7.5
  },
  "visual_evidence": ["Heavy blast furnace plume"],
  "contextual_evidence": ["Inside steel plant perimeter"],
  "uncertainties": ["Minor haze"],
  "image_quality": {"score": 85, "cloud_cover": "low", "visibility": "good"},
  "needs_reinvestigation": false,
  "reasoning_summary": "Process explosion at blast furnace."
}
```"""
    report = provider._parse_json_response(raw_markdown, reasoning="thinking trace", key_id="Key #1")
    assert report.classification == "industrial_fire"
    assert report.confidence == 92.5
    assert report.alternative.classification == "gas_flare"
    assert report.reasoning_details == "thinking trace"
    assert report.key_used == "Key #1"


def test_openrouter_fallback_on_garbage():
    provider = OpenRouterProvider()
    report = provider._parse_json_response("This is not JSON at all!", reasoning=None, key_id="Key #1")
    assert report.classification == "uncertain"
    assert report.confidence == 50.0
    assert report.needs_reinvestigation is True

# ---------------------------------------------------------------------------
# 6. INVESTIGATION SERVICE & DATABASE PERSISTENCE TESTS
# ---------------------------------------------------------------------------
def test_investigation_service_lifecycle(db_session):
    # Setup test asset and incident
    asset = IndustrialAsset(
        id="asset-test-01",
        name="Test Refinery Complex",
        facility_type="refinery",
        industry="Oil & Gas",
        category="RED",
        latitude=22.0,
        longitude=88.0
    )
    db_session.add(asset)

    incident = Incident(
        id="inc-test-01",
        incident_code="INC-2026-TEST",
        status="NEW",
        latitude=22.0,
        longitude=88.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow(),
        current_max_frp=65.0,
        nearest_asset_id=asset.id,
        distance_to_asset_km=0.1
    )
    db_session.add(incident)
    db_session.commit()

    # Run investigation using Mock provider
    provider = MockAIProvider()
    res = run_incident_investigation("inc-test-01", db_session, provider=provider)

    assert res["status"] == "COMPLETED"
    assert res["classification"] in ["industrial_fire", "gas_flare"]
    assert res["confidence"] > 0.0

    # Verify Incident record was updated
    db_session.refresh(incident)
    assert incident.classification == res["classification"]
    assert incident.status == "ACTIVE"

    # Verify AIInvestigation row in DB
    investigations = get_incident_investigations("inc-test-01", db_session)
    assert len(investigations) == 1
    assert investigations[0]["classification"] == res["classification"]

    # Verify second run returns CACHED without re-analyzing
    cached_res = run_incident_investigation("inc-test-01", db_session, force_reinvestigate=False, provider=provider)
    assert cached_res["status"] == "CACHED"
    assert cached_res["investigation_id"] == res["investigation_id"]

    # Verify force_reinvestigate=True adds another investigation row
    forced_res = run_incident_investigation("inc-test-01", db_session, force_reinvestigate=True, provider=provider)
    assert forced_res["status"] == "COMPLETED"
    history = get_incident_investigations("inc-test-01", db_session)
    assert len(history) == 2

# ---------------------------------------------------------------------------
# 7. FASTAPI API ROUTE TESTS
# ---------------------------------------------------------------------------
def test_investigation_api_endpoints():
    client = TestClient(app)

    # Test GET on non-existent incident
    resp_404 = client.get("/api/investigation/non-existent-id")
    assert resp_404.status_code == 404

    # Test POST on real trial incident c5e3f0b7-929f-41c2-9b85-cf5b179fc9c2
    # In trial, this incident was already verified
    resp = client.get("/api/investigation/c5e3f0b7-929f-41c2-9b85-cf5b179fc9c2")
    # If not investigated in DB yet, 404 is expected until triggered
    assert resp.status_code in [200, 404]
