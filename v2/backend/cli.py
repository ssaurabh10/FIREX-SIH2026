"""
FIREX v2 Operational CLI
========================
Command-line entrypoints for the v2 backend. The console itself is served by
``v2/backend/run.py`` (uvicorn) and driven through the REST/SSE API; this module
covers the operations that must be runnable without a browser: an analysis run,
regenerating the console data files, the severity sweep, and schema migration.

Invoked via the repository-root dispatcher -- ``python run.py <command>`` --
but works standalone as ``python cli.py <command>`` too.

Bootstrapping
-------------
The backend directory is put on ``sys.path`` and made the working directory
before any ``app.*`` import.

``sys.path`` is what makes ``import app`` resolve -- the same thing that lets
``uvicorn``'s ``app.main:app`` string target work in ``run.py``.

The working directory is *not* needed for database resolution:
``app/core/config.py`` validates ``DATABASE_URL`` through
``_resolve_relative_sqlite_path``, which anchors a relative SQLite path to the
backend directory, so ``sqlite:///./data/firex_v2.db`` selects
``v2/backend/data/firex_v2.db`` from anywhere (J11). It is set here for the
relative paths a *caller* supplies -- ``--file`` / ``--firms-csv`` CSV
arguments resolve against the CWD -- and so that a command run from the
repository root behaves exactly like one run from ``v2/backend``.
"""
import argparse
import os
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)


def _bootstrap_logging() -> None:
    """Surface the engines' INFO logs, which are silenced by default."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )


def cmd_pipeline(args) -> int:
    """Execute one end-to-end analysis run (ingestion -> ... -> export)."""
    _bootstrap_logging()
    from app.storage.database import SessionLocal
    from app.orchestration.pipeline import execute_analysis_pipeline
    from app.orchestration.lock import AnalysisAlreadyRunningError

    db = SessionLocal()
    try:
        summary = execute_analysis_pipeline(
            db=db,
            firms_csv=args.firms_csv,
            file_path=args.file,
            force_reinvestigate=args.force,
            max_ai_targets=args.max_ai_targets,
            export_to_dashboard=not args.no_export,
        )
    except AnalysisAlreadyRunningError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary, report and set exit code
        print(f"[ERROR] Analysis run failed: {exc}")
        return 1
    finally:
        db.close()

    print(
        f"[FIREX v2] Run {summary.get('run_id', '?')} {summary.get('status', '?')} "
        f"in {summary.get('duration_seconds', '?')}s."
    )
    for key in ("observations_active", "new_observations", "clusters_count",
                "incidents_updated", "new_incidents", "candidates_investigated",
                "severity_sweep_evaluated", "alerts_emitted"):
        if key in summary:
            print(f"  {key:26s} {summary[key]}")
    failures = summary.get("severity_sweep_failures") or []
    if failures:
        print(f"  {'severity_sweep_failures':26s} {len(failures)} (see log)")
    return 0


def cmd_data(args) -> int:
    """Regenerate the console data files from the persisted queue.

    R15: the export reads ``risk_score`` and ``risk_factors`` straight off the
    incident row, so the severity engine has to have run first -- otherwise the
    file ships zeros. ``run_severity_sweep`` evaluates only incidents with no
    persisted assessment (``force=False``), so calling it here is cheap on a
    queue that is already scored and correct on one that is not.
    """
    _bootstrap_logging()
    from app.storage.database import SessionLocal
    from app.orchestration import pipeline as pipeline_mod

    db = SessionLocal()
    try:
        sweep = pipeline_mod.run_severity_sweep(db, force=args.force_sweep)
        print(
            f"[FIREX v2] Severity sweep: {sweep['evaluated']} evaluated, "
            f"{len(sweep['failed'])} failed, {sweep['considered']} considered."
        )
        if sweep["failed"]:
            for failure in sweep["failed"][:10]:
                print(f"    {failure['incident_code']}: {failure['error']}")

        pipeline_mod.export_v1_dashboard_data(db)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"[ERROR] Data regeneration failed: {exc}")
        return 1
    finally:
        db.close()

    print("[FIREX v2] Console data written to frontend/data/ and v1/dashboard/data/.")
    return 0


def cmd_severity_sweep(args) -> int:
    """Run the severity engine over the whole displayable queue."""
    _bootstrap_logging()
    from app.storage.database import SessionLocal
    from app.orchestration.pipeline import run_severity_sweep

    db = SessionLocal()
    try:
        result = run_severity_sweep(db, force=args.force)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"[ERROR] Severity sweep failed: {exc}")
        return 1
    finally:
        db.close()

    print(
        f"[FIREX v2] Evaluated {result['evaluated']} of {result['considered']} "
        f"candidates; {len(result['failed'])} failed."
    )
    for failure in result["failed"][:20]:
        print(f"    {failure['incident_code']}: {failure['error']}")
    return 0


def cmd_migrate(args) -> int:
    """Apply pending schema migrations.

    Delegated to ``scripts/migrate_schema.py`` rather than reimplemented here:
    ``Base.metadata.create_all`` cannot ALTER an existing table, so column
    additions are applied by that script and it remains the single definition
    of the migration set.
    """
    script = os.path.join(BACKEND_DIR, "scripts", "migrate_schema.py")
    if not os.path.exists(script):
        print(f"[ERROR] Migration script not found at: {script}")
        return 1
    cmd = [sys.executable, script]
    if args.dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, cwd=BACKEND_DIR).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python cli.py",
        description="FIREX v2 operational commands",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("pipeline", help="Execute one end-to-end analysis run")
    p.add_argument("--firms-csv", type=str, default=None,
                   help="Ingest from an already-downloaded FIRMS CSV instead of fetching")
    p.add_argument("--file", type=str, default=None,
                   help="Ingest from a CSV file on disk")
    p.add_argument("--force", action="store_true",
                   help="Re-investigate incidents that already carry an AI verdict")
    p.add_argument("--max-ai-targets", type=int, default=5,
                   help="Maximum incidents to send for optical AI investigation (default: 5)")
    p.add_argument("--no-export", action="store_true",
                   help="Skip writing frontend/data/ at the end of the run")
    p.set_defaults(func=cmd_pipeline)

    d = sub.add_parser("data", help="Regenerate console data files from the persisted queue")
    d.add_argument("--force-sweep", action="store_true",
                   help="Re-evaluate every incident rather than only unassessed ones")
    d.set_defaults(func=cmd_data)

    s = sub.add_parser("severity-sweep", help="Run the severity engine over the whole queue")
    s.add_argument("--force", action="store_true",
                   help="Re-evaluate every incident, not only those without an assessment")
    s.set_defaults(func=cmd_severity_sweep)

    m = sub.add_parser("migrate", help="Apply pending schema migrations")
    m.add_argument("--dry-run", action="store_true", help="Report pending changes only")
    m.set_defaults(func=cmd_migrate)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
