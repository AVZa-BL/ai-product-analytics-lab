# Referee

A deterministic reviewer for A/B/n experiments: *ruff for experiments*. Every warning is a named rule, and advice is generated from rules, not improvised. Referee is advisory only. It never ships, stops or decides anything; it returns findings with severity, evidence and remediation.

All data used to develop and test Referee is synthetic. The project contains no production, customer, or employer data.

## Status

Under development, in milestones. About 80% by milestone count, give or take 10 points: milestones 1 to 4 of the five in the design are built, and milestone 5 is not started. The figure counts milestones, not effort or quality, and the hardening of milestone 4 that is still going (see the pull requests) is inside milestone 4:

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1 | Experiment spec schema and validation | Done |
| 2 | Design-review rules, power calculations, `review-design` CLI | Done |
| 3 | Synthetic experiment in the lab's hybrid scenario | Done |
| 4 | Results review, `review-results` CLI, decision memo | Done: the export reader and the statistics (4a), the data-fit rules (4b-1), the effect rules (4b-2: RES-004, RES-007 and RES-008, with the design rule DES-009), the report and command (4c-1), the lab's `first_seen_at_utc` column (4c-2) and the decision memo, `--format memo` (4c-3) |
| 5 | Narration layer (optional): a language model restates only findings the engine emitted, with an evaluation set of mostly refusals; README case-study section | Not started |

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

Referee is advisory. `proceed` means the design raised none of the objections of the 18 design-review rules in [`docs/rules.md`](docs/rules.md), the catalogue with what triggers each and why it matters. It does not mean the experiment is worth running. The catalogue also lists the nine results rules built so far (RES-001, RES-002, RES-003, RES-004, RES-007, RES-008, RES-011, RES-012, RES-013); they read an experiment's data as well as its spec, and `review-results` runs them (below).

Things to know when writing a spec:

- Quote the hypothesis key: `"null": ...`. An unquoted `null:` is read by YAML as an empty key, and Referee refuses it with a message that says so.
- Repeated keys, aliases (`*x`) and merge keys (`<<`) are refused, because YAML would resolve them silently.
- Write numbers with a dot: `5e-2` is read as text by YAML 1.1, while `0.05` and `5.0e-2` are numbers.
- The report carries the spec's SHA-256 fingerprint, which ignores comments, key order and layout, and the Referee version. The same spec reviewed by the same Referee gives the same output byte for byte.

The design and its amendments are in [`docs/design/`](docs/design/2026-09-28-referee-experiment-review-design.md).

## Reviewing results

`review-results` reads an experiment's exported data against its spec, runs the results rules and reports a verdict. The data is a folder of the lab's three CSV files, `experiment_assignments.csv`, `experiment_exposures.csv` and `experiment_outcomes.csv`, and may hold a `manifest.json`. From this folder:

```bash
python -m referee review-results examples/offer-page-results.yaml \
    tests/data/hybrid_offer_page_5000 --experiment-id hybrid_offer_page \
    --as-of 2026-06-30T00:00:00Z
```

The example reads the committed lab export and finds its planted problems: the arms are not the size the allocation promised (RES-001), players were first exposed after they had bought (RES-012), an arm's configuration changed (RES-013), and the effect differs between cohorts (RES-007). The verdict is **invalid**.

| Verdict | Meaning | Exit status |
| --- | --- | --- |
| `clear` | The rules that ran found nothing that blocks or warns. It does not say the effect is real. | 0 |
| `caution` | At least one warning, no blocker | 0 |
| `invalid` | At least one blocker | 1 |

Status 2 means the spec or the data cannot be read or reviewed (the problems are listed on stderr, up to 1,000, with their exact number), and 3 a failure inside Referee. `--experiment-id` is required; when it is left out the experiment ids in the export are listed. `--as-of` says when the export was taken, as an ISO 8601 time in UTC. It replaces the `exported_at_utc` of `manifest.json`, and without either the report says completeness of the outcome windows was not checked.

`--format memo` writes the same review as a decision memo in markdown, in the analytics lab's template: Decision, Observed facts, Assumptions and uncertainty, Data-quality qualification and Reproducibility, in that order. It is advisory like the report (its Decision says what the blocking rules advise and that shipping, stopping or continuing is not decided here), it is built from the report and from nothing else, and the same inputs give the same bytes on one machine with the same output encoding (a title or an arm that is not ASCII is written differently by a stdout that cannot hold it). When the assignments carry `first_seen_at_utc`, the JSON report, the memo and RES-007's note (when RES-007 has a finding; the default text report says nothing of it otherwise) say whether the declared `population.kind` agrees with it: a player first seen before the origin is an existing user, one first seen at or after it a new user, and the population is what more than half of its players are.

The report states the spec's fingerprint and the SHA-256 of each CSV file, the origin the weeks were counted from, the first and last assignment, the players assigned, analysed and ignored, whether the run is an interim one, whether the same rules fire at the same severity if the origin is 1 to 6 days earlier (not run when `design.start_utc` is registered; it costs six more reviews, about 4 s on the example on the development machine and about twice that on a slower one), one line for each of RES-004, RES-007 and RES-008 even when it found nothing, the effect of the primary metric among the players whose outcome window had closed (labelled not to be read when RES-001, RES-003 or RES-012 blocks, and as underpowered when RES-002 does), and every finding with its evidence. `--format json` holds every row; the text lists at most 1,000 rows of a list and says so. Anything in the text that could move a terminal or forge a line (a control character or a newline in a title, an experiment or a player id) is written as an escape. The same spec and data reviewed by the same Referee on one machine give the same bytes. Between machines a float may differ in its last digits.

## Working on it

Referee is self-contained. Run everything from this folder (`referee/`), with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
python -m pytest -q                # the tests (about a minute)
python -m pytest -q -m study     # the simulation studies the design rests on (about 3 minutes;
                                 # naming a study file without -m study selects nothing)
```

The cohort test's false-alarm rate and power were measured by a simulation that is part of the tests: `python tests/cohort_simulation.py --reps 5000 --out docs/simulations/cohort_trigger_null.json` repeats the study of design section 21.5 (about four minutes; add `--power` for the fade study), and the study tests (`-m study`) re-run a handful of its cells. `python tests/cohort_simulation.py --heavy --reps 5000 --printed-reps 3000 --workers 4 --out docs/simulations/cohort_trigger_heavy.json` repeats the study of heavy-tailed outcomes, unequal arms and the shift a finding prints as the smallest change it could have seen (about half an hour on four cores; `--workers` spreads the cells over processes and changes no number).

The pooled effect of revenue-like metrics (how often Welch's interval and a percentile bootstrap interval miss the true difference, and what candidate heavy-tail warnings say) was measured by `python tests/pooled_simulation.py --workers 4 --out docs/simulations/pooled_effect_heavy.json` (design section 21.10; about forty minutes on four cores; `--workers` spreads the cells over processes and changes no number), and the study tests (`-m study`) make a handful of its rows again. RES-008 quotes those rates from `src/referee/pooled_rates_table.py`, which `python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py` writes from that file (design section 21.11); a test makes it again and compares it with the committed copy.

The runtime dependencies are PyYAML (to read spec files), NumPy and SciPy (the results statistics: the distributions and the seeded bootstrap); the power calculations and design rules use the standard library. `pytest`, `ruff` and `statsmodels` (which the tests check the power formulas and the statistics against) are development tools.
