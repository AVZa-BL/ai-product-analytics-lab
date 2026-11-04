---
name: run-referee
description: Build, run, test and drive Referee, the deterministic A/B experiment reviewer (`python -m referee review-design`, `review-results` and `narrate`). Use when asked to run or start Referee, review an experiment spec or a results export, print a page about a saved report, smoke-test the CLI, check an exit status or a report, run its tests or lint, or set up its Python environment.
---

Referee is a Python 3.12 command-line tool and library (no server, no GUI). The agent path is
`.claude/skills/run-referee/smoke.py`: it runs the real command line against the committed examples,
the committed lab export and the committed report of that review, and checks exit statuses, key lines
and JSON fields.

All paths are relative to `referee/` (the folder with `pyproject.toml`); run everything from there.

## Setup

Python must be 3.12 exactly (`requires-python = ">=3.12,<3.13"`). If `python3` is not 3.12, name
the interpreter: `python3.12`, or `uv venv --python 3.12`.

```bash
uv venv --python 3.12 .venv      # skip this line if .venv exists, or add --clear
uv pip install -p .venv/bin/python -q -e '.[dev]'
```

A few seconds to 10 s with uv and a warm cache; a cold cache is download-bound (53 s through the
proxy, measured by a reviewer). Without uv, 35 to 70 s:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -q -e '.[dev]'
```

Check it: `.venv/bin/python -m referee --version` prints `referee <version>`. `.venv/` is gitignored.
The commands below call `.venv/bin/python` directly, so nothing needs activating.

## Run (agent path)

```bash
.venv/bin/python .claude/skills/run-referee/smoke.py
```

Each step is the real `python -m referee ...` in a subprocess (one calls `referee.cli.main` in
process), ending `<n>/<n> steps passed`. The whole run takes about a minute here: each start of
Python costs about 1 s and a results review 8 to 9 s. Groups: `design`, `results`, `narrate`,
`errors`, `inprocess`.

```bash
.venv/bin/python .claude/skills/run-referee/smoke.py --only design          # about 8 s
.venv/bin/python .claude/skills/run-referee/smoke.py --only errors --keep .venv/out
```

`--keep DIR` writes each command's stdout and stderr, numbered (`01-review-results.out`, `.err`, ...);
in the `errors` group the message is in the `.err` file and the `.out` file is empty.
Exit status 0 only if every selected step passed; a failing step prints what it wanted and what it got
(for the exit-status checks, the command and the first 600 characters of stdout and stderr). If a
count or a verdict differs, check whether the example's findings were changed on purpose (README,
`tests/golden/`) before suspecting Referee, and update the numbers in `smoke.py`. The driver finds
`referee/` from its own location, so it can be started from any directory.

To drive Referee by hand, the three commands are:

```bash
.venv/bin/python -m referee review-design examples/offer-page-underpowered.yaml   # REVISE, exit 1
.venv/bin/python -m referee review-design examples/offer-page-powered.yaml --format json   # exit 0
.venv/bin/python -m referee review-results examples/offer-page-results.yaml \
    tests/data/hybrid_offer_page_5000 --experiment-id hybrid_offer_page \
    --as-of 2026-06-30T00:00:00Z --format memo                                    # exit 1
.venv/bin/python -m referee narrate tests/golden/offer-page-results.json     # a summary page, exit 0
.venv/bin/python -m referee narrate tests/golden/offer-page-results.json \
    --question "can we call it on day 3?"                                     # refused by code, exit 0
