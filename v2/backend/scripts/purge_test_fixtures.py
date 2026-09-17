"""
Purge leftover test-fixture incidents from a live database.

Before `tests/conftest.py` bound the suite to a throwaway database, a test run
wrote into whichever `firex_v2.db` the working directory resolved to. The
historian suite's fixtures survived their run, so nine `INC-HIST-TEST-*`
incidents ended up `ACTIVE` in the database the console serves -- each with
`observation_count = 1` and no linked observation, positioned at coordinates
that made them look like ordinary detections.

An incident is treated as a leftover only when **both** hold:

* its `incident_code` matches the fixture prefix, and
* it has no linked `incident_observations` row.

The second condition is the important one. It means the purge can never remove a
real incident that merely happens to be named like a fixture: a genuine
detection is linked to the observations that produced it, so it survives.

    python scripts/purge_test_fixtures.py                 # report only
    python scripts/purge_test_fixtures.py --apply         # delete
    python scripts/purge_test_fixtures.py --apply --prefix INC-HIST-TEST-

Dependent rows in every table that carries an `incident_id` are removed with the
incident, in foreign-key order. Run `--apply` while the API is not serving.
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

DEFAULT_PREFIX = "INC-HIST-TEST-"

# Tables carrying an `incident_id` foreign key, ordered so dependents go first.
DEPENDENT_TABLES = [
    "incident_observations",
    "incident_events",
    "severity_assessments",
    "alert_records",
    "ai_investigations",
    "imagery_records",
    "historical_anomalies",
]


def resolve_db_path() -> str:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite:///"):
        raise SystemExit(f"purge_test_fixtures.py handles SQLite databases only; DATABASE_URL is {url!r}.")
    path = url[len("sqlite:///"):]
    return path if os.path.isabs(path) else os.path.abspath(os.path.join(BACKEND_DIR, path))


def find_fixtures(cur: sqlite3.Cursor, prefix: str):
    cur.execute(
        """
        SELECT i.id, i.incident_code, i.status, i.created_at
        FROM incidents i
        WHERE i.incident_code LIKE ?
          AND NOT EXISTS (
              SELECT 1 FROM incident_observations io WHERE io.incident_id = i.id
          )
        ORDER BY i.created_at
        """,
        (prefix + "%",),
    )
    return cur.fetchall()


def purge(db_path: str, prefix: str, apply: bool) -> int:
    if not os.path.exists(db_path):
        raise SystemExit(f"No database at {db_path}.")

    con = sqlite3.connect(db_path, timeout=60.0)
    cur = con.cursor()
    fixtures = find_fixtures(cur, prefix)

    if not fixtures:
        print(f"[OK] No unlinked incidents matching {prefix!r} in {db_path}.")
        con.close()
        return 0

    print(f"[*] {len(fixtures)} unlinked fixture incident(s) matching {prefix!r}:")
    for inc_id, code, status, created in fixtures:
        print(f"      {code}  status={status}  created={created}")

    ids = tuple(row[0] for row in fixtures)
    placeholders = ",".join("?" * len(ids))

    counts = {}
    for table in DEPENDENT_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE incident_id IN ({placeholders})", ids)
        counts[table] = cur.fetchone()[0]

    print("[*] Dependent rows that will be removed with them:")
    for table, n in counts.items():
        print(f"      {table}: {n}")

    if not apply:
        con.close()
        print("\n[report only] Re-run with --apply to delete.")
        return 0

    for table in DEPENDENT_TABLES:
        if counts[table]:
            cur.execute(f"DELETE FROM {table} WHERE incident_id IN ({placeholders})", ids)
    cur.execute(f"DELETE FROM incidents WHERE id IN ({placeholders})", ids)
    con.commit()

    # Reclaim the space; a 1.2 GB SQLite file does not shrink on DELETE alone.
    cur.execute("VACUUM")
    con.commit()
    con.close()

    print(f"\n[OK] Removed {len(fixtures)} fixture incident(s) and {sum(counts.values())} dependent row(s).")
    return len(fixtures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove leftover test-fixture incidents.")
    parser.add_argument("--apply", action="store_true", help="delete rather than report")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"incident_code prefix (default {DEFAULT_PREFIX!r})")
    parser.add_argument("--db", default=None, help="override the SQLite path")
    args = parser.parse_args()

    target = args.db or resolve_db_path()
    print(f"[*] Target database: {target}")
    purge(target, args.prefix, args.apply)
