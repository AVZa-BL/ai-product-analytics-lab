# Referee

A deterministic reviewer for A/B/n experiments: *ruff for experiments*. Every warning is a named rule, and advice is generated from rules, not improvised. Referee is advisory only. It never ships, stops or decides anything; it returns findings with severity, evidence and remediation.

All data used to develop and test Referee is synthetic. The project contains no production, customer, or employer data.

## Status

Under development, in milestones:

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1 | Experiment spec schema and validation | Done |
| 2 | Design-review rules, power calculations, `review-design` CLI | Done |
| 3 | Synthetic experiment in the lab's hybrid scenario | Done |
| 4 | Results review, `review-results` CLI, decision memo | In progress: the export reader and the statistics (4a) are done; the data-fit rules (4b-1) are built; of the effect rules (4b-2) RES-004, RES-007 and RES-008 are built, with the design rule DES-009; the report, the command and the memo (4c) are planned |

## Reviewing a design

Write the experiment as a YAML spec, then run the review from this folder:

```bash
python -m referee review-design examples/offer-page-underpowered.yaml
python -m referee review-design examples/offer-page-powered.yaml --format json
```

The first prints a review that recommends **revise**: the design needs 389,060 units and its 14 days deliver 58,800. The second recommends **proceed**: the same experiment planned for 98 days, with every optional field declared. Both examples are commented, and the second is the one to copy.

| Exit status | Meaning |
| --- | --- |
| 0 | The review found no blocker |
| 1 | It found at least one blocker |
| 2 | The spec cannot be read or is not valid (every violation is listed) |
| 3 | A failure inside Referee itself |

Referee is advisory. `proceed` means the design raised none of the objections of the 18 design-review rules in [`docs/rules.md`](docs/rules.md), the catalogue with what triggers each and why it matters. It does not mean the experiment is worth running. The catalogue also lists the nine results rules built so far (RES-001, RES-002, RES-003, RES-004, RES-007, RES-008, RES-011, RES-012, RES-013); they read an experiment's data as well as its spec, and no command runs them yet.

Things to know when writing a spec:

- Quote the hypothesis key: `"null": ...`. An unquoted `null:` is read by YAML as an empty key, and Referee refuses it with a message that says so.
- Repeated keys, aliases (`*x`) and merge keys (`<<`) are refused, because YAML would resolve them silently.
- Write numbers with a dot: `5e-2` is read as text by YAML 1.1, while `0.05` and `5.0e-2` are numbers.
- The report carries the spec's SHA-256 fingerprint, which ignores comments, key order and layout, and the Referee version. The same spec reviewed by the same Referee gives the same output byte for byte.

The design and its amendments are in [`docs/design/`](docs/design/2026-09-28-referee-experiment-review-design.md).

## Working on it

Referee is self-contained. Run everything from this folder (`referee/`), with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
python -m pytest -q
```

The cohort test's false-alarm rate and power were measured by a simulation that is part of the tests: `python tests/cohort_simulation.py --reps 5000 --out docs/simulations/cohort_trigger_null.json` repeats the study of design section 21.5 (about four minutes; add `--power` for the fade study), and the tests re-run a handful of its cells. `python tests/cohort_simulation.py --heavy --reps 5000 --printed-reps 3000 --workers 4 --out docs/simulations/cohort_trigger_heavy.json` repeats the study of heavy-tailed outcomes, unequal arms and the shift a finding prints as the smallest change it could have seen (about half an hour on four cores; `--workers` spreads the cells over processes and changes no number).

The pooled effect of revenue-like metrics (how often Welch's interval and a percentile bootstrap interval miss the true difference, and what candidate heavy-tail warnings say) was measured by `python tests/pooled_simulation.py --workers 4 --out docs/simulations/pooled_effect_heavy.json` (design section 21.10; about forty minutes on four cores; `--workers` spreads the cells over processes and changes no number), and the tests make a handful of its rows again. RES-008 quotes those rates from `src/referee/pooled_rates_table.py`, which `python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py` writes from that file (design section 21.11); a test makes it again and compares it with the committed copy.

The runtime dependencies are PyYAML (to read spec files), NumPy and SciPy (the results statistics: the distributions and the seeded bootstrap); the power calculations and design rules use the standard library. `pytest`, `ruff` and `statsmodels` (which the tests check the power formulas and the statistics against) are development tools.
