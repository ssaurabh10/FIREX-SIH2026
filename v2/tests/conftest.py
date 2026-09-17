"""
Pytest configuration for the FIREX v2 test suite.

Three jobs:

1. Put ``v2/backend`` on ``sys.path`` regardless of where pytest is invoked.

2. Bind the whole session to a throwaway SQLite database.

3. Redirect the pipeline's data exports *and* the imagery crop cache into that
   same throwaway directory.

Jobs 2 and 3 are both load-bearing, and job 3 is the one that was missing.

Job 2: this file used to fix ``sys.path`` only, and ``.env`` carries a
CWD-relative ``DATABASE_URL`` -- so depending on the directory pytest was
launched from, the suite ran straight against the live
``backend/data/firex_v2.db`` (1.28 GB). That is how nine ``INC-HIST-TEST-*``
fixtures ended up ``ACTIVE`` in the served console queue and baked into the
committed ``frontend/data/incidents.json``.

``DATABASE_URL`` is therefore overridden *before* any ``app.*`` import, because
``app.storage.database`` builds its engine from ``settings.DATABASE_URL`` at
import time. In pydantic-settings an environment variable outranks the dotenv
file, so the override holds wherever pytest is launched from.

Job 3: the throwaway database alone was not enough. ``export_v1_dashboard_data``
writes ``incidents.json`` / ``ambient_firms.json`` / ``queue_summary.json`` into
``FRONTEND_DATA_DIR`` and ``V1_DATA_DIR``, which ``app/orchestration/pipeline.py``
resolves from the *source tree* and not from the environment -- so a test run
still overwrote the committed console data with the throwaway database's
contents. ``test_dashboard_data_export_contract`` calls that export twice, and
its cleanup re-exports precisely so the served file is left "restored" -- but it
restores it *from the throwaway database*, which is the same write. Measured
before this fix: the served ``v2/frontend/data/incidents.json`` went from
921,393 bytes / 323 records at HEAD to 3,181 bytes / 1 record (F-098).

Small reference tables the suite reads but does not create (thermal-climatology
grid cells, industrial assets) are seeded from
``tests/fixtures/reference_data.json`` -- see ``tests/fixtures/README.md`` for
how that file was produced.

Job 3 covers a second directory as well: ``backend/data/imagery_cache``, where
the imagery service caches rendered crops and the API serves them from. Test
renders were landing there too (F-106); ``_isolate_test_writes`` redirects every
module-level handle on it.
"""
import json
import os
import shutil
import sys
import tempfile

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "reference_data.json")

# The database the application actually serves. Tests must never open it.
LIVE_DB_PATH = os.path.abspath(os.path.join(BACKEND_DIR, "data", "firex_v2.db"))

# --- Database isolation, before any app.* import -------------------------
# FIREX_TEST_DB lets a caller pin the throwaway database to a known path
# (useful when you want to inspect it after a run); otherwise we make one.
_pinned_dir = os.environ.get("FIREX_TEST_DB_DIR")
# abspath'd because the export-target guard below compares it against abspath'd
# targets: a caller pinning a POSIX-style path on Windows (``/tmp/firex-test``)
# would otherwise fail the comparison with nothing actually wrong.
_test_db_dir = os.path.abspath(_pinned_dir) if _pinned_dir else tempfile.mkdtemp(prefix="firex-test-")
_created_test_db_dir = _pinned_dir is None
os.environ["FIREX_TEST_DB_DIR"] = _test_db_dir
TEST_DB_PATH = os.path.abspath(os.path.join(_test_db_dir, "firex_test.db"))
os.environ["FIREX_TEST_DB"] = TEST_DB_PATH
os.environ["DATABASE_URL"] = "sqlite:///" + TEST_DB_PATH.replace("\\", "/")

if TEST_DB_PATH == LIVE_DB_PATH:
    raise RuntimeError(
        "Refusing to run the test suite against the live application database at "
        f"{LIVE_DB_PATH}. Unset FIREX_TEST_DB_DIR or point it somewhere else."
    )

# --- Test-write isolation, before any app.* import -----------------------
# Two source-tree directories receive writes during a *test* run. Neither is the
# database, so the DATABASE_URL override above does not cover either, and both
# were being written for real until they were redirected here.
#
# (1) The pipeline's exports. See job 3 in the module docstring for the measured
#     damage (F-098).
# Where the exports go instead. Both live under the throwaway directory, so
# pytest_unconfigure removes them with the database.
EXPORT_DIR = os.path.join(_test_db_dir, "exports")
FRONTEND_EXPORT_DIR = os.path.join(EXPORT_DIR, "frontend")
V1_EXPORT_DIR = os.path.join(EXPORT_DIR, "v1")

# Set in the environment as well as rebound below, because the rebind alone is
# not sufficient. ``_isolate_test_writes`` covers the module as imported, but a
# caller that re-execs the pipeline module body recomputes both names from
# ``__file__`` and silently points them back at the served files; the
# falsification harnesses that write into ``Temp/`` do exactly that, and one of
# them left the served ``frontend/data/incidents.json`` at ``[]``. Setting the
# environment first means the recomputation lands in the throwaway directory too.
os.environ["FIREX_FRONTEND_DATA_DIR"] = FRONTEND_EXPORT_DIR
os.environ["FIREX_V1_DATA_DIR"] = V1_EXPORT_DIR

