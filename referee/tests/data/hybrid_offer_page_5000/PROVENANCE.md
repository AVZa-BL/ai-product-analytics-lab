# hybrid_offer_page_5000

The three exported tables of the lab's synthetic offer-page experiment at the 5,000-player
reference scale (seed 42). A snapshot used to test Referee against real lab output, in CI and
without the lab installed. 2,824 assignments, 3,974 exposures, 2,824 outcomes; about 1 MB.

## How it was made

From the repository root, with the analytics lab's environment:

```bash
cd analytics-lab
python -m analytics_lab.generate --scenario hybrid_subscription --seed 42 \
  --start-date 2026-01-01 --days 180 --scale 5000 --output-dir /tmp/raw5000
python - <<'PY'
import duckdb
raw, out = "/tmp/raw5000/hybrid_subscription", "../referee/tests/data/hybrid_offer_page_5000"
con = duckdb.connect()
for table in ("experiment_assignments", "experiment_exposures", "experiment_outcomes"):
    con.sql(f"copy (select * from read_parquet('{raw}/{table}.parquet') order by 1, 2) "
            f"to '{out}/{table}.csv' (header)")
PY
```

The generator is the one on `main` at the merge of pull request 31 (`15b1aa4`). DuckDB 1.5.6 wrote
the CSV, in its default format: UTF-8, a header row, timestamps such as `2026-04-26 17:43:48+00`.
Regenerating gives byte-identical files (checked when the fixture was added), and
`manifest.json` holds each file's row count and SHA-256 so that a test notices an edit.

## What it is not

A snapshot, not a mirror. If the lab's generator changes, this directory does not change with
it; regenerate it with the commands above and update `manifest.json` and the figures the tests
pin. The lab's own tests pin the generator, so a change there is noticed on that side.
