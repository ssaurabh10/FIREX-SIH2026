# tests/fixtures

## `reference_data.json`

A frozen extract of the *small reference tables* that the suite reads but never
creates. It exists so `tests/conftest.py` can bind the whole session to a
throwaway SQLite database:

- `thermal_climatology` — the six grid cells the behaviour tests query by name
  (`GRID_22.04_83.73`, `GRID_21.19_81.39`, `GRID_20.96_86.01`, `GRID_17.61_83.20`,
  `GRID_22.32_82.59`, `GRID_23.77_86.39`). These back
  `test_climatology_calibration.py`, `test_industrial_facility_classification.py`
  and `test_mining_basin_classification.py`, which otherwise depend on whatever
  happens to be seeded in the live demo database.
- `industrial_assets` — all 30 rows. `find_nearest_asset` and the facility
  baseline tests resolve against these.

Everything else the suite touches (`incidents`, `observations`,
`behavior_profiles`, …) it creates and tears down itself.

## Regenerating

Extracted read-only from `backend/data/firex_v2.db`, which is the only place
these rows exist:

```bash
cd v2
python - <<'PY'
import sqlite3, json

GRIDS = [(22.04, 83.73), (21.189, 81.385), (20.965, 86.011),
         (17.615, 83.205), (22.324, 82.592), (23.769, 86.389)]

db = sqlite3.connect("file:backend/data/firex_v2.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
c = db.cursor()

clim = []
for lat, lon in GRIDS:
    clim += [dict(r) for r in c.execute(
        "SELECT * FROM thermal_climatology WHERE spatial_key = ?",
        (f"GRID_{lat:.2f}_{lon:.2f}",)).fetchall()]

payload = {
    "_provenance": "Extracted read-only from backend/data/firex_v2.db.",
    "thermal_climatology": clim,
    "industrial_assets": [dict(r) for r in
                          c.execute("SELECT * FROM industrial_assets").fetchall()],
}
with open("tests/fixtures/reference_data.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=1, ensure_ascii=False)
PY
```

`conftest.py` writes only the columns present in *both* the fixture and the
model-created table, so the seed degrades to a partial insert rather than
failing if the two drift apart.
