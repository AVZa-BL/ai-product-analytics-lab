# Referee

A deterministic reviewer for A/B/n experiments: *ruff for experiments*. Every warning is a named rule, and advice is generated from rules, not improvised. Referee is advisory only. It never ships, stops or decides anything; it returns findings with severity, evidence and remediation.

All data used to develop and test Referee is synthetic. The project contains no production, customer, or employer data.

## Status

Under development, in milestones. This one is the first:

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1 | Experiment spec schema and validation | In progress |
| 2 | Design-review rules, power calculations, `review-design` CLI | Planned |
| 3 | Synthetic experiment in the lab's hybrid scenario | Planned |
| 4 | Results review, `review-results` CLI, decision memo | Planned |

## Working on it

Referee is self-contained. Run everything from this folder (`referee/`), with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
python -m pytest -q
```

The project has no runtime dependencies yet. `pytest`, `pyyaml` and `ruff` are development tools.
