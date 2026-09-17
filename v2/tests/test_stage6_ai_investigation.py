"""
FIREX v2 Stage 6 Comprehensive Test Suite: Multimodal AI Investigation Engine
Tests taxonomy compliance, prompt rules, key pool rotation/failover, provider abstractions,
DB persistence, and FastAPI API routes.
"""
import os
import sys
import json
import re
import time
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
from app.imagery.viewport import crop_coverage_radius_meters
from app.intelligence.schemas import (
    AIInvestigationReport,
    AlternativeHypothesis,
    ImageQualityAssessment,
    TaxonomyClass
)
from app.intelligence.key_pool import (
    KeyPoolManager,
    COOLDOWN_SECONDS_AUTH,
    COOLDOWN_SECONDS_RATE_LIMIT
)
from app.intelligence.prompts import build_investigation_prompt, PROMPT_VERSION, SYSTEM_PROMPT
from app.intelligence.provider import MockAIProvider, OpenRouterProvider, FALLBACK_CONFIDENCE_CEILING
import app.intelligence.provider as provider_module
from app.imagery.viewport import calculate_incident_viewport
from app.intelligence.service import run_incident_investigation, get_incident_investigations
from app.severity.scoring import calculate_ai_source_severity
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


# Spec 6.3 key-health tracking: error_count, total_requests, cooldown_until (F-007).
def test_key_pool_tracks_errors_requests_and_cooldown_deadline():
    pool = KeyPoolManager(api_keys=["key-A-1234567890", "key-B-1234567890"])
    pool.record_call()
    pool.quarantine_key(429)

    assert pool.stats[0]["calls"] == 1          # total_requests
    assert pool.stats[0]["errors"] == 1         # error_count
    assert pool.stats[0]["cooldown_until"] > 0.0  # quarantine deadline


# Spec 6.3: "On HTTP 429 (Rate Limit), key is quarantined for 60 seconds."
def test_429_quarantines_key_for_about_sixty_seconds():
    assert COOLDOWN_SECONDS_RATE_LIMIT == 60.0
    pool = KeyPoolManager(api_keys=["key-A-1234567890", "key-B-1234567890"])
    assert pool.get_current_key() == "key-A-1234567890"

    pool.quarantine_key(429)

    remaining = pool.cooldown_remaining_seconds(0)
    assert abs(remaining - 60.0) < 1.0, f"429 quarantine was {remaining:.1f}s, expected ~60s"


# Spec 6.3: "On HTTP 401/403, quarantined for 1 hour." 402 is not in the spec's
# list but is treated as the same credential/billing class of failure.
def test_401_and_402_quarantine_key_for_about_one_hour():
    assert COOLDOWN_SECONDS_AUTH == 3600.0

    for status_code in (401, 403, 402):
        pool = KeyPoolManager(api_keys=["key-A-1234567890", "key-B-1234567890"])
        pool.quarantine_key(status_code)
        remaining = pool.cooldown_remaining_seconds(0)
        assert abs(remaining - 3600.0) < 1.0, (
            f"HTTP {status_code} quarantine was {remaining:.1f}s, expected ~3600s"
        )


def test_cooling_key_is_not_immediately_reselected():
    pool = KeyPoolManager(api_keys=["key-A-1234567890", "key-B-1234567890", "key-C-1234567890"])
    assert pool.get_current_key() == "key-A-1234567890"

    pool.quarantine_key(429)
    assert pool.get_current_key() == "key-B-1234567890", "a cooling key was re-selected"

    pool.quarantine_key(429)
    assert pool.get_current_key() == "key-C-1234567890"

    # Every key quarantined -> the pool reports exhaustion (empty key) instead of
    # re-serving a cooling key, which is what lets the provider break out of its
    # retry loop and fall through to the deterministic fallback report.
    pool.quarantine_key(429)
    assert pool.get_current_key() == ""


def test_selection_prefers_the_longest_cooled_usable_key():
    pool = KeyPoolManager(api_keys=["key-A-1234567890", "key-B-1234567890"])
    # B is the current key but only just came off a quarantine; A has rested longer.
    pool.current_idx = 1
    now = time.monotonic()
    pool.stats[0]["cooldown_until"] = now - 300.0
    pool.stats[1]["cooldown_until"] = now - 1.0

    assert pool.get_current_key() == "key-A-1234567890"

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


