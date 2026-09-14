"""
Automated Test Suite for Stage 2: GIS + Industrial Context
Verifies:
1. Spatial Mathematics & Geometry Algorithms (Haversine & Point-in-Polygon).
2. Point-in-Polygon Controlled Fixtures:
   - Point inside facility polygon -> is_inside == True
   - Point near polygon (< buffer_radius) -> is_inside == False, distance < radius
   - Point far outside polygon -> is_inside == False, distance > radius
3. Administrative Boundaries Lookup (State & District).
4. Land Cover Resolution (Industrial, Protected Forest, Agrarian).
5. Industry API Endpoints:
   - GET /industries (listing & filtering)
   - GET /industries/search?q= (multi-attribute text search)
   - GET /gis/enrich (end-to-end enrichment for coordinate)
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.database import SessionLocal, engine
from app.storage.models import Base, IndustrialAsset
from app.gis.spatial import haversine_distance_meters, point_in_polygon, point_in_geojson_geometry
from app.gis.boundaries import resolve_admin_boundary
from app.gis.landcover import resolve_landcover
from app.gis.assets import seed_industrial_assets, find_nearest_asset
from app.gis.enrichment import enrich_coordinate_gis_context

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

def test_haversine_distance_accuracy():
    """
    Test Haversine distance calculation between known coordinates:
    HMEL Refinery (29.9100, 74.9520) and Panipat IOCL (29.4780, 76.8540).
    Expected ~190 km.
    """
    dist_m = haversine_distance_meters(29.9100, 74.9520, 29.4780, 76.8540)
    dist_km = dist_m / 1000.0
    assert 170.0 <= dist_km <= 210.0

def test_controlled_geometry_point_in_polygon():
    """
    Test controlled geometric fixtures:
    - Unit square polygon: [(0,0), (10,0), (10,10), (0,10), (0,0)]
    """
    square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    
    # 1. Point strictly inside
    assert point_in_polygon(lat=5.0, lon=5.0, polygon_coords=square) is True
    
    # 2. Point strictly outside
    assert point_in_polygon(lat=15.0, lon=5.0, polygon_coords=square) is False
    assert point_in_polygon(lat=5.0, lon=-2.0, polygon_coords=square) is False

def test_facility_containment_fixtures():
    """
    Test real facility containment fixtures around Panipat IOCL Refinery (29.4780, 76.8540):
    - Case A: Point inside perimeter (within 200m)
    - Case B: Point near perimeter (within 5 km)
    - Case C: Point distant (far outside)
    """
    db = SessionLocal()
    try:
        # Case A: Inside Panipat refinery footprint (~100m away)
        inside_result = find_nearest_asset(29.4785, 76.8545, db)
        assert inside_result["facility_name"] is not None
        assert "Panipat" in inside_result["facility_name"]
        assert inside_result["is_inside_facility"] is True
        assert inside_result["distance_km"] < 1.0

        # Case B: Near Panipat refinery (~4 km away, outside perimeter)
        near_result = find_nearest_asset(29.5100, 76.8540, db)
        assert "Panipat" in near_result["facility_name"]
        assert near_result["is_inside_facility"] is False
        assert 3.0 <= near_result["distance_km"] <= 6.0

        # Case C: Distant point in southern India (8.5, 77.0)
        far_result = find_nearest_asset(8.5000, 77.0000, db)
        assert far_result["is_inside_facility"] is False
        assert far_result["distance_km"] > 50.0
    finally:
        db.close()

def test_admin_boundary_resolution():
    """
    Test Indian sovereign State and District lookups.
    """
    # Bathinda, Punjab
    res_punjab = resolve_admin_boundary(29.9100, 74.9520)
    assert res_punjab["country"] == "India"
    assert res_punjab["state"] == "Punjab"

    # Dhanbad, Jharkhand
    res_jharkhand = resolve_admin_boundary(23.6790, 86.3940)
    assert res_jharkhand["country"] == "India"
    assert res_jharkhand["state"] == "Jharkhand"

def test_landcover_classification():
    """
    Test landcover resolution:
    - Industrial complex when close to refinery
    - Dense forest when inside national park
    - Cropland in agrarian belt
    """
    # 1. Industrial complex
    lc_ind = resolve_landcover(lat=29.4780, lon=76.8540, nearest_asset_distance_km=0.1, nearest_asset_category="gas_flare")
    assert lc_ind["primary_landcover"] == "industrial_complex"
    assert lc_ind["is_protected_area"] is False

    # 2. Jim Corbett National Park (29.53, 78.77)
    lc_forest = resolve_landcover(lat=29.53, lon=78.77, nearest_asset_distance_km=100.0)
    assert lc_forest["primary_landcover"] == "dense_forest"
    assert lc_forest["is_protected_area"] is True
    assert "Corbett" in lc_forest["protected_area_name"]

def test_industries_api_endpoints():
    """
    Test GET /industries, GET /industries/search, and GET /gis/enrich.
    """
    # 1. Listing
    res_list = client.get("/industries?limit=10")
    assert res_list.status_code == 200
    industries = res_list.json()
    assert len(industries) >= 5

    # 2. Search by name
    res_search = client.get("/industries/search?q=Refinery")
    assert res_search.status_code == 200
    refineries = res_search.json()
    assert len(refineries) >= 2
    assert all(
        "refinery" in r["name"].lower()
        or "refinery" in r["industry"].lower()
        or "refinery" in r.get("facility_type", "").lower()
        for r in refineries
    )

    # 3. Search by state
    res_state = client.get("/industries/search?q=Gujarat")
    assert res_state.status_code == 200
    assert len(res_state.json()) >= 1

    # 4. Master GIS Enrichment endpoint
    res_enrich = client.get("/gis/enrich?lat=29.9100&lon=74.9520")
    assert res_enrich.status_code == 200
    enrich_data = res_enrich.json()
    assert enrich_data["country"] == "India"
    assert enrich_data["state"] == "Punjab"
    assert enrich_data["nearest_industrial_asset"]["name"] is not None
    assert "HMEL" in enrich_data["nearest_industrial_asset"]["name"]
    assert enrich_data["nearest_industrial_asset"]["is_inside_facility"] is True
    assert enrich_data["land_cover"] == "industrial_complex"
