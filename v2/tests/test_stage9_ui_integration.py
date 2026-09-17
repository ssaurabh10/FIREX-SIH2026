"""
Unit & Integration Tests for Stage 9: Existing UI Integration + Industry Intelligence
Verifies that:
1. export_v1_dashboard_data populates all required Stage 9 fields into frontend incidents.json
2. Industry search & facility profile endpoints respond with complete metadata
3. Satellite persistence & history stats endpoints match the HUD contract
4. Analysis status & streaming routes function as expected
5. The /api/console/feed route the console boots from honours its contract
"""
import os
import json
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.storage.database import SessionLocal, Base, engine
from app.storage.models import Observation, Incident, IndustrialAsset, AIInvestigation, SeverityAssessment, AnalysisRun
from app.orchestration.pipeline import (
    export_v1_dashboard_data,
    FRONTEND_DATA_DIR,
    CONSOLE_ACTIVE_STATUSES,
    CONSOLE_CLOSED_STATUSES,
    UNRECONCILED_FACTOR_LABEL,
)
from app.incidents.state import VALID_STATES
from app.severity.scoring import score_to_level
from app.severity.state_machine import determine_lifecycle_state

# The tiers frontend/js/config.js:25-35 declares. `isTier` (:37) gates whether the
# console shows the tier the engine published or silently substitutes one it
# recomputed, so a tier outside this set is a payload the UI cannot label.
CONSOLE_TIERS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

# Fixed in-boundary coordinates for the fixtures this module creates: Delhi NCR
# for the facility test, and central Odisha (inside INDIAN_STATE_REGIONS
# ['Odisha'] = 17.8-22.6 N, 82.8-87.5 E, which resolve_admin_boundary maps to
# state 'Odisha', district 'Jajpur') for the history-search test.
ODISHA_LAT = 20.3000
ODISHA_LON = 85.1000


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


def test_console_queue_covers_every_lifecycle_status():
    """Every status an incident can hold is displayable somewhere.

    The console queue and the alert engine have to agree about which incidents
    are live, and they agree by sharing one whitelist. That whitelist had
    drifted from the state machine in both directions: ESCALATED -- which
    `determine_lifecycle_state` assigns to *every* CRITICAL detection, and which
    `alerts/engine.py` fires an `[ESCALATED]` alert for -- was absent, so ten
    live incidents were neither in the queue nor in the closed roll-up; and
    SUBSIDING had been dropped in an earlier fix. A status in neither list is an
    incident the console cannot show at all, which is J4 in its purest form.

    This is the assertion that would have caught both: it derives the vocabulary
    from the state machine rather than restating the list, so adding a status
    without deciding how the console shows it fails here instead of in the
    field.
    """
    displayed = set(CONSOLE_ACTIVE_STATUSES) | set(CONSOLE_CLOSED_STATUSES)
    undisplayable = VALID_STATES - displayed
    assert not undisplayable, (
        f"{sorted(undisplayable)} can be set on an incident -- the lifecycle "
        f"assigns it -- but appears in neither CONSOLE_ACTIVE_STATUSES nor "
        f"CONSOLE_CLOSED_STATUSES, so the console has no way to show it"
    )

    assert not (set(CONSOLE_ACTIVE_STATUSES) & set(CONSOLE_CLOSED_STATUSES)), (
        "a status cannot be both live and closed; the two whitelists overlap"
    )

    # The live half is exactly what the lifecycle can return while the incident
    # is burning: RESOLVED is closed, and every other state is reachable.
    assert set(CONSOLE_ACTIVE_STATUSES) == VALID_STATES - {"RESOLVED"}, (
        "CONSOLE_ACTIVE_STATUSES is not the lifecycle's own vocabulary minus "
        "RESOLVED; a status was added or dropped without the queue following"
    )

    # Every status the state machine can return is therefore either shown in the
    # live queue or in the closed roll-up -- and the CRITICAL path in particular
    # lands somewhere displayable.
    for status in VALID_STATES:
        assert determine_lifecycle_state(
            current_status=status, severity_level="LOW"
        ) in displayed, f"determine_lifecycle_state can return an unshowable status from {status}"
    assert determine_lifecycle_state(
        current_status="ACTIVE", severity_level="CRITICAL"
    ) in CONSOLE_ACTIVE_STATUSES, (
        "a CRITICAL detection is promoted to ESCALATED and must stay in the "
        "live queue rather than leaving it"
    )


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


