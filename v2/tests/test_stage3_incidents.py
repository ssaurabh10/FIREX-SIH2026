"""
Automated Test Suite for Stage 3: Clustering + Incident Lifecycle
Tests & Invariant Verification:
1. Hard Rule Verification:
   Assert that in a multi-observation cluster, FRPs are NEVER summed.
   Assert current_max_frp, current_mean_frp, and raw observation FRPs are preserved.
2. Case A: 3 nearby observations at nearly the same time -> 1 cluster.
3. Case B: 2 distant observations -> 2 separate clusters.
4. Case C: Same location but separated in time (> 24h) -> 2 separate clusters.
5. Case D: Re-running ingestion/clustering updates the existing active incident rather than creating a duplicate.
6. Case E: State transitions (ACTIVE -> SUBSIDING -> RESOLVED) and audit event recording in incident_events.
7. Endpoints:
   - GET /incidents
   - GET /incidents/{id} (returns linked observations + audit events)
   - POST /incidents/cluster-sync
   - POST /incidents/{id}/state
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.storage.database import SessionLocal, engine
from app.storage.models import Base, Observation, Incident, IncidentObservation, IncidentEvent
from app.incidents.clustering import cluster_observations
from app.incidents.association import sync_clusters_to_incidents
from app.gis.assets import seed_industrial_assets
from app.gis.boundaries import is_within_indian_sovereign_territory

client = TestClient(app)

# Fixed coordinates for the lifecycle and state-transition tests: Panipat,
# Haryana (IOCL refinery complex), deep inland inside the Invariant-3 envelope.
# These were previously derived from a random uuid, which scattered the test
# point over 19.0-38.98N / 80.0-99.98E -- mostly open ocean and territory the
# sovereign filter rightly rejects -- so the run failed at random when the
# association engine discarded the cluster.
TEST_LAT = 29.4780
TEST_LON = 76.8540
TEST_INCIDENT_CODE = "INC-TEST-STATE-0001"
# A fixed half-width for the "is this our test incident" cleanup window: ~5.5 km,
# comfortably beyond the association engine's 3000 m spatial threshold.
TEST_CLEANUP_DEGREES = 0.05

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_industrial_assets(db)
    finally:
        db.close()
    yield

def test_hard_rule_frp_non_summation_invariant():
    """
    Hard Rule:
    FRP1 + FRP2 + FRP3 = incident FRP  ❌
    max_frp, mean_frp, and count must be derived statistics.
    """
    now = datetime(2026, 9, 3, 10, 0, 0)
    
    # 3 observations close to each other in Bathinda (~200m apart)
    obs1 = Observation(
        id="obs_test_1", latitude=29.9100, longitude=74.9520, frp_mw=40.0,
        acquired_at=now, satellite="N20", sensor="VIIRS", confidence_score=0.9
    )
    obs2 = Observation(
        id="obs_test_2", latitude=29.9105, longitude=74.9525, frp_mw=30.0,
        acquired_at=now + timedelta(minutes=5), satellite="N20", sensor="VIIRS", confidence_score=0.9
    )
    obs3 = Observation(
        id="obs_test_3", latitude=29.9095, longitude=74.9515, frp_mw=20.0,
        acquired_at=now + timedelta(minutes=10), satellite="N20", sensor="VIIRS", confidence_score=0.9
    )

    # Exercise the function's own defaults here: Section 4.3
    # (V2_LOGIC_SPECIFICATION.md:129) pins reachability at eps_s = 1500 m and
    # tau = 24.0 h, and these three points are ~100 m apart.
    clusters = cluster_observations([obs1, obs2, obs3])
    assert len(clusters) == 1
    c = clusters[0]
    
    assert c.max_frp == 40.0
    assert c.min_frp == 20.0
    assert c.mean_frp == 30.0
    assert len(c.observations) == 3

    # INV-2 (V2_LOGIC_SPECIFICATION.md:30) says FRP "MUST NEVER BE SUMMED".
    # The assertion that used to sit here -- `assert c.max_frp != 90.0` -- was
    # entailed by the `== 40.0` above it (40.0 != 90.0 for any implementation
    # that computes a max at all), so it could not fail and guarded nothing (E2,
    # F-082). Assert the derivation instead: the statistics are recomputed here
    # from the member observations, so a refactor that returned a sum, or that
    # aliased max onto a total, fails regardless of the literals above.
    member_frps = [o.frp_mw for o in c.observations]
    assert c.max_frp == max(member_frps)
    assert c.min_frp == min(member_frps)
    assert c.mean_frp == pytest.approx(sum(member_frps) / len(member_frps))
    # The one derivation INV-2 forbids, stated directly: no published statistic
    # may equal the sum of the members.
    total = sum(member_frps)
    assert c.max_frp != total
    assert c.mean_frp != total
    assert not hasattr(c, "total_frp")

def test_clustering_cases_a_b_c():
    """
    Case A: 3 nearby points -> 1 cluster
    Case B: 2 distant points -> 2 clusters
    Case C: Same location but distant time (>24h) -> 2 clusters
    """
    t0 = datetime(2026, 9, 3, 12, 0, 0)
    t_later = t0 + timedelta(hours=36)  # 36 hours later

    # Case A points (Panipat IOCL)
    p1 = Observation(id="p1", latitude=29.4780, longitude=76.8540, frp_mw=15.0, acquired_at=t0)
    p2 = Observation(id="p2", latitude=29.4790, longitude=76.8550, frp_mw=25.0, acquired_at=t0)
    p3 = Observation(id="p3", latitude=29.4770, longitude=76.8530, frp_mw=10.0, acquired_at=t0)

    clusters_a = cluster_observations([p1, p2, p3], spatial_eps_meters=1500.0)
    assert len(clusters_a) == 1

    # Case B points (Panipat vs Jamnagar: ~900 km apart)
    p_jamnagar = Observation(id="p_jam", latitude=22.3550, longitude=69.8730, frp_mw=50.0, acquired_at=t0)
    clusters_b = cluster_observations([p1, p_jamnagar], spatial_eps_meters=1500.0)
    assert len(clusters_b) == 2

    # Case C points (Panipat at t0 vs Panipat 36h later)
    p_panipat_late = Observation(id="p_late", latitude=29.4780, longitude=76.8540, frp_mw=18.0, acquired_at=t_later)
    clusters_c = cluster_observations([p1, p_panipat_late], spatial_eps_meters=1500.0, time_window_hours=24.0)
    assert len(clusters_c) == 2


def test_clustering_reachability_boundary_at_shipped_epsilon():
    """
    Exercise the 1500 m reachability boundary itself (E8, F-094).

    Section 4.3 (V2_LOGIC_SPECIFICATION.md:129) pins epsilon_s = 1500 m and the
    shipped pipeline passes exactly that (orchestration/pipeline.py:923). Every
    clustering test here used to run at the function default, so no test placed
    a pair on either side of the boundary the production path actually uses --
    the one distance at which a change to epsilon_s, or to the `<=` comparison
    in clustering.py, would silently start merging detections the spec keeps
    apart.

    Offsets are pure latitude and the resulting ground distances are stated
    against the same earth radius the clustering code uses (EARTH_RADIUS_METERS
    = 6371000.0 in gis/spatial.py), so these figures are exact rather than
    approximate.
    """
    t0 = datetime(2026, 9, 3, 12, 0, 0)

    def obs(obs_id, dlat):
        return Observation(
            id=obs_id, latitude=TEST_LAT + dlat, longitude=TEST_LON,
            frp_mw=20.0, acquired_at=t0, satellite="N20", sensor="VIIRS"
        )

    # 1389.9 m apart -- inside epsilon_s, must be one cluster.
    inside = cluster_observations(
        [obs("b_in_a", 0.0), obs("b_in_b", 0.0125)], spatial_eps_meters=1500.0
    )
    assert len(inside) == 1, "1389.9 m pair was split; epsilon_s is 1500 m"

    # 1501.1 m apart -- the first offset past epsilon_s, must stay two clusters.
    # This is the pair that pins the comparison as inclusive (`<=`): the boundary
    # point is reachable, one metre beyond it is not.
    outside = cluster_observations(
        [obs("b_out_a", 0.0), obs("b_out_b", 0.0135)], spatial_eps_meters=1500.0
    )
    assert len(outside) == 2, "1501.1 m pair was merged; epsilon_s is 1500 m"

    # 1601.2 m apart -- the case the shipped pipeline must never merge.
    far = cluster_observations(
        [obs("b_far_a", 0.0), obs("b_far_b", 0.0144)], spatial_eps_meters=1500.0
    )
    assert len(far) == 2, "1601.2 m pair was merged; the shipped pipeline uses 1500 m"

def test_incident_lifecycle_and_association_dedup():
    """
    Test that re-running cluster-sync updates existing active incidents
    rather than creating duplicate incidents.

    Runs on fixed in-boundary coordinates (Panipat, Haryana) that the test
    owns: it clears the point beforehand, creates its own observations, and
    tears the incident, its links and its events down again afterwards.
    """
    db = SessionLocal()
    obs_ids = ["obs_life_1_stage3", "obs_life_2_stage3"]
    incident_ids = []
    try:
        # The test point must sit inside Indian sovereign territory, otherwise
        # association now (correctly) discards the cluster and there is nothing
        # to assert. Fail loudly here rather than three frames down.
        assert is_within_indian_sovereign_territory(TEST_LAT, TEST_LON), (
            f"lifecycle test coordinates ({TEST_LAT}, {TEST_LON}) are outside "
            "Indian sovereign territory; pick an inland test point"
        )

        # Clean any incidents in test vicinity to guarantee zero test interference
        stale_ids = [
            row[0]
            for row in db.query(Incident.id).filter(
                Incident.latitude.between(TEST_LAT - TEST_CLEANUP_DEGREES, TEST_LAT + TEST_CLEANUP_DEGREES),
                Incident.longitude.between(TEST_LON - TEST_CLEANUP_DEGREES, TEST_LON + TEST_CLEANUP_DEGREES)
            ).all()
        ]
        if stale_ids:
            db.query(IncidentObservation).filter(
                IncidentObservation.incident_id.in_(stale_ids)
            ).delete(synchronize_session=False)
            db.query(IncidentEvent).filter(
                IncidentEvent.incident_id.in_(stale_ids)
            ).delete(synchronize_session=False)
            db.query(Incident).filter(
                Incident.id.in_(stale_ids)
            ).delete(synchronize_session=False)
        db.query(Observation).filter(Observation.id.in_(obs_ids)).delete(synchronize_session=False)
        db.commit()

        t_base = datetime(2026, 9, 4, 14, 0, 0)
        obs_a = Observation(
            id=obs_ids[0], latitude=TEST_LAT, longitude=TEST_LON, frp_mw=45.0,
            acquired_at=t_base, satellite="N20", sensor="VIIRS"
        )
        db.add(obs_a)
        db.commit()

        # Run 1: Should create 1 new incident
        c1 = cluster_observations([obs_a])
        incidents_run1 = sync_clusters_to_incidents(db, c1)
        assert len(incidents_run1) == 1
        inc1 = incidents_run1[0]
        incident_ids.append(inc1.id)
        assert inc1.observation_count == 1
        assert inc1.incident_code
        inc1_code = inc1.incident_code
        # The incident must be anchored on the coordinates we actually supplied
        assert inc1.latitude == pytest.approx(TEST_LAT)
        assert inc1.longitude == pytest.approx(TEST_LON)

        # Run 2: New observation in same facility ~1 hour later
        obs_b = Observation(
            id=obs_ids[1], latitude=TEST_LAT + 0.0005, longitude=TEST_LON + 0.0005, frp_mw=55.0,
            acquired_at=t_base + timedelta(hours=1), satellite="N20", sensor="VIIRS"
        )
        db.add(obs_b)
        db.commit()

        c2 = cluster_observations([obs_b])
        incidents_run2 = sync_clusters_to_incidents(db, c2)
        assert len(incidents_run2) == 1
        inc2 = incidents_run2[0]
        incident_ids.append(inc2.id)

        # Must be the exact same incident code updated!
        assert inc2.id == inc1.id
        assert inc2.incident_code == inc1_code
        assert inc2.observation_count == 2
        assert inc2.current_max_frp == 55.0
        # An update must not re-anchor the incident on the new observation
        assert inc2.latitude == pytest.approx(TEST_LAT)
        assert inc2.longitude == pytest.approx(TEST_LON)

        # Both observations are linked to the same incident
        linked = (
            db.query(IncidentObservation.observation_id)
            .filter(IncidentObservation.incident_id == inc1.id)
            .all()
        )
        assert sorted(row[0] for row in linked) == sorted(obs_ids)
    finally:
        try:
            # Clean up this test's incident chain and observations
            if incident_ids:
                db.query(IncidentObservation).filter(
                    IncidentObservation.incident_id.in_(incident_ids)
                ).delete(synchronize_session=False)
                db.query(IncidentEvent).filter(
                    IncidentEvent.incident_id.in_(incident_ids)
                ).delete(synchronize_session=False)
                db.query(Incident).filter(
                    Incident.id.in_(incident_ids)
                ).delete(synchronize_session=False)
            db.query(IncidentObservation).filter(
                IncidentObservation.observation_id.in_(obs_ids)
            ).delete(synchronize_session=False)
            db.query(Observation).filter(
                Observation.id.in_(obs_ids)
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        db.close()

def test_incident_state_transition_and_events():
    """
    Test incident state transition (ACTIVE -> SUBSIDING -> RESOLVED)
    and check that timeline events are stored in incident_events.

    The test creates the incident it transitions and removes it (with its
    events) afterwards. It used to take `db.query(Incident).first()` and drive
    a SUBSIDING transition on whichever row happened to sort first, permanently
    mutating a real record and depending on incidental live data.
    """
    db = SessionLocal()
    inc_id = None
    try:
        # Pre-clean: a previous interrupted run must not collide with the
        # incident_code unique constraint.
        stale_ids = [
            row[0]
            for row in db.query(Incident.id).filter(
                Incident.incident_code == TEST_INCIDENT_CODE
            ).all()
        ]
        if stale_ids:
            db.query(IncidentObservation).filter(
                IncidentObservation.incident_id.in_(stale_ids)
            ).delete(synchronize_session=False)
            db.query(IncidentEvent).filter(
                IncidentEvent.incident_id.in_(stale_ids)
            ).delete(synchronize_session=False)
            db.query(Incident).filter(
                Incident.id.in_(stale_ids)
            ).delete(synchronize_session=False)
            db.commit()

        detected_at = datetime(2026, 9, 4, 14, 0, 0)
        inc = Incident(
            incident_code=TEST_INCIDENT_CODE,
            status="ACTIVE",
            latitude=TEST_LAT,
            longitude=TEST_LON,
            footprint_radius_meters=500.0,
            first_detected_at=detected_at,
            last_detected_at=detected_at,
            observation_count=1,
            current_max_frp=12.5,
            current_mean_frp=12.5,
            created_at=datetime.utcnow()
        )
        db.add(inc)
        db.commit()
        inc_id = inc.id

        # ACTIVE -> SUBSIDING via the API
        resp = client.post(f"/incidents/{inc_id}/state", json={"new_state": "SUBSIDING", "reason": "FRP diminished"})
        assert resp.status_code == 200
        assert resp.json()["new_state"] == "SUBSIDING"

        # The API committed through its own session; drop this session's cached
        # copies so the assertions read what was actually persisted.
        db.expire_all()

        events = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.incident_id == inc_id)
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "incident.state_changed"
        assert events[0].payload["from_state"] == "ACTIVE"
        assert events[0].payload["to_state"] == "SUBSIDING"
        assert events[0].payload["reason"] == "FRP diminished"
        assert db.get(Incident, inc_id).status == "SUBSIDING"

        # SUBSIDING -> RESOLVED
        resp = client.post(f"/incidents/{inc_id}/state", json={"new_state": "RESOLVED", "reason": "Terminated"})
        assert resp.status_code == 200
        assert resp.json()["new_state"] == "RESOLVED"

        db.expire_all()
        events = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.incident_id == inc_id)
            .all()
        )
        assert len(events) == 2
        ordered = sorted(events, key=lambda e: e.payload["timestamp"])
        assert (ordered[0].payload["from_state"], ordered[0].payload["to_state"]) == ("ACTIVE", "SUBSIDING")
        assert (ordered[1].payload["from_state"], ordered[1].payload["to_state"]) == ("SUBSIDING", "RESOLVED")

        # Check the full detail endpoint returns the same timeline
        detail_resp = client.get(f"/incidents/{inc_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["status"] == "RESOLVED"
        assert len(detail["events"]) == 2
        assert all(e["event_type"] == "incident.state_changed" for e in detail["events"])
    finally:
        try:
            if inc_id:
                db.query(IncidentEvent).filter(
                    IncidentEvent.incident_id == inc_id
                ).delete(synchronize_session=False)
                db.query(Incident).filter(
                    Incident.id == inc_id
                ).delete(synchronize_session=False)
                db.commit()
        except Exception:
            db.rollback()
        db.close()

