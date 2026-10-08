# Importing your current tracking from a CSV

`tracewright import-plan` turns a spreadsheet export of your tracking into a plan file that
`propose` and `review-plan` can read:

```bash
python -m tracewright import-plan examples/current-tracking.csv \
    --id puzzle_core --title "Puzzle game core tracking" \
    --identity-key player_id --owner game-analytics --out current-plan.yaml
```

`--identity-key` is the property that ties an event to a user or device (repeat it for several).
`--owner` is the default owner of every event. Without `--out` the YAML goes to standard output.

## Format

A header row is required. One row is one property of one event. A row whose `property` is empty
describes the event itself.

| Column | Used on | Meaning |
| --- | --- | --- |
| `event` | every row | Event name. Required. |
| `property` | property rows | Property name. Empty on a row that describes the event. |
| `type` | property rows | `string`, `integer`, `number`, `boolean`, `timestamp` or `enum`. Default `string`. |
| `required` | property rows | `true`/`false`, `yes`/`no`, `1`/`0`. Blank means false. |
| `pii` | property rows | Same spellings. Blank means false. |
| `allowed_values` | property rows | Values separated by `\|`, for an `enum`. |
| `description` | both | On a property row, the property; on an event row, the event. |
| `trigger`, `owner`, `status` | event | Say it on any row of the event; if repeated it must agree. `status` is `active`, `planned` or `deprecated`. |

All columns except `event` are optional. A column that is not in the table is refused, so a typo
in a header does not silently drop data.

**Errors.** Problems in a row's own fields name the row (row 1 is the header): an empty event, a
bad `true`/`false`, an unknown `type`, a property declared twice, a row with more cells than the
header (usually an unquoted comma in a value), conflicting event fields, or type, `required`, `pii`
or `allowed_values` filled in on a row with no property name. A problem that is found only when the
whole plan is validated, such as a bad `--id`, is reported by field path.

**Format.** Comma-separated, UTF-8, at most 5 MB. Excel in some locales writes semicolons; save as
"CSV UTF-8 (Comma delimited)". The importer does not guess the delimiter. `--out` is not
overwritten unless `--force` is given, because the generated YAML is meant to be edited by hand. See [`examples/current-tracking.csv`](../examples/current-tracking.csv).

## Getting your tracking out of Google Sheets today

The importer reads a CSV file, not a Google Sheet directly (reading a sheet directly is planned, see the README, *Next*). To use a sheet now:

1. Open the tab that holds the tracking calls. The export covers one tab at a time.
2. **File, Download, Comma Separated Values (.csv)**. The file is UTF-8 and comma-separated, which is what the importer requires.
3. Make the first row use the column names above (`event`, `property`, `type`, and so on). A header the importer does not know is refused, so a sheet with its own headers must be renamed first; keep a copy of the original.
4. Run `import-plan` and read the YAML it writes before trusting it. The importer checks the structure, not whether the sheet is right.

Several tabs mean several exports; combine them into one CSV with the same header, or import one at a time into separate plans. A Google Doc with a design description is exported with **File, Download, Plain Text (.txt)** or **PDF Document (.pdf)** and passed to `propose --doc`.

## What the importer does not do

It reads the structure, not the data: nothing checks that the events in the CSV are really being
sent. It does not read Segment, Amplitude or Mixpanel exports directly; export or convert to the
columns above first. Metrics are not part of the CSV; add them to the generated YAML by hand if you
want the coverage rules (COV-*) to apply.
