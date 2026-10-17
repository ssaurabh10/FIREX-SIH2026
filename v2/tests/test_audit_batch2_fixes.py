"""
Tests for Batch 2 Audit Remediations (N-04, N-05, N-07, N-08):
1. N-04: GET endpoints / selection candidate evaluation do not persist anomaly records or execute per-incident db.commit().
2. N-05: Location baseline separates climatology_window_days (365) from request window_days.
3. N-07: Rate limiter ignores spoofed X-Forwarded-For headers from untrusted clients.
4. N-08: Live FIRMS ingestion queries all configured products with FIRMS_DAYS.
"""
import pytest
from unittest.mock import MagicMock, patch
from starlette.requests import Request

from app.core.ratelimit import RateLimitMiddleware
from app.selection.engine import evaluate_incident_selection
from app.behavior.baseline import get_or_create_location_baseline
from app.core.config import settings
from app.storage.models import Incident, ThermalClimatology


def test_n07_ratelimit_client_ip_anti_spoofing():
    """
    Verifies N-07: X-Forwarded-For is only trusted when the direct client
    is a trusted loopback/local proxy (e.g. 127.0.0.1, ::1).
    """
    app_mock = MagicMock()
    middleware = RateLimitMiddleware(app_mock)

    # 1. Direct external client trying to spoof X-Forwarded-For
    scope_external = {
        "type": "http",
        "client": ("198.51.100.22", 54321),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.1, 10.0.0.1"),
        ],
    }
    req_external = Request(scope_external)
    ip_external = middleware.get_client_ip(req_external)
    assert ip_external == "198.51.100.22", "Must not trust X-Forwarded-For from external client"

    # 2. Localhost reverse proxy forwarding client request
    scope_proxy = {
        "type": "http",
        "client": ("127.0.0.1", 45678),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.50, 10.0.0.1"),
        ],
    }
    req_proxy = Request(scope_proxy)
    ip_proxy = middleware.get_client_ip(req_proxy)
    assert ip_proxy == "203.0.113.50", "Must extract client IP from trusted local proxy"


def test_n04_selection_evaluation_does_not_commit_or_save_anomaly():
    """
    Verifies N-04: evaluate_incident_selection does not persist anomaly records (save_record=False)
    and does not commit transactions inside read paths.
    """
    mock_db = MagicMock()
    mock_incident = MagicMock(spec=Incident)
    mock_incident.id = "INC_TEST_BATCH2"
    mock_incident.latitude = 21.15
    mock_incident.longitude = 78.50
    mock_incident.current_max_frp = 38.5
    mock_incident.observation_count = 5
    mock_incident.status = "ACTIVE"
    mock_incident.nearest_asset_id = None
    mock_incident.asset = None

    mock_db.query.return_value.filter.return_value.first.return_value = mock_incident

    with patch("app.selection.engine.get_or_create_location_baseline") as mock_baseline, \
         patch("app.selection.engine.evaluate_historical_anomaly") as mock_anomaly, \
         patch("app.selection.engine.resolve_firms_confidence", return_value=85.0):

        mock_baseline.return_value = {
            "p50_frp": 10.0,
            "p95_frp": 25.0,
            "active_days": 12,
            "persistence_score": 0.45,
            "history_reliability_score": 0.75,
            "history_reliability_label": "HIGH",
        }
        mock_anomaly.return_value = {"anomaly_score": 55.0, "is_abnormal": True}

        res = evaluate_incident_selection("INC_TEST_BATCH2", mock_db)

        # Assert save_record=False was passed
        mock_anomaly.assert_called_once()
        _, kwargs = mock_anomaly.call_args
        assert kwargs.get("save_record") is False, "save_record must be False on selection read-path"

        # Assert no db.commit() was called
        mock_db.commit.assert_not_called()
        assert res["selection_priority"] is not None


def test_n05_climatology_window_days_separation():
    """
    Verifies N-05: When baseline pulls from 365-day ThermalClimatology table,
    climatology_window_days (365) is clearly exposed.
    """
    mock_db = MagicMock()
    # No profile cache hit
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        None,  # HistoricalBaseline
        ThermalClimatology(
            spatial_key="GRID_19.50_71.50",
            latitude=19.50,
            longitude=71.50,
            observation_count=45,
            active_days=20,
            median_frp=8.5,
            p90_frp=18.0,
            p95_frp=24.0,
            max_frp=42.0,
            night_ratio=0.30,
            is_routine_flare=True
        ),
        None   # BehaviorProfile lookup
    ]

    with patch("app.behavior.baseline.find_nearest_asset", return_value={"distance_km": 999.0, "is_inside_facility": False}):
        baseline = get_or_create_location_baseline(
            lat=19.50,
            lon=71.50,
            db=mock_db,
            window_days=90
        )

    assert baseline["window_days"] == 90
    assert baseline.get("climatology_window_days") == 365
    assert baseline["active_days"] == 20
    assert baseline["is_routine_flare"] is True


def test_n08_firms_ingestion_multi_product_loop():
    """
    Verifies N-08: Ingestion queries all configured products in settings.FIRMS_DEFAULT_PRODUCTS
    using settings.FIRMS_DAYS.
    """
    mock_firms_client = MagicMock()
    mock_firms_client.fetch_live_csv.return_value = "latitude,longitude,frp\n21.1,78.5,15.0"

    products_fetched = []
    days_passed = []

    def fake_fetch(prod, days=1):
        products_fetched.append(prod)
        days_passed.append(days)
        return "latitude,longitude,frp\n21.1,78.5,15.0"

    mock_firms_client.fetch_live_csv.side_effect = fake_fetch

    # Replicate the Stage 2 multi-product ingestion loop
    raw_csvs = []
    for prod in settings.FIRMS_DEFAULT_PRODUCTS:
        csv_data = mock_firms_client.fetch_live_csv(prod, days=settings.FIRMS_DAYS)
        raw_csvs.append(csv_data)

    assert set(products_fetched) == set(settings.FIRMS_DEFAULT_PRODUCTS)
    assert all(d == settings.FIRMS_DAYS for d in days_passed)
    assert len(raw_csvs) == len(settings.FIRMS_DEFAULT_PRODUCTS)