# F-004: spec 6.2 names the sixth class "mining_or_other_thermal_source" while the
# Blueprint (and therefore the wire value) uses "mining_related". The spec literal
# must be accepted and normalised, not silently downgraded to "uncertain".
def test_spec_mining_literal_normalised_to_blueprint_value():
    provider = OpenRouterProvider()
    assert provider._normalize_taxonomy("mining_or_other_thermal_source") == "mining_related"
    assert provider._normalize_taxonomy("Mining-Or-Other Thermal Source") == "mining_related"

    # End to end: a spec-conformant model answer is accepted, not silently
    # downgraded to "uncertain" by the parser.
    payload = {
        "classification": "mining_or_other_thermal_source",
        "confidence": 71.0,
        "alternative": {"classification": "industrial_fire", "confidence": 29.0},
        "visual_evidence": ["Terraced open-cast pit benches"],
        "contextual_evidence": ["Inside a documented coal-mining concession"],
        "uncertainties": ["Haze"],
        "reasoning_summary": "Coal seam combustion inside an active pit."
    }
    report = provider._parse_json_response(json.dumps(payload), reasoning=None, key_id="Key #1")
    assert report.classification == "mining_related"


# F-003: spec 6.2 serialises image_quality.score as 92.0, a JSON float.
def test_fractional_image_quality_score_survives_round_trip():
    provider = OpenRouterProvider()
    payload = {
        "classification": "industrial_fire",
        "confidence": 92.5,
        "alternative": {"classification": "gas_flare", "confidence": 7.5},
        "visual_evidence": ["Blast furnace plume"],
        "contextual_evidence": ["Inside steel plant perimeter"],
        "uncertainties": ["Minor haze"],
        "image_quality": {"score": 92.5, "cloud_cover": "low", "visibility": "good"},
        "needs_reinvestigation": False,
        "reasoning_summary": "Process explosion at blast furnace."
    }
    report = provider._parse_json_response(json.dumps(payload), reasoning=None, key_id="Key #1")
    assert report.image_quality.score == 92.5
    assert isinstance(report.image_quality.score, float)

    # ... and it survives serialisation back through the schema.
    dumped = report.model_dump()
    assert dumped["image_quality"]["score"] == 92.5
    assert AIInvestigationReport(**dumped).image_quality.score == 92.5

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
# 3b. SECTION 6.1 MANDATORY PROMPT RULES (F-095)
#
# The twelve rules are the product of spec 6.1, and before this block no test
# asserted their count, numbering or wording -- so deleting or reordering them
# failed nothing. Each entry is (rule number, a distinctive phrase from the rule).
# ---------------------------------------------------------------------------
SECTION_6_1_RULES = [
    (1, "Treat NASA FIRMS as a thermal anomaly detection, NOT guaranteed proof of an uncontrolled fire."),
    (2, "Visually inspect the satellite image inside the range rings; do NOT rely exclusively on tabular metadata."),
    (3, "Use GIS and FIRMS as contextual guidance to interpret the visual scene."),
    (4, 'Never invent or hallucinate missing values. If an attribute is unknown, explicitly state "Unknown".'),
    (5, "Do NOT calculate or assign final disaster severity scores"),
    (6, "Provide both a primary classification AND an alternative competing hypothesis."),
    (7, "Detail specific visual evidence observed"),
    (8, "Detail specific contextual evidence"),
    (9, "Clearly state uncertainties, optical constraints, cloud obscuration, or temporal lag."),
    (10, 'classify as "uncertain" rather than guessing'),
    (11, "Never claim definitive ground truth from optical imagery alone; provide probabilistic assessment."),
    (12, "Output MUST be ONLY a valid JSON object"),
]


def test_system_prompt_carries_the_twelve_section_6_1_rules():
    rules_block = SYSTEM_PROMPT.split("CRITICAL OPERATIONAL RULES (MANDATORY):", 1)
    assert len(rules_block) == 2, "SYSTEM_PROMPT has no mandatory-rules block"

    numbered = re.findall(r"(?m)^(\d+)\.\s", rules_block[1])
    assert numbered == [str(i) for i in range(1, 13)], (
        f"expected rules numbered 1-12 in order, found {numbered}"
    )

    for number, phrase in SECTION_6_1_RULES:
        assert phrase in SYSTEM_PROMPT, f"rule {number} text missing from SYSTEM_PROMPT: {phrase!r}"


# F-001: spec 6.1 rule 4 mandates the literal sentinel; the prompt previously said
# only "state so", dropping both the word "explicitly" and the quoted token.
def test_system_prompt_carries_the_unknown_sentinel_literal():
    assert '"Unknown"' in SYSTEM_PROMPT
    assert "explicitly state" in SYSTEM_PROMPT


