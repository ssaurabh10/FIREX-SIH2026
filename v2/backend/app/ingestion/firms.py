"""
NASA FIRMS HTTP Client & CSV Ingestion Engine
Handles:
1. Live fetch from NASA FIRMS API (area/csv endpoint).
2. Parsing CSV rows (VIIRS & MODIS format).
3. Validation via RawFIRMSObservation.
4. Normalization and deduplication before database persistence.
5. Ingesting from local/cached CSV files (deterministic test fixtures).
"""
import csv
import io
from typing import List, Dict, Any, Optional
import requests
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import logger
from app.ingestion.validator import RawFIRMSObservation, NormalizedObservation
from app.ingestion.normalizer import normalize_raw_firms
from app.storage.models import Observation
from app.gis.boundaries import is_within_indian_sovereign_territory

class FIRMSClient:
    def __init__(
        self,
        map_key: Optional[str] = None,
        base_url: Optional[str] = None,
        region: Optional[str] = None
    ):
        self.map_key = map_key or settings.FIRMS_MAP_KEY
        self.base_url = base_url or settings.FIRMS_BASE_URL
        self.region = region or settings.FIRMS_REGION

    def fetch_live_csv(self, product: str, days: int = 1) -> Optional[str]:
        """
        Calls NASA FIRMS area/csv API for the specified product and days.
        URL pattern: {FIRMS_BASE}/{MAP_KEY}/{product}/{region}/{days}
        """
        url = f"{self.base_url}/{self.map_key}/{product}/{self.region}/{days}/"
        logger.info(f"Fetching FIRMS feed: {url}")
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.text
            logger.error(f"FIRMS fetch failed: HTTP {response.status_code} - {response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Error querying NASA FIRMS API: {e}")
            return None

    def parse_csv(self, csv_content: str, product: str = settings.FIRMS_DEFAULT_PRODUCTS[0]) -> List[NormalizedObservation]:
        """
        Parses CSV string into a validated list of NormalizedObservation objects.
        Silently skips malformed rows with warning logs.
        """
        reader = csv.DictReader(io.StringIO(csv_content))
        normalized_records: List[NormalizedObservation] = []

        for row_idx, row in enumerate(reader):
            try:
                # Basic key sanitization
                clean_row: Dict[str, Any] = {k.strip(): v.strip() for k, v in row.items() if k and v is not None}
                
                # Default instrument if missing
                if "instrument" not in clean_row or not clean_row["instrument"]:
                    clean_row["instrument"] = "MODIS" if "MODIS" in product.upper() else "VIIRS"

                raw_obj = RawFIRMSObservation(**clean_row)
                norm_obj = normalize_raw_firms(raw_obj, product=product)
                normalized_records.append(norm_obj)
            except Exception as e:
                logger.warning(f"Skipping malformed FIRMS row {row_idx}: {e}")
                continue

        logger.info(f"Parsed and normalized {len(normalized_records)} FIRMS detections for product {product}")
        return normalized_records

    def save_to_db(self, db: Session, observations: List[NormalizedObservation]) -> Dict[str, int]:
        """
        Persists observations into the database with deduplication on external_id.
        Returns counts of {ingested, skipped_duplicate, total}.
        """
        if not observations:
            return {"ingested": 0, "skipped_duplicate": 0, "total": 0}

        # Check existing external_ids in batch
        external_ids = [obs.external_id for obs in observations if obs.external_id]
        existing_ids = set()
        if external_ids:
            rows = db.query(Observation.external_id).filter(Observation.external_id.in_(external_ids)).all()
            existing_ids = {row[0] for row in rows if row[0]}

        new_entities = []
        skipped = 0
        foreign_skipped = 0

        for obs in observations:
            if not is_within_indian_sovereign_territory(obs.latitude, obs.longitude):
                foreign_skipped += 1
                continue

            if obs.external_id and obs.external_id in existing_ids:
                skipped += 1
                continue

            if obs.external_id:
                existing_ids.add(obs.external_id)

            entity = Observation(
                source=obs.source,
                external_id=obs.external_id,
                latitude=obs.latitude,
                longitude=obs.longitude,
                frp_mw=obs.frp_mw,
                confidence_raw=obs.confidence_raw,
                confidence_score=obs.confidence_score,
                satellite=obs.satellite,
                sensor=obs.sensor,
                product=obs.product,
                daynight=obs.daynight,
                acquired_at=obs.acquired_at,
                raw_payload=obs.raw_payload
            )
            new_entities.append(entity)
            existing_ids.add(obs.external_id)  # prevent duplicate in same batch

        if new_entities:
            db.bulk_save_objects(new_entities)
            db.commit()

        logger.info(f"Ingestion committed: {len(new_entities)} new observations, {skipped} duplicates skipped.")
        return {
            "ingested": len(new_entities),
            "skipped_duplicate": skipped,
            "total": len(observations)
        }

    def ingest_from_file(self, db: Session, file_path: str, product: str = settings.FIRMS_DEFAULT_PRODUCTS[0]) -> Dict[str, int]:
        """
        Deterministic fixture ingestion from a local CSV file.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        records = self.parse_csv(content, product=product)
        return self.save_to_db(db, records)
