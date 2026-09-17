"""
FIREX v2 Schema Reconciliation

Adds the columns that `app/storage/models.py` declares but an existing SQLite
database may predate. There is no migration tool in this project -- schema
changes reach a database only through `Base.metadata.create_all`, which creates
missing *tables* and never alters an existing one. So a model gaining a column
silently diverges from every database already on disk, and the divergence shows
up as `no such column` at runtime.

Run it against the configured database:

    python scripts/migrate_schema.py            # apply
    python scripts/migrate_schema.py --dry-run  # report only

Idempotent: each column is added only when `PRAGMA table_info` does not already
list it, so running twice is a no-op.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings

# (table, column, DDL type+default). Only additive, nullable or defaulted
# columns belong here -- a NOT NULL column without a default cannot be added to
# a populated table.
ADDITIONS = [
    # C_firms: the aggregate NASA FIRMS confidence of an incident's member
    # observations, on the 0-100 scale. Section 4.5/4.6. Nullable on purpose:
    # NULL means "no member observation carried a confidence", which is
    # different from 0.0 and is what app/incidents/aggregation.py detects.
    ("incidents", "firms_confidence", "FLOAT"),
    # INV-6 alert lifecycle. `superseded_by` lets an escalation close the alert it
    # replaced instead of leaving both open against the same incident.
    ("alert_records", "superseded_by", "VARCHAR"),
    ("alert_records", "acknowledged_at", "DATETIME"),
    ("alert_records", "resolved_at", "DATETIME"),
    # Persisted counterpart of the status string returned by
    # behavior.anomaly.evaluate_historical_anomaly.
    ("historical_anomalies", "anomaly_status", "VARCHAR"),
    # Behavior-profile window metadata (Section 10).
    ("behavior_profiles", "window_days", "INTEGER DEFAULT 365"),
    ("behavior_profiles", "day_passes_count", "INTEGER DEFAULT 0"),
    ("behavior_profiles", "night_passes_count", "INTEGER DEFAULT 0"),
    ("behavior_profiles", "is_continuous_24h", "BOOLEAN DEFAULT 0"),
]


def resolve_db_path() -> str:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite:///"):
        raise SystemExit(
            f"migrate_schema.py handles SQLite databases only; DATABASE_URL is {url!r}. "
            "For PostgreSQL, apply the equivalent ALTER TABLE statements with your own tooling."
        )
    path = url[len("sqlite:///"):]
    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join(BACKEND_DIR, path))
    return path


def migrate(db_path: str, dry_run: bool = False) -> int:
    if not os.path.exists(db_path):
        raise SystemExit(f"No database at {db_path}. Nothing to reconcile.")

    con = sqlite3.connect(db_path, timeout=60.0)
    cur = con.cursor()
    applied = 0

    for table, column, ddl in ADDITIONS:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if cur.fetchone() is None:
            print(f"  skip  {table}.{column}: table does not exist yet "
                  f"(create_all will build it with this column)")
            continue

        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column in existing:
            print(f"  ok    {table}.{column}: already present")
            continue

        if dry_run:
            print(f"  WOULD {table}.{column} {ddl}")
            applied += 1
            continue

        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        print(f"  add   {table}.{column} {ddl}")
        applied += 1

    if dry_run:
        con.close()
        print(f"\n[dry-run] {applied} column(s) would be added to {db_path}")
        return applied

    con.commit()
    con.close()
    print(f"\n[OK] {applied} column(s) added to {db_path}")
    return applied


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconcile a SQLite database with the ORM models.")
    parser.add_argument("--dry-run", action="store_true", help="report without altering")
    parser.add_argument("--db", default=None, help="override the SQLite path")
    args = parser.parse_args()

    target = args.db or resolve_db_path()
    print(f"[*] Target database: {target}")
    migrate(target, dry_run=args.dry_run)