# R12 / F-009: the coverage figure the vision prompt hands the model must be the
# ground half-width the 640px crop really spans -- 320 * m/px -- not the nominal
# tier request. At lat 20.965 / zoom 16 the real coverage is ~714m, not 1000m.
def test_prompt_states_real_ground_coverage_not_the_requested_tier():
    """
    R12 / F-009: the coverage line must state what the pixels cover.

    The visual_context fed in here is the one the pipeline actually builds for this
    incident. This test used to pass a nominal 1000.0 by hand, which pinned the
    renderer's arithmetic while exercising an input the production package no
    longer emits -- since F-009 the viewport stores the *real* coverage under
    radius_meters. That gap hid a clause which called the correct coverage figure a
    "nominal target only", i.e. it told the model not to trust the one number the
    line exists to establish.
    """
    viewport = calculate_incident_viewport(20.9650, 86.0110, observation_count=4)
    pkg = {
        "incident": {"incident_code": "INC-COV-001", "latitude": 20.9650, "longitude": 86.0110},
        "visual_context": {
            "radius_meters": viewport.radius_meters,
            "zoom_level": viewport.zoom_level,
            "provider": "Google Satellite",
        },
    }
    prompt = build_investigation_prompt(pkg)

    expected_half_width = crop_coverage_radius_meters(20.9650, 16, 640)
    assert abs(expected_half_width - 713.8) < 1.0  # pins the formula, not just the render
    # The production input is that same real coverage -- the premise of the test.
    assert abs(viewport.radius_meters - expected_half_width) < 1.0

    assert "~714m" in prompt
    assert "2.23 m/pixel" in prompt
    assert "radius ~1000m" not in prompt
    # ...and nothing may describe that figure as a request rather than a measurement.
    lowered = prompt.lower()
    assert "nominal" not in lowered
    assert "tier request" not in lowered

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


# ---------------------------------------------------------------------------
# 8. SYSTEM PROMPT TRANSMISSION & PROVIDER CASCADE (F-002, F-005, F-006, R9)
#
# These drive OpenRouterProvider.investigate() with a stubbed HTTP layer so the
# payloads that would really go on the wire can be inspected, and with a private
# KeyPoolManager so quarantine state never leaks into the shared singleton.
# ---------------------------------------------------------------------------
class _FakeHTTPResponse:
    """Minimal requests.Response stand-in for the OpenRouter call path."""

    def __init__(self, status_code: int, payload: dict = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _openrouter_ok_payload(classification: str = "industrial_fire") -> dict:
    return {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "classification": classification,
                    "confidence": 91.0,
                    "alternative": {"classification": "gas_flare", "confidence": 9.0},
                    "visual_evidence": ["Blast furnace plume inside plant perimeter"],
                    "contextual_evidence": ["FRP above the 365-day P95 ceiling"],
                    "uncertainties": ["Single pass"],
                    "image_quality": {"score": 88.5, "cloud_cover": "low", "visibility": "good"},
                    "needs_reinvestigation": False,
                    "reasoning_summary": "Process fire at the blast furnace."
                })
            }
        }]
    }


@pytest.fixture
def stub_openrouter(monkeypatch):
    """
    Captures every JSON payload the provider posts and replays a scripted list of
    responses. Also swaps the module-level key pool for a private one so cooldown
    state stays inside the test.
    """
    def _install(responses, keys=("key-A-1234567890", "key-B-1234567890")):
        captured = []
        pool = KeyPoolManager(api_keys=list(keys))
        monkeypatch.setattr(provider_module, "key_pool", pool)

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.append(json)
            index = min(len(captured) - 1, len(responses) - 1)
            return responses[index]

        monkeypatch.setattr(provider_module.requests, "post", fake_post)
        return captured, pool

    return _install


def test_system_message_is_first_message_and_carries_the_rule_block():
    provider = OpenRouterProvider()
    messages = provider._build_messages("ANALYSIS TARGET: ...", "data:image/png;base64,AAAA")

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "CRITICAL OPERATIONAL RULES (MANDATORY):" in messages[0]["content"]

    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "text"
    assert messages[1]["content"][0]["text"] == "ANALYSIS TARGET: ..."
    assert messages[1]["content"][1]["type"] == "image_url"


def test_system_message_reaches_the_wire_on_first_attempt_and_retry(stub_openrouter):
    captured, _pool = stub_openrouter([
        _FakeHTTPResponse(429, text="rate limit exceeded"),
        _FakeHTTPResponse(200, payload=_openrouter_ok_payload()),
    ])

    provider = OpenRouterProvider(model="test-model", max_retries=2)
    report = provider.investigate("ANALYSIS TARGET: TATA Steel 55.0 MW spike", "data:image/png;base64,AAAA")

    assert len(captured) == 2, "expected one retry after the 429"
    for payload in captured:
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == SYSTEM_PROMPT
        assert payload["messages"][1]["role"] == "user"

    assert report.classification == "industrial_fire"
    assert report.image_quality.score == 88.5


