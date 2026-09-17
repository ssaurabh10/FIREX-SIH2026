"""
Reconcile `incident_observations` links and the `incidents.observation_count`
denormalised counter against the observations that actually exist.

Two drifts are repaired, both measured on the shipped database:

1. **Dangling links.** 144 `incident_observations` rows name an
   `observation_id` that is not in `observations`. Their id shapes give the
   provenance away: 140 are bare UUIDs and 4 are `obs_test_*` samples, while
   every observation the current ingestion writes is `obs_<hex>`. They are
   association rows written against an earlier observation corpus that is no
   longer present.

2. **Overstated `observation_count`.** The column is not derived -- the
   association stage increments it (`app/incidents/association.py`:
   `old_count = matched_inc.observation_count or 1`, then `+=`) when it links
   another observation. An increment that survives the loss of its observation
   never gets taken back, so the counter keeps claiming detections that cannot
   be produced. Downstream this is not cosmetic: `pipeline.py` renders
   "Spatial multi-pixel cluster (N satellite detections)" from it, and
   `selection` and `imagery` size their viewports from it.

The two co-occur exactly. 77 incidents hold all 144 dangling rows and have no
resolvable link at all; the remaining 255 have a resolvable link for every row.
No incident is partially damaged, which is what makes a clean repair possible:
prune the rows that resolve to nothing, then restate the counter as the number
of links that do resolve.

Nothing else is touched -- not `status`, not `current_max_frp`, not any
severity column. An incident left at zero observations is reported, not
deleted; `--prune-orphans` is opt-in and separate.

    python scripts/reconcile_incident_links.py                  # report only
    python scripts/reconcile_incident_links.py --apply          # repair
    python scripts/reconcile_incident_links.py --apply --prune-orphans

Run while the API is not serving.
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

# Tables carrying an `incident_id` foreign key, ordered so dependents go first.
# Only consulted by `--prune-orphans`; a link repair never removes an incident.
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
        raise SystemExit(f"reconcile_incident_links.py handles SQLite only; DATABASE_URL is {url!r}.")
    path = url[len("sqlite:///"):]
    return path if os.path.isabs(path) else os.path.abspath(os.path.join(BACKEND_DIR, path))


def survey(cur: sqlite3.Cursor):
    """Return (dangling_rows, counter_drift, orphans) without changing anything."""
    cur.execute(
        """
        SELECT io.incident_id, io.observation_id
        FROM incident_observations io
        WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.id = io.observation_id)
        """
    )
    dangling = cur.fetchall()

    # Every incident's claimed counter beside the number of links that resolve.
    cur.execute(
        """
        SELECT i.id, i.incident_code, i.observation_count,
               (SELECT COUNT(*) FROM incident_observations io
                 WHERE io.incident_id = i.id) AS link_rows,
               (SELECT COUNT(*) FROM incident_observations io
                  JOIN observations o ON o.id = io.observation_id
                 WHERE io.incident_id = i.id) AS resolvable
        FROM incidents i
        """
    )
    rows = cur.fetchall()

    drift = [r for r in rows if (r[2] or 0) != r[4]]
    orphans = [r for r in rows if r[4] == 0]
    return dangling, drift, orphans, len(rows)


def reconcile(db_path: str, apply: bool, prune_orphans: bool, force_orphans: bool) -> int:
    if not os.path.exists(db_path):
        raise SystemExit(f"No database at {db_path}.")

    con = sqlite3.connect(db_path, timeout=60.0)
    cur = con.cursor()
    dangling, drift, orphans, total = survey(cur)

    print(f"[*] Database            : {db_path}")
    print(f"[*] Incidents           : {total}")
    print(f"[*] Dangling link rows  : {len(dangling)}")
    print(f"[*] Counters to restate : {len(drift)}")
    print(f"[*] Zero-observation    : {len(orphans)}")

    if dangling:
        by_method = {}
        for inc_id, obs_id in dangling:
            kind = "obs_test_*" if str(obs_id).startswith("obs_test_") else (
                "uuid" if len(str(obs_id)) == 36 and str(obs_id).count("-") == 4 else "other")
            by_method[kind] = by_method.get(kind, 0) + 1
        print(f"      dangling id shapes: {by_method}")

    if drift:
        print("\n[*] `observation_count` differs from the resolvable link count:")
        for inc_id, code, claimed, link_rows, resolvable in drift[:15]:
            print(f"      {code:22s} claimed={claimed!s:>4} links={link_rows:>3} resolvable={resolvable:>3}")
        if len(drift) > 15:
            print(f"      ... and {len(drift) - 15} more")

    if orphans:
        print(f"\n[*] {len(orphans)} incident(s) left with no resolvable observation:")
        for inc_id, code, claimed, link_rows, resolvable in orphans[:10]:
            print(f"      {code:22s} claimed={claimed!s:>4} (all {link_rows} link row(s) dangle)")
        if len(orphans) > 10:
            print(f"      ... and {len(orphans) - 10} more")

    if not apply:
        con.close()
        print("\n[report only] Re-run with --apply to repair.")
        return 0

    # 1. Prune links that resolve to nothing.
    if dangling:
        cur.executemany(
            "DELETE FROM incident_observations WHERE incident_id = ? AND observation_id = ?",
            dangling,
        )
        print(f"\n[OK] Removed {len(dangling)} dangling link row(s).")

    # 2. Restate the counter as the number of links that resolve. Done after the
    #    prune so the recomputation sees the repaired link table.
    if drift:
        cur.execute(
            """
            UPDATE incidents
               SET observation_count = (
                     SELECT COUNT(*)
                       FROM incident_observations io
                       JOIN observations o ON o.id = io.observation_id
                      WHERE io.incident_id = incidents.id
                   )
             WHERE observation_count IS NOT (
                     SELECT COUNT(*)
                       FROM incident_observations io
                       JOIN observations o ON o.id = io.observation_id
                      WHERE io.incident_id = incidents.id
                   )
            """
        )
        print(f"[OK] Restated {cur.rowcount} `observation_count` value(s).")

    # 3. Optional: remove the incident shells themselves. Deleting whole
    #    incidents is a much larger act than pruning links, so it takes two
    #    flags: `--prune-orphans` states the intent and reports the blast
    #    radius, `--force-orphans` confirms it. Without the second flag this
    #    block reports and leaves every incident in place.
    if prune_orphans and orphans:
        ids = tuple(r[0] for r in orphans)
        placeholders = ",".join("?" * len(ids))
        counts = {}
        for table in DEPENDENT_TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE incident_id IN ({placeholders})", ids)
            counts[table] = cur.fetchone()[0]
        total_dependents = sum(counts.values())

        if not force_orphans:
            print(f"\n[*] --prune-orphans would remove {len(ids)} incident(s) "
                  f"and {total_dependents} dependent row(s) across "
                  f"{sum(1 for n in counts.values() if n)} table(s):")
            for table, n in counts.items():
                if n:
                    print(f"      {table}: {n}")
            con.commit()
            con.close()
            print("\n[report only] Add --force-orphans to delete them.")
            return 1

        for table in DEPENDENT_TABLES:
            if counts[table]:
                cur.execute(f"DELETE FROM {table} WHERE incident_id IN ({placeholders})", ids)
        cur.execute(f"DELETE FROM incidents WHERE id IN ({placeholders})", ids)
        print(f"[OK] Removed {len(ids)} zero-observation incident(s) "
              f"and {total_dependents} dependent row(s).")

    con.commit()
    con.close()
    print("\n[OK] Reconciliation complete.")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reconcile incident observation links and counters.")
    parser.add_argument("--apply", action="store_true", help="repair rather than report")
    parser.add_argument("--prune-orphans", action="store_true",
                        help="also delete incidents left with no resolvable observation")
    parser.add_argument("--force-orphans", action="store_true",
                        help="skip the confirmation report for --prune-orphans")
    parser.add_argument("--db", default=None, help="override the SQLite path")
    args = parser.parse_args()

    target = args.db or resolve_db_path()
    reconcile(target, args.apply, args.prune_orphans, args.force_orphans)
