"""The export targets must be redirectable, and the redirect must survive a re-exec.

``export_v1_dashboard_data`` writes ``incidents.json`` / ``ambient_firms.json`` /
``queue_summary.json`` into ``FRONTEND_DATA_DIR`` and ``V1_DATA_DIR``. Both resolve
from the source tree, so *any* process that calls the export overwrites the files
the console serves on its static-fallback path -- a test run, a scratch probe, a
CLI invocation against a throwaway database. That has now caused real damage
twice:

* F-098 -- a pytest run against the throwaway database took the served
  ``v2/frontend/data/incidents.json`` from 921,393 bytes / 323 records to
  3,181 bytes / 1 record.
* An out-of-harness falsification run in ``Temp/`` left all six exports at ``[]``
  (2 bytes) and an all-zero ``queue_summary.json``.

``tests/conftest.py`` rebinds the two module attributes, which covers an ordinary
run from ``v2/``. It did **not** cover the second incident: that harness re-execs
the pipeline module body, which recomputes both names from ``__file__`` and points
them straight back at the served directory -- and it sat outside ``v2/tests/``, so
conftest never loaded at all. These tests pin the two properties that make the
redirect robust rather than merely conventional.
"""
import os
import subprocess
import sys

import pytest

from app.orchestration import pipeline

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
FRONTEND_ENV = "FIREX_FRONTEND_DATA_DIR"
V1_ENV = "FIREX_V1_DATA_DIR"

# The paths the defaults must still produce when nothing overrides them: the
# served console fallback and its v1 twin, anchored on the repository root.
SOURCE_TREE_FRONTEND = os.path.join(pipeline._REPO_ROOT, "v2", "frontend", "data")
SOURCE_TREE_V1 = os.path.join(pipeline._REPO_ROOT, "v1", "dashboard", "data")


def _resolve_in_subprocess(env_overrides):
    """Import the pipeline in a fresh interpreter and report both targets.

    A subprocess is required: ``app.storage.database`` builds its engine at
    import time, and these names are module globals, so the only way to observe
    what a *caller* gets is to be one.
    """
    env = dict(os.environ)
    for key in (FRONTEND_ENV, V1_ENV):
        env.pop(key, None)
    env.update(env_overrides)
    env["PYTHONPATH"] = BACKEND_DIR + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import json;"
        "from app.orchestration import pipeline as p;"
        "print(json.dumps([p.FRONTEND_DATA_DIR, p.V1_DATA_DIR]))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=BACKEND_DIR,
    )
    if proc.returncode != 0:
        pytest.fail(f"subprocess failed:\n{proc.stdout}\n{proc.stderr}")
    import json

    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_targets_default_to_the_source_tree():
    """With no override the export still lands where the console reads from.

    The override must not change production behaviour: the served fallback is
    the point of the export.
    """
    frontend, v1 = _resolve_in_subprocess({})
    assert os.path.normcase(frontend) == os.path.normcase(SOURCE_TREE_FRONTEND)
    assert os.path.normcase(v1) == os.path.normcase(SOURCE_TREE_V1)


def test_targets_honour_the_environment():
    """A caller that must not touch the served files can say so."""
    override_frontend = os.path.join(os.path.abspath(os.sep), "tmp", "firex-probe", "frontend")
    override_v1 = os.path.join(os.path.abspath(os.sep), "tmp", "firex-probe", "v1")
    frontend, v1 = _resolve_in_subprocess(
        {FRONTEND_ENV: override_frontend, V1_ENV: override_v1}
    )
    assert os.path.normcase(frontend) == os.path.normcase(override_frontend)
    assert os.path.normcase(v1) == os.path.normcase(override_v1)


def test_targets_survive_a_module_body_reexec():
    """The redirect must outlive a re-exec of the module body.

    This is the case that defeated attribute rebinding alone, and the reason the
    environment is read at all. The falsification harnesses exec a (possibly
    reverted) copy of ``pipeline``'s source into the module's namespace; the
    module body recomputes both names from ``__file__``, which is still the real
    source path, so an attribute-only redirect silently reverts to the served
    directory.
    """
    assert os.environ.get(FRONTEND_ENV), "conftest must export the override"
    assert os.environ.get(V1_ENV), "conftest must export the override"

    with open(pipeline.__file__, "r", encoding="utf-8") as fh:
        source = fh.read()

    # A copy of the live namespace: ``__file__`` and every import are present, so
    # the re-exec behaves exactly as it does in the harness, while the real module
    # is left untouched for the rest of the session.
    namespace = dict(vars(pipeline))
    exec(compile(source, pipeline.__file__, "exec"), namespace)

    assert namespace["FRONTEND_DATA_DIR"] == os.environ[FRONTEND_ENV]
    assert namespace["V1_DATA_DIR"] == os.environ[V1_ENV]

    # And the re-exec must not have reached into the source tree by any other
    # name either -- `_REPO_ROOT` is still derived from `__file__`, so it is
    # correct for it to point at the repository.
    assert os.path.normcase(namespace["_REPO_ROOT"]) == os.path.normcase(
        pipeline._REPO_ROOT
    )