# F-005: a 429 must quarantine its key, so the retry lands on a different key and
# the quarantined one is not re-selected.
def test_429_on_the_wire_quarantines_the_key_and_moves_on(stub_openrouter):
    captured, pool = stub_openrouter([
        _FakeHTTPResponse(429, text="rate limit exceeded"),
        _FakeHTTPResponse(200, payload=_openrouter_ok_payload()),
    ])

    provider = OpenRouterProvider(model="test-model", max_retries=2)
    provider.investigate("ANALYSIS TARGET: ...", "data:image/png;base64,AAAA")

    assert len(captured) == 2
    assert abs(pool.cooldown_remaining_seconds(0) - 60.0) < 1.0
    assert pool.cooldown_remaining_seconds(1) == 0.0


# F-006: with every key exhausted/quarantined the provider must stop looping and
# reach the Deterministic Sovereign Mock Provider -- not hand-build a second,
# independent report. The mock supplies the report's shape; it must not supply a
# verdict about a scene no model looked at (see the neutrality test below).
def test_exhausted_pool_falls_through_to_the_deterministic_mock(stub_openrouter):
    captured, pool = stub_openrouter(
        [_FakeHTTPResponse(429, text="rate limit exceeded")],
        keys=("key-A-1234567890", "key-B-1234567890"),
    )

    prompt = "ANALYSIS TARGET: TATA Steel Kalinganagar 55.0 MW spike"
    provider = OpenRouterProvider(model="test-model", max_retries=4)
    report = provider.investigate(prompt, "data:image/png;base64,AAAA")

    # Two keys, four allowed attempts: the loop must stop once the pool is empty
    # rather than re-posting to a quarantined key.
    assert len(captured) == 2
    assert pool.get_current_key() == ""

    # The mock is the leg that ran, so its structure is what the report carries.
    direct_mock = MockAIProvider().investigate(prompt, "")
    assert report.visual_evidence == direct_mock.visual_evidence
    assert report.contextual_evidence == direct_mock.contextual_evidence
    assert report.reasoning_summary == direct_mock.reasoning_summary
    assert "mock" in (report.model_used or "").lower()
    assert report.needs_reinvestigation is True
    assert any("exhausted" in u.lower() for u in report.uncertainties)

    # ...but not its verdict. The mock's verdict here is "industrial_fire" at 88.0,
    # and both of those numbers are the mock guessing from the prompt's own text.
    assert direct_mock.classification == "industrial_fire"
    assert report.classification == "uncertain"
    assert report.alternative.classification == "uncertain"

    # An outage must not read as a confident one either: the fallback ceiling keeps
    # service.py's uncertainty tier out of "LOW".
    assert direct_mock.confidence == 88.0
    assert report.confidence == FALLBACK_CONFIDENCE_CEILING == 50.0


def test_outage_fallback_cannot_raise_the_ai_source_severity(stub_openrouter):
    """
    F-006 regression guard: an outage must not raise severity on evidence that
    does not exist.

    severity/service.py reads the incident's stored classification verbatim into
    calculate_ai_source_severity, so whatever the fallback report says here becomes
    a score. The mock's classification is a keyword match over the prompt -- for
    this prompt "industrial_fire", whose 92.0 base scores 71.0 at the capped
    confidence, against "uncertain"'s neutral 50.0. Delegating that value to the
    mock (which the F-006 fix did) therefore inflated the AI-source contribution,
    and the weighted final score with it, for every run in which no model ran.

    Non-vacuous: the same prompt scored through the mock alone is asserted to be
    strictly above neutral, so this fails if the guess is ever passed through again.
    """
    captured, pool = stub_openrouter(
        [_FakeHTTPResponse(429, text="rate limit exceeded")],
        keys=("key-A-1234567890",),
    )

    prompt = "ANALYSIS TARGET: TATA Steel Kalinganagar 55.0 MW spike"
    report = OpenRouterProvider(model="test-model", max_retries=2).investigate(
        prompt, "data:image/png;base64,AAAA"
    )

    assert report.classification == "uncertain"
    assert calculate_ai_source_severity(report.classification, report.confidence) == 50.0

    # The value that must not have leaked, and what it would have been worth.
    guess = MockAIProvider().investigate(prompt, "")
    assert guess.classification == "industrial_fire"
    assert calculate_ai_source_severity(guess.classification, report.confidence) > 50.0

    # Nothing else in the report may assert conditions for a crop nobody examined.
    assert report.image_quality.score == 50.0
    assert report.image_quality.cloud_cover == "medium"
    assert report.image_quality.visibility == "moderate"
    assert any("no model inspected this scene" in u.lower() for u in report.uncertainties)


