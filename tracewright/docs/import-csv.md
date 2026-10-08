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
in a header does not silently drop data. Every error names the row (row 1 is the header).

The file must be UTF-8 and at most 5 MB. See [`examples/current-tracking.csv`](../examples/current-tracking.csv).

## What the importer does not do

It reads the structure, not the data: nothing checks that the events in the CSV are really being
sent. It does not read Segment, Amplitude or Mixpanel exports directly; export or convert to the
columns above first. Metrics are not part of the CSV; add them to the generated YAML by hand if you
want the coverage rules (COV-*) to apply.