def test_export_publishes_a_breakdown_only_when_it_adds_up(client, db_session):
    """Three records, three honest outcomes -- and no fourth.

    The export used to publish the fallback breakdown unconditionally, so a
    record whose incident carried no score at all went out with
    ``risk_score: 0.0`` beside rows worth 40-odd points, and a record whose
    assessment was written by the v1 schema went out with three rows of 0.0 that
    stated the current model had rated every factor at zero. Both are the same
    defect the assessment path was fixed for, one branch over: a breakdown that
    does not arrive at the number printed beside it.

    The rule now: either the rows sum to ``risk_score`` exactly, or there are no
    rows. Which of the two is decided by whether there is a score to break down
    at all.
    """
    unscored = Incident(
        id="test-inc-breakdown-none",
        incident_code="INC-STAGE9-NOSCORE",
        status="ACTIVE",
        latitude=ODISHA_LAT,
        longitude=ODISHA_LON,
        current_max_frp=41.0,
        first_detected_at=datetime.utcnow() - timedelta(hours=3),
        last_detected_at=datetime.utcnow(),
        observation_count=4,
        investigation_priority=50.0,
        severity_score=0.0,
        severity_level="LOW",
        classification="wildfire",
        classification_confidence=70.0,
        state="Odisha",
        district="Jajpur",
    )
    unassessed = Incident(
        id="test-inc-breakdown-fallback",
        incident_code="INC-STAGE9-UNASSESSED",
        status="ACTIVE",
        latitude=ODISHA_LAT,
        longitude=ODISHA_LON,
        current_max_frp=41.0,
        first_detected_at=datetime.utcnow() - timedelta(hours=3),
        last_detected_at=datetime.utcnow(),
        observation_count=4,
        investigation_priority=61.0,
        severity_score=61.0,
        severity_level="HIGH",
        classification="wildfire",
        classification_confidence=70.0,
        state="Odisha",
        district="Jajpur",
    )
    v1_assessed = Incident(
        id="test-inc-breakdown-v1",
        incident_code="INC-STAGE9-V1FACTORS",
        status="ACTIVE",
        latitude=ODISHA_LAT,
        longitude=ODISHA_LON,
        current_max_frp=41.0,
        first_detected_at=datetime.utcnow() - timedelta(hours=3),
        last_detected_at=datetime.utcnow(),
        observation_count=4,
        investigation_priority=48.0,
        severity_score=48.0,
        severity_level="MEDIUM",
        classification="wildfire",
        classification_confidence=70.0,
        state="Odisha",
        district="Jajpur",
    )
    for inc in (unscored, unassessed, v1_assessed):
        db_session.merge(inc)
    # The v1 schema's own key names -- what the shipped assessment rows looked
    # like before the model was rewritten, and what `_weighted_risk_factors`
    # cannot render as this model's contributions.
    db_session.merge(SeverityAssessment(
        incident_id=v1_assessed.id,
        score=48.0,
        level="MEDIUM",
        confidence=80.0,
        factors={"vision_ai": 25.0, "frp": 12.0, "facility_distance": 2.0},
        created_at=datetime.utcnow(),
    ))
    db_session.commit()

    try:
        export_v1_dashboard_data(db_session)
        with open(os.path.join(FRONTEND_DATA_DIR, "incidents.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        by_code = {row["incident_code"]: row for row in data}

        def tenths(rows):
            return sum(int(round(r["score"] * 10.0)) for r in rows)

        none_row = by_code["INC-STAGE9-NOSCORE"]
        assert none_row["risk_score"] == 0.0, none_row["risk_score"]
        assert none_row["risk_factors"] == [], (
            "a record with no score has nothing to break down; the fallback's "
            f"rows used to publish anyway: {none_row['risk_factors']}"
        )

        for code in ("INC-STAGE9-UNASSESSED", "INC-STAGE9-V1FACTORS"):
            row = by_code[code]
            assert row["risk_factors"], f"{code} must publish a breakdown"
            assert tenths(row["risk_factors"]) == int(round(row["risk_score"] * 10)), (
                f"{code}: rows sum to {tenths(row['risk_factors']) / 10} but the record "
                f"publishes {row['risk_score']}: {row['risk_factors']}"
            )
            named = [r for r in row["risk_factors"] if r["factor"] == UNRECONCILED_FACTOR_LABEL]
            assert len(named) == 1, (
                f"{code}: the fallback model's own sum differs from the engine's score, "
                f"so exactly one row must name the difference: {row['risk_factors']}"
            )
            assert named[0]["score"] < 0, (
                f"{code}: the fallback rates this detection above the engine's score, so "
                f"the reconciliation is a reduction: {named[0]}"
            )
    finally:
        db_session.query(SeverityAssessment).filter(
            SeverityAssessment.incident_id == v1_assessed.id
        ).delete()
        for inc in (unscored, unassessed, v1_assessed):
            db_session.query(Incident).filter(Incident.id == inc.id).delete()
        db_session.commit()
        export_v1_dashboard_data(db_session)


def test_console_feed_route_contract(client, db_session):
    """
    Pin the /api/console/feed payload the console boots from (E5, F-096).

    Section 12 credits this file with "Console data feed" (spec line 629) and no
    test requested the route -- ``grep -rn console/feed v2/tests/`` returned
    nothing. The route's only caller is ``frontend/js/data.js:34``, so a renamed
    key or a roll-up that stopped reconciling with the board it describes would
    reach the operator and no test would notice: the console's fallback path
    then serves ``data/incidents.json`` instead, which looks like an empty board
    rather than a broken route.

    The assertions are written against the *consumer's* contract rather than a
    copy of the producer's output: the four top-level keys are the ones
    ``data.js:38-54`` type-guards before it will adopt them, the per-row keys are
    the ones ``normaliseCase`` (:130-225) reads, and ``active_statuses`` is the
    whitelist that decides which incidents the queue may display at all (J4,
    where a status missing from it made the whole board read LOW).
    """
    marker = "INC-STAGE9-FEED"
    incumbent = Incident(
        id="test-inc-stage9-feed", incident_code=marker, status="ACTIVE",
        latitude=28.5010, longitude=77.2010, footprint_radius_meters=500.0,
        current_max_frp=42.0, current_mean_frp=42.0,
        first_detected_at=datetime.utcnow() - timedelta(hours=3),
        last_detected_at=datetime.utcnow(), observation_count=2,
        severity_score=58.0, severity_level="HIGH", severity_confidence=80.0,
        classification="industrial_fire", classification_confidence=88.0,
        state="Delhi NCR", district="South Delhi",
    )
    # A second incident, deliberately of a different investigation_priority. One
    # row cannot show whether priority_rank is a rank or a constant -- [1] is a
    # 1..1 permutation either way -- so the ordering assertions below need a pair
    # to have any content at all.
    rival = Incident(
        id="test-inc-stage9-feed-2", incident_code=marker + "-2", status="ACTIVE",
        latitude=28.5120, longitude=77.2120, footprint_radius_meters=500.0,
        current_max_frp=24.0, current_mean_frp=24.0,
        first_detected_at=datetime.utcnow() - timedelta(hours=1),
        last_detected_at=datetime.utcnow(), observation_count=1,
        investigation_priority=95.0,
        severity_score=31.0, severity_level="MEDIUM", severity_confidence=72.0,
        classification="gas_flare", classification_confidence=70.0,
        state="Delhi NCR", district="South Delhi",
    )
    # An observation this test owns, stamped newest so the ambient list (the 200
    # most recent sovereign detections) is guaranteed to hold it rather than
    # have the row-shape assertions vanish on an empty list.
    obs = Observation(
        id="obs-stage9-feed-01", latitude=28.5012, longitude=77.2012, frp_mw=42.0,
        acquired_at=datetime.utcnow(), satellite="N20", sensor="VIIRS",
        confidence_score=0.9,
    )
    db_session.merge(incumbent)
    db_session.merge(rival)
    db_session.merge(obs)
    db_session.commit()

    try:
        res = client.get("/api/console/feed")
        assert res.status_code == 200
        payload = res.json()

        # --- Top-level shape: exactly the guards data.js:38-54 applies --------
        assert isinstance(payload["incidents"], list)
        assert isinstance(payload["ambient"], list)
        assert isinstance(payload["queue_summary"], dict)
        assert isinstance(payload["closed_attention"], list)

        summary = payload["queue_summary"]
        incidents = payload["incidents"]

        # --- The roll-up must reconcile with the board it describes ----------
        # This is the J4 defect stated as an invariant: a queue summary that
        # disagrees with the queue it summarises is how the board read calm
        # while the alert feed held five CRITICAL alerts.
        assert summary["active_count"] == len(incidents), (
            f"queue_summary.active_count={summary['active_count']} but the feed "
            f"published {len(incidents)} incidents"
        )
        histogram = summary["tier_histogram"]
        assert set(histogram) <= CONSOLE_TIERS, (
            f"tier_histogram carries {sorted(set(histogram) - CONSOLE_TIERS)}, "
            f"which isTier (config.js:37) does not recognise"
        )
        assert sum(histogram.values()) == len(incidents), (
            f"tier_histogram sums to {sum(histogram.values())} over "
            f"{len(incidents)} incidents; a row's risk_tier missed the histogram"
        )
        assert summary["attention_count"] == histogram["HIGH"] + histogram["CRITICAL"]
        assert set(summary["active_statuses"]) == {
            "NEW", "INVESTIGATING", "ACTIVE", "PERSISTENT", "ESCALATED",
            "SUBSIDING", "REOPENED",
        }, (
            "the published queue whitelist changed; RESOLVED must stay out of the "
            "live queue, SUBSIDING must stay in it (J4), and ESCALATED -- which the "
            "lifecycle assigns to every CRITICAL detection -- must be displayable "
            "rather than excluded while the alert feed fires on it"
        )
        assert summary["closed_attention_count"] == len(payload["closed_attention"])

        # --- Universal per-row invariants, over every published incident -----
        for row in incidents:
            assert row["risk_tier"] in CONSOLE_TIERS, (
                f"{row['incident_code']} published risk_tier={row['risk_tier']!r}; "
                f"data.js:178 then silently substitutes a tier it recomputed"
            )
            # The tier the engine publishes and the tier its own band function
            # derives from the same score must agree -- otherwise every case
            # raises a "these bands say" notice in the console (checkTiers,
            # data.js:110-119).
            assert row["risk_tier"] == score_to_level(row["risk_score"]), (
                f"{row['incident_code']} scored {row['risk_score']} but published "
                f"{row['risk_tier']}"
            )
            # The score published is the severity engine's own -- the number that
            # set this row's level and that the alert was raised against. The
            # export used to replace it with the sum of the rendered factors
            # whenever the two differed by more than 0.15, which published
            # contradictions both ways: INC-2026-0348 went out as score 70.5 /
            # tier HIGH beside severity_level CRITICAL, and a routine flare went
            # out at 34.2 when INV-4 caps it at 20.0.
            if row["severity_level"] is not None:
                assert row["risk_score"] == round(float(row["severity_score"]), 1), (
                    f"{row['incident_code']} published risk_score="
                    f"{row['risk_score']} beside severity_score="
                    f"{row['severity_score']}; the breakdown is not a second vote "
                    f"on the engine's score"
                )
                # And the level and the score must not contradict each other --
                # the pair is banded from the same rounded value so that the
                # console's checkTiers (data.js:110-119) never has to reconcile
                # them for the operator.
                assert row["severity_level"] == score_to_level(row["severity_score"]), (
                    f"{row['incident_code']} records severity_score="
                    f"{row['severity_score']} as {row['severity_level']}"
                )
            # The breakdown is what the dossier shows as the explanation for the
            # score, so it has to arrive there. Not approximately: the rows are
            # apportioned to the tenth they are displayed at.
            if row["risk_factors"]:
                rows_tenths = sum(
                    int(round(f["score"] * 10.0)) for f in row["risk_factors"]
                )
                assert rows_tenths == int(round(row["risk_score"] * 10.0)), (
                    f"{row['incident_code']}: risk_factors sum to "
                    f"{rows_tenths / 10.0} but risk_score is {row['risk_score']}"
                )
            assert row["status"] in summary["active_statuses"], (
                f"{row['incident_code']} is {row['status']}, which the published "
                f"active_statuses whitelist excludes; the queue is leaking a "
                f"non-live incident"
            )
            # INV-2 at the payload level: no published key may assert a total.
            # This is the assertion that would have caught `cluster_total_frp`,
            # which carried the incident maximum under a name claiming a sum
            # (report F-item, pipeline.py:312).
            offending = [k for k in row if "total" in k.lower()]
            assert not offending, (
                f"{row['incident_code']} publishes {offending}; INV-2 forbids any "
                f"summed (or sum-named) FRP in the payload"
            )
            assert row["cluster_max_frp"] == row["frp"], (
                f"{row['incident_code']} publishes frp={row['frp']} and "
                f"cluster_max_frp={row['cluster_max_frp']}; both must be the "
                f"incident maximum"
            )

        # --- Priority ordering ------------------------------------------------
        # data.js:150 sorts the published queue by this field
        # (`rank: Number(raw.priority_rank) || 99`, then
        # `sort((a, b) => a.rank - b.rank)`), so a constant here is a queue that
        # is never actually ordered -- which is what the committed payload
        # shipped: all 319 records carried priority_rank 1 while their
        # investigation_priority spanned 118 distinct values from 0 to 90, because
        # Incident has no such column and the producer's getattr default is 1
        # (F-100). Ranks must therefore be a 1..N permutation that follows
        # investigation_priority descending.
        ranks = sorted(r["priority_rank"] for r in incidents)
        assert ranks == list(range(1, len(incidents) + 1)), (
            f"priority_rank is not a 1..{len(incidents)} permutation: {ranks[:8]}; "
            f"the console's queue sort is a no-op when every record ranks the same"
        )
        by_rank = sorted(incidents, key=lambda r: r["priority_rank"])
        priorities = [r["investigation_priority"] for r in by_rank]
        assert priorities == sorted(priorities, reverse=True), (
            "priority_rank does not follow investigation_priority descending, so "
            "the console's most-investigable case is not the one it shows first"
        )

        # --- The row this test owns: every key normaliseCase reads -----------
        mine = next((r for r in incidents if r["incident_code"] == marker), None)
        assert mine is not None, (
            f"{marker} is ACTIVE and inside the sovereign envelope but the feed "
            f"did not publish it"
        )
        for key in ("id", "incident_code", "latitude", "longitude", "frp",
                    "risk_score", "risk_tier", "priority_rank",
                    "investigation_priority", "priority_explanation",
                    "ai_classification", "ai_confidence", "ai_uncertainty",
                    "ai_evidence", "ai_reasoning", "severity_score",
                    "severity_level", "action_recommendation", "risk_factors",
                    "baseline_median", "baseline_p95", "active_days_365d",
                    "is_routine_flare", "historical_anomaly", "status",
                    "image_url", "raw_image_url"):
            assert key in mine, f"console feed row is missing {key!r}"

        assert isinstance(mine["ai_evidence"], list)
        assert isinstance(mine["risk_factors"], list) and mine["risk_factors"], (
            "risk_factors must be a non-empty list; dossier.js:84-95 renders each "
            "row's name/score/max/detail"
        )
        for factor in mine["risk_factors"]:
            for key in ("factor", "score", "max", "detail"):
                assert key in factor, (
                    f"risk factor {factor!r} is missing {key!r}; "
                    f"data.js:182-189 reads exactly these four"
                )
        assert 0.0 <= mine["risk_score"] <= 100.0
        assert isinstance(mine["priority_rank"], int)
        assert mine["image_url"] == f"/crops/{mine['id']}/annotated.jpg"

        # --- Ambient rows carry the short keys normaliseAmbient reads --------
        mine_obs = next((a for a in payload["ambient"] if a["lat"] == obs.latitude), None)
        assert mine_obs is not None, (
            "the newest observation in the test database is absent from the "
            "ambient list, so the ambient half of the feed is unverified"
        )
        for key in ("lat", "lon", "frp", "conf", "sat", "date", "time"):
            assert key in mine_obs, f"ambient row is missing {key!r}"
    finally:
        db_session.query(Incident).filter(
            Incident.id.in_([incumbent.id, rival.id])
        ).delete(synchronize_session=False)
        db_session.query(Observation).filter(Observation.id == obs.id).delete()
        db_session.commit()


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


def test_history_search_api(client, db_session):
    """
    Tests /api/history/search endpoint verifying:
    1. Filter by state (Odisha) and min_frp returns filtered observation rows.
    2. Enriched sovereign boundaries (state, district) and nearest industrial asset.
    3. Aggregate telemetry summary metrics (min_frp, max_frp, mean_frp, total_matches).
    4. Text query matching works.

    The row-shape block used to sit inside ``if payload["returned"] > 0:`` and the
    only unconditional assertions were three key-presence checks and
    ``returned <= 3`` -- so on a database with no Odisha detections the test
    asserted nothing about a row while still reporting green (E6, F-090). It now
    creates the two Odisha detections it needs and asserts against them.
    """
    obs_ids = ["obs-stage9-search-01", "obs-stage9-search-02"]
    # min_frp=15.0 is the filter under test, so seed one row above it and one
    # below it to show the filter does something rather than merely being echoed.
    seeded = [
        (obs_ids[0], ODISHA_LAT, ODISHA_LON, 61.0),
        (obs_ids[1], ODISHA_LAT + 0.01, ODISHA_LON + 0.01, 3.0),
    ]
    for obs_id, lat, lon, frp in seeded:
        db_session.merge(Observation(
            id=obs_id, latitude=lat, longitude=lon, frp_mw=frp,
            acquired_at=datetime.utcnow(), satellite="N20", sensor="VIIRS",
            confidence_score=0.9,
        ))
    db_session.commit()

    try:
        res = client.get("/api/history/search?state=Odisha&min_frp=15.0&limit=5")
        assert res.status_code == 200
        payload = res.json()
        assert "total_matches" in payload
        assert "results" in payload
        assert "summary" in payload
        assert payload["returned"] <= 5
        # `returned` is the page size, `total_matches` the match count: they are
        # different quantities and a route that reported one for the other would
        # leave the console claiming 5 results out of 5 when it holds thousands.
        assert payload["returned"] == len(payload["results"])
        assert payload["total_matches"] >= payload["returned"]

        # The seeded rows make this block unconditional. Odisha holds exactly
        # these two detections in the isolated database, so the filter's effect
        # is observable in both directions.
        returned_ids = {row["id"] for row in payload["results"]}
        assert obs_ids[0] in returned_ids, (
            "the 61.0 MW Odisha detection above min_frp=15.0 was not returned"
        )
        assert obs_ids[1] not in returned_ids, (
            "the 3.0 MW Odisha detection was returned despite min_frp=15.0"
        )
        assert payload["returned"] == 1, (
            f"expected exactly the 61.0 MW detection, got {payload['returned']}"
        )

        row = payload["results"][0]
        assert row["latitude"] == pytest.approx(ODISHA_LAT, abs=1e-4)
        assert row["longitude"] == pytest.approx(ODISHA_LON, abs=1e-4)
        assert row["frp_mw"] >= 15.0
        # The enrichment claim, asserted rather than merely key-checked: the
        # route was asked for Odisha and must resolve the row's own
        # administrative position, not echo the query back. `state` defaults to
        # "India" and `district` to "Unknown" when resolution fails
        # (history.py:346-347), so key presence alone accepts a total failure.
        assert row["state"] == "Odisha", f"admin resolution returned {row['state']!r}"
        assert row["district"] not in (None, "", "Unknown"), (
            "district enrichment did not resolve"
        )
        assert "nearest_facility" in row
        assert "distance_km" in row

        # The summary must describe the rows it accompanies, not the filter.
        assert payload["summary"]["max_frp"] == pytest.approx(row["frp_mw"])
        assert payload["summary"]["mean_frp"] == pytest.approx(row["frp_mw"])
        assert payload["summary"]["state_filter"] == "Odisha"

        # Test query filter
        q_res = client.get("/api/history/search?query=Refinery&limit=3")
        assert q_res.status_code == 200
        q_payload = q_res.json()
        assert "results" in q_payload
        assert q_payload["returned"] <= 3
        assert q_payload["returned"] == len(q_payload["results"])
    finally:
        db_session.query(Observation).filter(Observation.id.in_(obs_ids)).delete(
            synchronize_session=False
        )
        db_session.commit()

