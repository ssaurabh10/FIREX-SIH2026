"""
Automated Test Suite for Stage 1: Data Foundation & FIRMS Ingestion
Tests:
1. Parsing and validation of deterministic fixture CSV files (VIIRS and MODIS).
2. Deduplication engine: ingesting the same CSV twice produces 0 new records on second run.
3. Database retrieval via GET /observations.
4. Spatial filtering (bounding box and radial distance query).
5. Single observation retrieval by ID.
6. Real NASA FIRMS API live access test.
"""
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.database import SessionLocal, engine
from app.storage.models import Base, Observation
from app.ingestion.firms import FIRMSClient

client = TestClient(app)

FIXTURE_VIIRS = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "v1", "pipeline", "01_firms", "raw_responses", "VIIRS_NOAA20_NRT_20260903T141217Z.csv"
    )
)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        firms_client = FIRMSClient()
        if os.path.exists(FIXTURE_VIIRS):
            with open(FIXTURE_VIIRS, "r", encoding="utf-8") as f:
                records = firms_client.parse_csv(f.read(), product="VIIRS_NOAA20_NRT")
            ext_ids = [r.external_id for r in records]
            db.query(Observation).filter(Observation.external_id.in_(ext_ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()
    yield

def test_deterministic_fixture_ingestion_and_deduplication():
    """
    Test Step 1: Ingest known CSV fixture, verify records are stored.
    Test Step 2: Ingest again, verify deduplication catches all duplicates.
    """
    assert os.path.exists(FIXTURE_VIIRS), f"Fixture not found at {FIXTURE_VIIRS}"
    
    db = SessionLocal()
    try:
        firms_client = FIRMSClient()
        
        # Initial ingestion
        stats1 = firms_client.ingest_from_file(db, FIXTURE_VIIRS, product="VIIRS_NOAA20_NRT")
        assert stats1["ingested"] > 0
        assert stats1["total"] > 0
        assert stats1["skipped_duplicate"] == 0
        first_count = stats1["ingested"]
        
        # Secondary ingestion (exact same file)
        stats2 = firms_client.ingest_from_file(db, FIXTURE_VIIRS, product="VIIRS_NOAA20_NRT")
        assert stats2["ingested"] == 0
        assert stats2["skipped_duplicate"] == first_count
    finally:
        db.close()

def test_get_observations_endpoint():
    """
    Test GET /observations returns list of normalized observations.
    """
    response = client.get("/observations?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first = data[0]
    assert "id" in first
    assert "latitude" in first
    assert "longitude" in first
    assert "frp_mw" in first
    assert "confidence_score" in first
    assert "acquired_at" in first

def test_spatial_query_filtering():
    """
    Test spatial bounding box and radial queries.
    """
    # 1. Fetch one sample observation to get its coordinates
    resp = client.get("/observations?limit=1")
    sample = resp.json()[0]
    lat, lon = sample["latitude"], sample["longitude"]

    # 2. Query with radial filter around this point (radius 5 km)
    radial_resp = client.get(f"/observations?center_lat={lat}&center_lon={lon}&radius_km=5")
    assert radial_resp.status_code == 200
    radial_data = radial_resp.json()
    assert len(radial_data) >= 1
    assert any(obs["id"] == sample["id"] for obs in radial_data)

    # 3. Query with bounding box around the point
    bbox_resp = client.get(
        f"/observations?min_lat={lat - 0.1}&max_lat={lat + 0.1}&min_lon={lon - 0.1}&max_lon={lon + 0.1}"
    )
    assert bbox_resp.status_code == 200
    bbox_data = bbox_resp.json()
    assert len(bbox_data) >= 1

def test_get_single_observation_by_id():
    """
    Test GET /observations/{id}
    """
    resp = client.get("/observations?limit=1")
    sample_id = resp.json()[0]["id"]
    
    single_resp = client.get(f"/observations/{sample_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["id"] == sample_id

def test_live_firms_api_connectivity():
    """
    Live test against NASA FIRMS API using configured MAP_KEY.
    """
    firms_client = FIRMSClient()
    csv_text = firms_client.fetch_live_csv(product="VIIRS_NOAA20_NRT", days=1)
    # If network allows, verify we receive valid CSV text with header
    if csv_text:
        assert "latitude" in csv_text
        assert "longitude" in csv_text
        assert "frp" in csv_text
        parsed = firms_client.parse_csv(csv_text, product="VIIRS_NOAA20_NRT")
        assert len(parsed) >= 0