```

`review-results --format` takes `text` (default), `json` or `memo`; `review-design` takes `text` or
`json`. A spec is a YAML file (`examples/` has three, commented, and `custom-metrics/`, a fourth
with its own export); the data is a folder of the lab's
three CSV files (`tests/data/hybrid_offer_page_5000` is the committed one). `narrate` reads the JSON
of `review-results --format json` (`tests/golden/offer-page-results.json` is the committed one) and
prints one page: it answers four kinds of question by code and refuses the rest (README,
`docs/narration.md`). A running experiment is `review-results --mode monitor` (README, "Monitoring a
running experiment"): the statuses are `on_track` and `attention` (exit 0) and `stop_for_cause`
(exit 1), and `--format memo` is refused (exit 2).

| Exit status | Meaning |
| --- | --- |
| 0 | No blocker (a results verdict of `caution` is still 0) |
| 1 | At least one blocker: a finding, not a crash |
| 2 | The spec or the data cannot be read or is invalid (reasons on stderr) |
| 3 | A failure inside Referee |

`narrate` has its own statuses: 0 a page was printed (an answer or a refusal, whatever the verdict),
1 the output of `--llm-command` failed a check, 2 the report cannot be read or checked or the arguments
are unusable, 3 an internal error, 4 the `--llm-command` failed. Status 0 does not say the experiment
is valid.

## Direct invocation (internals)

`referee.cli.main(argv)` never raises and returns the exit status; the layers under it can be
called without the command line:

```bash
.venv/bin/python - <<'EOF'
from referee.loader import load_spec
from referee.review import review_design
from referee.report import design_report
spec = load_spec("examples/offer-page-underpowered.yaml")
report = design_report(spec, review_design(spec))
print(report["recommendation"], report["blocking_rule_ids"], report["counts"])
EOF
```

Prints `revise ['DES-001', 'PRO-001'] {'blocker': 2, 'warning': 3, 'info': 2}`. For one results
rule or the narration code, run the matching test file instead (`.venv/bin/python -m pytest -q
tests/test_rules_design.py`, `tests/test_narration_command.py`; `tests/test_cli.py` calls `main` in
process); the helpers that build reports are `tests/results_helpers.py` and
`tests/narration_reports.py`.

## Test

```bash
.venv/bin/ruff check src tests                 # All checks passed!
.venv/bin/python -m pytest -q                  # all pass; 2.5 to 4 min here
.venv/bin/python -m pytest -q -m study         # all pass; about 3.5 min here
```

The default run leaves the simulation studies out (`addopts = -m 'not study'`). Naming a study file
without `-m study` selects nothing. The counts grow as the project does; the point is no failures.
The times are for a container that was also doing other work.

## Gotchas

- **Exit status 1 is a finding, not a failure.** The underpowered example and the lab export both
  exit 1 by design. Only 2 and 3 mean something went wrong.
- **`--experiment-id` is required for `review-results`.** Left out, it exits 2 and lists the ids the
  export holds (`hybrid_offer_page`). `--as-of` is optional; without it (and without a manifest
  time) the report says completeness was not checked.
- **A spec's `"null":` key must be quoted.** YAML reads a bare `null:` as null; Referee refuses it
  and says so (exit 2).
- **Same input, same bytes.** The driver checks two runs for identical output; between machines a
  float may differ in its last digits (README).
- **`review-results` takes 8 to 9 s here** on the example because the report includes a sensitivity
  check on the origin of the weeks (six more reviews of the data; README: about 4 s on the
  development machine and about twice that on a slower one). Registering `design.start_utc` in a copy
  of the spec skips it: 2.4 s instead of 7.5 s, measured.
- **Do not give `narrate` an `--llm-command` in a smoke test.** For a summary, next-steps or
  one-finding page it starts the command you name and sends it the report's counts, p values, rates
  and allocations (`docs/narration.md`); the driver never uses it. `--llm-command CMD --show-request`
  prints that request and never starts CMD; `--show-request` without `--llm-command` only says that
  no request would be made.
- **CI lints `src tests` only**, so `ruff check src tests` is the gate; the skill folder is not in it.

## Troubleshooting

- **`ERROR: Package 'referee' requires a different Python: 3.11.17 not in '<3.13,>=3.12'`**: the
  venv was made with `python3` (3.11). Use `python3.12`, or `uv venv --python 3.12`.
- **`referee: error: --experiment-id is required; the export holds: hybrid_offer_page`**: add
  `--experiment-id hybrid_offer_page`.
- **`referee: error: ...: key 'null' is read by YAML as null, not as text`**: quote the key,
  `"null":`.
- **`referee: error: PATH cannot be used as a results report (N problems):`** from `narrate`: give it
  the JSON of `review-results --format json`, not a YAML spec, a CSV folder, the JSON of
  `review-design`, or a path that does not exist (all exit 2).
- **`cannot import referee (No module named 'referee'); run this with the venv's python`** from
  the driver: run it as `.venv/bin/python .claude/skills/run-referee/smoke.py`, not with the system
  `python3`.
