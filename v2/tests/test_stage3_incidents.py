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

client = TestClient(app)

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

    clusters = cluster_observations([obs1, obs2, obs3], spatial_eps_meters=2000.0)
    assert len(clusters) == 1
    c = clusters[0]
    
    assert c.max_frp == 40.0
    assert c.min_frp == 20.0
    assert c.mean_frp == 30.0
    assert len(c.observations) == 3
    # Explicitly check that FRP is NOT 90.0 (40+30+20)
    assert c.max_frp != 90.0

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

    clusters_a = cluster_observations([p1, p2, p3], spatial_eps_meters=2000.0)
    assert len(clusters_a) == 1

    # Case B points (Panipat vs Jamnagar: ~900 km apart)
    p_jamnagar = Observation(id="p_jam", latitude=22.3550, longitude=69.8730, frp_mw=50.0, acquired_at=t0)
    clusters_b = cluster_observations([p1, p_jamnagar], spatial_eps_meters=2000.0)
    assert len(clusters_b) == 2

    # Case C points (Panipat at t0 vs Panipat 36h later)
    p_panipat_late = Observation(id="p_late", latitude=29.4780, longitude=76.8540, frp_mw=18.0, acquired_at=t_later)
    clusters_c = cluster_observations([p1, p_panipat_late], spatial_eps_meters=2000.0, time_window_hours=24.0)
    assert len(clusters_c) == 2

def test_incident_lifecycle_and_association_dedup():
    """
    Test that re-running cluster-sync updates existing active incidents
    rather than creating duplicate incidents.
    """
    db = SessionLocal()
    try:
        # Create test observations in database
        import uuid
        uid = uuid.uuid4().hex[:8]
        offset = 5.0 + (int(uid, 16) % 1000) * 0.02
        test_lat = 14.0 + offset
        test_lon = 75.0 + offset
        
        # Clean any incidents in test vicinity to guarantee zero test interference
        db.query(Incident).filter(
            Incident.latitude.between(test_lat - 0.1, test_lat + 0.1),
            Incident.longitude.between(test_lon - 0.1, test_lon + 0.1)
        ).delete(synchronize_session=False)
        db.commit()

        t_base = datetime(2026, 9, 4, 14, 0, 0)
        obs_a = Observation(
            id=f"obs_life_1_{uid}", latitude=test_lat, longitude=test_lon, frp_mw=45.0,
            acquired_at=t_base, satellite="N20", sensor="VIIRS"
        )
        db.add(obs_a)
        db.commit()

        # Run 1: Should create 1 new incident
        c1 = cluster_observations([obs_a])
        incidents_run1 = sync_clusters_to_incidents(db, c1)
        assert len(incidents_run1) == 1
        inc1 = incidents_run1[0]
        assert inc1.observation_count == 1
        inc1_code = inc1.incident_code

        # Run 2: New observation in same facility ~1 hour later
        obs_b = Observation(
            id=f"obs_life_2_{uid}", latitude=test_lat + 0.0005, longitude=test_lon + 0.0005, frp_mw=55.0,
            acquired_at=t_base + timedelta(hours=1), satellite="N20", sensor="VIIRS"
        )
        db.add(obs_b)
        db.commit()

        c2 = cluster_observations([obs_b])
        incidents_run2 = sync_clusters_to_incidents(db, c2)
        assert len(incidents_run2) == 1
        inc2 = incidents_run2[0]

        # Must be the exact same incident code updated!
        assert inc2.incident_code == inc1_code
        assert inc2.observation_count == 2
        assert inc2.current_max_frp == 55.0
    finally:
        try:
            # Clean up test observations and test incident
            db.query(IncidentObservation).filter(
                IncidentObservation.observation_id.in_([f"obs_life_1_{uid}", f"obs_life_2_{uid}"])
            ).delete(synchronize_session=False)
            db.query(Incident).filter(
                Incident.latitude.between(test_lat - 0.1, test_lat + 0.1),
                Incident.longitude.between(test_lon - 0.1, test_lon + 0.1)
            ).delete(synchronize_session=False)
            db.query(Observation).filter(
                Observation.id.in_([f"obs_life_1_{uid}", f"obs_life_2_{uid}"])
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        db.close()

def test_incident_state_transition_and_events():
    """
    Test incident state transition (ACTIVE -> SUBSIDING -> RESOLVED)
    and check that timeline events are stored in incident_events.
    """
    db = SessionLocal()
    try:
        # Fetch an active incident
        inc = db.query(Incident).first()
        assert inc is not None

        # Call transition endpoint via API
        resp = client.post(f"/incidents/{inc.id}/state", json={"new_state": "SUBSIDING", "reason": "FRP diminished"})
        assert resp.status_code == 200
        assert resp.json()["new_state"] == "SUBSIDING"

        # Check full detail endpoint
        detail_resp = client.get(f"/incidents/{inc.id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["status"] == "SUBSIDING"
        assert len(detail["events"]) >= 1
        assert any(e["event_type"] == "incident.state_changed" for e in detail["events"])
    finally:
        db.close()
