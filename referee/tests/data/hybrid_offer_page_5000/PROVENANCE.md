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
con.sql("set TimeZone = 'UTC'")
for table in ("experiment_assignments", "experiment_exposures", "experiment_outcomes"):
    con.sql(f"copy (select * from read_parquet('{raw}/{table}.parquet') order by 1, 2) "
            f"to '{out}/{table}.csv' (header)")
PY
```

The generator is the one on `main` at the merge of pull request 43 (`e8ccac7`), which writes
`first_seen_at_utc` into the assignments (design 4c-2) and, in the outcomes, two pre-period
columns, `sessions_pre_7d` and `revenue_usd_pre_7d` (design 29, CUPED). The exposures are
byte-identical to the files first written at the merge of pull request 31 (`15b1aa4`), every other
column of the assignments is unchanged row by row, and every other column of the outcomes is
unchanged row by row (the new columns draw from the random stream after all the old ones).
Measured on this file: the correlation of `sessions_pre_7d` with `sessions_7d` is 0.576, and of
`revenue_usd_pre_7d` with `revenue_usd_7d` is -0.01. DuckDB 1.5.6 wrote the CSV, in
its default format: UTF-8, a header row, timestamps such as `2026-04-26 17:43:48+00`. DuckDB
writes a timestamp in the session's time zone, so the snippet sets it to UTC: without that line a
machine in another zone writes other offsets (`+05:30`, `-07`), other bytes, and files that
Referee's own loader refuses. With the line regenerating gives byte-identical files (checked when
the fixture was added and again when the column was, with the time zone of the machine set to UTC,
Asia/Kolkata and America/Los_Angeles). `manifest.json` holds each file's row count and SHA-256; the
tests compare the SHA-256 values, and the row counts and the generator block are documentation.

## What it is not

A snapshot, not a mirror. If the lab's generator changes, this directory does not change with
it; regenerate it with the commands above and update `manifest.json` and the figures the tests
pin. The lab's tests check properties of the generator (the columns, the first-seen time being the
player's `acquired_at_utc`, the planted effects, the ids), not the bytes of these tables, so a
change in the lab does not by itself change or flag this snapshot.