# (2) The imagery cache. ``app/imagery/service.py`` renders and caches crops under
#     ``backend/data/imagery_cache/<incident_id>/`` and serves them back through
#     ``/api/imagery/cache/...``, so a suite run was writing test renders into the
#     directory the console reads from, keyed by throwaway incident ids (F-106).
#     Measured before this redirect: every one of the 623 directories in the
#     served cache was absent from the 319 incidents in
#     ``frontend/data/incidents.json``, and the newest carried an mtime inside a
#     test run. Deleting the cache is not the fix -- it refills on the next run.
IMAGERY_CACHE_DIR = os.path.join(_test_db_dir, "imagery_cache")


def _isolate_test_writes() -> None:
    """Point every in-repo test write target at ``_test_db_dir``.

    All five are module-level constants read at call time, so rebinding the
    module attributes redirects the module as imported. That is necessary but
    not sufficient on its own: a caller that re-execs a module body recomputes
    its ``__file__``-derived paths and undoes the rebind, which is why the two
    export targets are also set in the environment above (``pipeline`` reads
    ``FIREX_FRONTEND_DATA_DIR`` / ``FIREX_V1_DATA_DIR``). The remaining three
    have no environment hook and are covered by the rebind plus the assertion
    below:

    * ``pipeline.FRONTEND_DATA_DIR`` / ``V1_DATA_DIR`` -- read as globals on
      every call (``export_v1_dashboard_data``'s
      ``for target_dir in [FRONTEND_DATA_DIR, V1_DATA_DIR]``).
    * ``imagery_service.CACHE_DIR`` -- read as a global where a crop is cached
      (``service.py:17``).
    * ``imagery_api.CACHE_DIR`` -- that module does ``from app.imagery.service
      import ... CACHE_DIR``, which binds the *value* at import time, so
      rebinding ``service.CACHE_DIR`` alone would leave the crop-download
      endpoint reading the real directory. It has to be rebound separately.
    * ``main.V2_CROPS_DIR`` -- the same directory, as mounted for static serving.
      The ``StaticFiles`` instance captured the path when it was created at
      import, so this rebind covers code that reads the variable; the mount
      itself still points at the source tree, which the suite only reads from.

    ``intelligence/vision.py`` used to be a sixth writer: it re-derived the same
    directory from its own ``__file__``, so no rebind could reach it. It now
    reads ``imagery_service.CACHE_DIR`` off the module at call time, which is the
    same attribute rebound above (F-106).

    Must run before any test module does ``from app.orchestration.pipeline
    import FRONTEND_DATA_DIR``: that binds the value by name, so a later rebind
    would not reach it. ``pytest_configure`` runs before collection and
    therefore before every test-module import; the module-level call below runs
    earlier still, so the ordering does not depend on hook timing.
    """
    from app.orchestration import pipeline
    from app.imagery import service as imagery_service
    from app.api import imagery as imagery_api
    from app import main as app_main

    targets = [
        (pipeline, "FRONTEND_DATA_DIR", FRONTEND_EXPORT_DIR),
        (pipeline, "V1_DATA_DIR", V1_EXPORT_DIR),
        (imagery_service, "CACHE_DIR", IMAGERY_CACHE_DIR),
        (imagery_api, "CACHE_DIR", IMAGERY_CACHE_DIR),
        (app_main, "V2_CROPS_DIR", IMAGERY_CACHE_DIR),
    ]
    for _, _, replacement in targets:
        os.makedirs(replacement, exist_ok=True)

    originals = [(module, attr, getattr(module, attr)) for module, attr, _ in targets]
    for module, attr, replacement in targets:
        setattr(module, attr, replacement)

    # The rebind is only useful if it took. This is the assertion that would
    # have failed on the pre-fix tree, where every one of these globals resolved
    # into the source tree: it pins each write target to the throwaway
    # directory, so a regression fails the suite before it can touch the served
    # console data or the served imagery cache.
    for module, attr, original in originals:
        target = getattr(module, attr)
        assert os.path.abspath(target).startswith(_test_db_dir + os.sep), (
            f"{module.__name__}.{attr} is {target!r} (was {original!r}), outside "
            f"the throwaway test directory {_test_db_dir!r}; a test run would "
            f"write into the source tree"
        )


_isolate_test_writes()


def _seed_reference_tables(engine) -> None:
    """Copy the small reference tables the suite reads but never creates.

    Only columns present in both the fixture and the model-created table are
    written, so a schema change in either direction degrades to a partial seed
    instead of an error.
    """
    if not os.path.exists(FIXTURE_PATH):
        return

    from sqlalchemy import inspect, text

    with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, rows in payload.items():
            if table.startswith("_") or table not in existing_tables or not rows:
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            placeholders = ", ".join(f":{c}" for c in sorted(columns))
            column_list = ", ".join(sorted(columns))
            stmt = text(
                f"INSERT OR IGNORE INTO {table} ({column_list}) VALUES ({placeholders})"
            )
            for row in rows:
                conn.execute(stmt, {k: v for k, v in row.items() if k in columns})


def pytest_configure(config):
    """Create the schema in the isolated database and seed shared fixtures.

    Export-target redirection happens at import time -- see
    ``_isolate_test_writes`` above -- so that it precedes every test module's
    ``from app.orchestration.pipeline import FRONTEND_DATA_DIR``.
    """
    from app.storage.database import Base, engine
    from app.storage import models  # noqa: F401  -- registers every table on Base

    Base.metadata.create_all(bind=engine)
    _seed_reference_tables(engine)


def pytest_unconfigure(config):
    """Drop the throwaway database, but only one this session created."""
    if _created_test_db_dir:
        shutil.rmtree(_test_db_dir, ignore_errors=True)
