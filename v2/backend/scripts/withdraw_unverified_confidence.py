"""
Corrective pass for INV-1: withdraw verification confidence that was never earned.

`refresh_industrial_incidents.py` and `refresh_mining_incidents.py` write
`classification` from a spatial predicate alone -- a basin polygon or a facility
perimeter -- while setting `classification_confidence` to 88.0 or 90.0 and
creating no `AIInvestigation` row. Those values are indistinguishable in the
database from a real vision verdict, and they satisfy the `ai_confidence >= 80`
gate on the CRITICAL industrial override in `severity/scoring.py`, so ordinary
process heat inside a mapped facility was escalated to CRITICAL on geometry
alone.

The scripts now write `FALLBACK_CONFIDENCE_CEILING` (50.0) instead, but that only
affects future runs. This pass withdraws the confidence already stored on rows
that have no investigation to justify it, leaving the label itself in place --
the label is a useful hint, the confidence is the false claim.

Run without arguments to see what would change; pass --apply to write.

    python scripts/withdraw_unverified_confidence.py
    python scripts/withdraw_unverified_confidence.py --apply

This is a data correction, not a re-score: `incidents.severity_score` is not
touched. An incident keeps the band it was last assessed into until the severity
sweep re-runs, so the console will not reflect this pass on its own.
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(SCRIPT_DIR, "..")))

from app.intelligence.provider import FALLBACK_CONFIDENCE_CEILING
from app.storage.database import SessionLocal
from app.storage.models import AIInvestigation, Incident

# The override gate this pass exists to keep unverified labels below.
OVERRIDE_CONFIDENCE_GATE = 80.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write the correction; without it the pass only reports",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        investigated = {
            row[0] for row in db.query(AIInvestigation.incident_id).distinct().all()
        }

        offenders = [
            inc for inc in db.query(Incident).all()
            if inc.classification
            and inc.classification != "uncertain"
            and (inc.classification_confidence or 0.0) >= OVERRIDE_CONFIDENCE_GATE
            and inc.id not in investigated
        ]

        print(f"[*] {len(offenders)} incident(s) assert classification confidence "
              f">= {OVERRIDE_CONFIDENCE_GATE} with no AI investigation on record.")
        print(f"[*] Their confidence will be withdrawn to "
              f"{FALLBACK_CONFIDENCE_CEILING} (the label is retained).\n")

        for inc in sorted(offenders, key=lambda i: i.incident_code or ""):
            print(f"    {inc.incident_code:<18} {inc.classification:<34} "
                  f"{inc.classification_confidence:>5} -> {FALLBACK_CONFIDENCE_CEILING}"
                  f"   ({inc.severity_level} {inc.severity_score})")

        if not offenders:
            print("[OK] Nothing to correct.")
            return 0

        if not args.apply:
            print(f"\n[DRY RUN] Nothing written. Re-run with --apply to correct "
                  f"{len(offenders)} row(s).")
            return 0

        for inc in offenders:
            inc.classification_confidence = FALLBACK_CONFIDENCE_CEILING
        db.commit()
        print(f"\n[OK] Withdrew unearned confidence on {len(offenders)} incident(s).")
        print("[!] incidents.severity_score is unchanged -- re-run the severity "
              "sweep for the console to reflect this.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
