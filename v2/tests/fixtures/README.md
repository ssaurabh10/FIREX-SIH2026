# tests/fixtures

## `reference_data.json`

A frozen extract of the *small reference tables* that the suite reads but never
creates. It exists so `tests/conftest.py` can bind the whole session to a
throwaway SQLite database:

- `thermal_climatology` — the six grid cells the behaviour tests query by name
  (`GRID_22.04_83.72`, `GRID_21.18_81.38`, `GRID_20.96_86.02`, `GRID_17.62_83.20`,
  `GRID_22.32_82.60`, `GRID_23.76_86.38`). These back
  `test_climatology_calibration.py`, `test_industrial_facility_classification.py`
  and `test_mining_basin_classification.py`, which otherwise depend on whatever
  happens to be seeded in the live demo database.
- `industrial_assets` — all 30 rows. `find_nearest_asset` and the facility
  baseline tests resolve against these.

Everything else the suite touches (`incidents`, `observations`,
`behavior_profiles`, …) it creates and tears down itself.

## Regenerating

Taken read-only from `backend/data/firex_v2.db`, but aggregated from its
`observations` through the producer's own cell function rather than read out of
the deployed `thermal_climatology` table. Reading the table directly is how this
fixture came to hold six 0.01° keys (`GRID_22.04_83.73`) that no lookup could
reach once the reader moved to the producer's 0.02° lattice — the keys here
followed whichever convention the table happened to be built with, so the suite
was asserting the wrong grid without anyone editing it. Aggregating makes the
fixture agree with the producer by construction, and it needs no write to the
live database, which the suite must never touch.

```bash
cd v2
python - <<'PY'
import json, sqlite3, sys
from datetime import datetime, timedelta

sys.path.insert(0, "backend")
from scripts.build_thermal_climatology import aggregate_thermal_cells, classify_cell
from app.behavior.baseline import compute_percentiles
from app.gis.spatial import climatology_cell

# The coordinates the behaviour tests name. They are snapped through
# `climatology_cell`, so the keys written below are whatever the producer would
# write for them -- never a literal that can go stale against the grid.
POINTS = [(22.04, 83.73), (21.189, 81.385), (20.965, 86.011),
          (17.615, 83.205), (22.324, 82.592), (23.769, 86.389)]

db = sqlite3.connect("file:backend/data/firex_v2.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
c = db.cursor()

ref = datetime.utcnow()
window = ref - timedelta(days=365)
cells = aggregate_thermal_cells(c, window.strftime("%Y-%m-%d %H:%M:%S"), 3, window.date())

clim = []
for lat, lon in POINTS:
    cell_lat, cell_lon, key = climatology_cell(lat, lon)
    cell = cells[key]
    obs = cell["observation_count"]
    active = bin(cell["day_mask"]).count("1")
    night = round(cell["night_count"] / max(1, obs), 3)
    stats = compute_percentiles(list(cell["frp_values"]))
    flare, hint = classify_cell(cell_lat, cell_lon, active, night, stats["p95"])
    clim.append({
        "spatial_key": key, "latitude": cell_lat, "longitude": cell_lon,
        "observation_count": obs, "active_days": active,
        "median_frp": stats["median"], "p90_frp": stats["p90"],
        "p95_frp": stats["p95"], "max_frp": stats["max"],
        "night_ratio": night,
        "is_routine_flare": 1 if flare else 0,
        "site_classification_hint": hint,
        "last_updated_at": ref.strftime("%Y-%m-%d %H:%M:%S"),
    })

payload = {
    "_provenance": "Extracted read-only from backend/data/firex_v2.db by "
                   "tests/fixtures/README. Seeded into the throwaway test database by "
                   "tests/conftest.py so the suite never reads or writes the live "
                   "application database.",
    "thermal_climatology": clim,
    "industrial_assets": [dict(r) for r in
                          c.execute("SELECT * FROM industrial_assets").fetchall()],
}
with open("tests/fixtures/reference_data.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=1, ensure_ascii=False)
    f.write("\n")
PY
```

`conftest.py` writes only the columns present in *both* the fixture and the
model-created table, so the seed degrades to a partial insert rather than
failing if the two drift apart.
