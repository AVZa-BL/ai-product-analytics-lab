# Referee

A deterministic reviewer for A/B/n experiments: *ruff for experiments*. Every warning is a named rule, and advice is generated from rules, not improvised. Referee is advisory only. It never ships, stops or decides anything; it returns findings with severity, evidence and remediation.

All data used to develop and test Referee is synthetic. The project contains no production, customer, or employer data.

## Status

Under development, in milestones. About 80% by milestone count, give or take 10 points: milestones 1 to 4 of the five in the design are built; milestone 5 is built and tested offline and is not counted as done, because its model path has never been run with a model. The figure counts milestones, not effort or quality, and the hardening of milestone 4 that is still going (see the pull requests) is inside milestone 4:

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1 | Experiment spec schema and validation | Done |
| 2 | Design-review rules, power calculations, `review-design` CLI | Done |
| 3 | Synthetic experiment in the lab's hybrid scenario | Done |
| 4 | Results review, `review-results` CLI, decision memo | Done: the export reader and the statistics (4a), the data-fit rules (4b-1), the effect rules (4b-2: RES-004, RES-007 and RES-008, with the design rule DES-009), the report and command (4c-1), the lab's `first_seen_at_utc` column (4c-2) and the decision memo, `--format memo` (4c-3) |
| 5 | Narration layer: `referee narrate` answers four kinds of question about a saved results report with the engine's own sentences and numbers rounded to six significant digits, and refuses by code what its router recognises as another kind of question; an optional path lets a command of the user's choice select what to show, by identifier. Built and tested offline with fake narrators and a stub subprocess; the model path has never been run with a model. A checker for model-written restatements was probed by language-model agents and a program, not through Referee, and no model was run through Referee: 0 of the 81 catalogue sentences contain none of the study's loaded words under its full list and 69 under the digits-only ablation, and the checker admitted 0 of 28 hand-written harmful probes under the full list (9 and 26 of 28 under the qualifiers-and-digits and digits-only ablations) (docs/grounding-study.md). The model-written channel is not shipped because the user decided that the model path selects and never writes. | Built and tested offline; not counted as done |

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

- `design.pre_period_covariate` names a column of the outcomes file measured before each player's first exposure; the results review then shows the adjusted estimate (CUPED, design section 29) beside the unadjusted one, and says so when the covariate cannot be used. See [`docs/data-contract.md`](docs/data-contract.md).
- A spec names the columns that hold its metrics: `column:` on the primary metric and on each guardrail, and `secondary_metrics:` for ones that are neither (only `--mode monitor` analyses them; a results review lists each, says whether it could be read, and is not affected by it). The contract, what a column may hold and why a metric cannot be read, is in [`docs/data-contract.md`](docs/data-contract.md), with a worked example in `examples/custom-metrics/`.
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

`--format memo` writes the same review as a decision memo in markdown, in the analytics lab's template: Decision, Observed facts, Assumptions and uncertainty, Data-quality qualification and Reproducibility, in that order. It is advisory like the report (its Decision says what the blocking rules advise and that shipping, stopping or continuing is not decided here), it is built from the report and from nothing else, and the same inputs give the same bytes on one machine with the same output encoding (a title or an arm that is not ASCII is written differently by a stdout that cannot hold it). When the assignments carry `first_seen_at_utc`, the JSON report, the memo and RES-007's note (when RES-007 has a finding; the default text report says nothing of it otherwise) say whether the declared `population.kind` agrees with it: a player first seen before the origin is an existing user, one first seen at or after it a new user, and the population is what more than half of its players are (at exactly half it is neither, and the report says so).

The report states the spec's fingerprint and the SHA-256 of each CSV file, the origin the weeks were counted from, the first and last assignment, the players assigned, analysed and ignored, whether the run is an interim one (the memo instead states how the time of the export and the span of the assignments compare with the planned end and the planned days), whether the same rules fire at the same severity if the origin is 1 to 6 days earlier (not run when `design.start_utc` is registered; it costs six more reviews, about 4 s on the example on the development machine and about twice that on a slower one), one line for each of RES-004, RES-007 and RES-008 even when it found nothing, the effect of the primary metric among the players whose outcome window had closed (labelled not to be read when RES-001, RES-003 or RES-012 blocks, and as underpowered when RES-002 does), and every finding with its evidence. `--format json` holds every row; the text lists at most 1,000 rows of a list and says so. Anything in the text that could move a terminal or forge a line (a control character or a newline in a title, an experiment or a player id) is written as an escape. The same spec and data reviewed by the same Referee on one machine give the same bytes. Between machines a float may differ in its last digits.

## Monitoring a running experiment

`review-results` judges an experiment as finished, so an unfinished one is `invalid` at once: RES-002 (too few players) and RES-003 (too short) block until it ends. `--mode monitor` asks other questions of the same spec and export: how far has it got, is the data healthy, are the guardrails holding, and what does the primary metric look like so far.

```bash
python -m referee review-results examples/offer-page-results.yaml \
    tests/data/hybrid_offer_page_5000 --experiment-id hybrid_offer_page \
    --as-of 2026-06-30T00:00:00Z --mode monitor
```

| Status | Meaning | Exit status |
| --- | --- | --- |
| `on_track` | Nothing needs attention | 0 |
| `attention` | A warning from a data-health rule (RES-011, RES-012, RES-013), a guardrail beyond its tolerance, or a declared metric that could not be read | 0 |
| `stop_for_cause` | A sample ratio mismatch (RES-001) or a late-exposure imbalance (RES-012 at blocker level): find the cause before reading anything | 1 |

These words are the monitor's own, not the verdicts of `review-results`. The report lists progress (players against the registered n and days against the registered minimum, which are numbers, never a status), every metric the spec declares with its role and whether it could be read and why not (a metric is never skipped silently), the primary metric's interval so far with no p value, and each guardrail with its interval and number of players. A guardrail beyond its tolerance is `attention` at an interim look, never a stop: an unadjusted 95% interval read at several looks raises false blockers (design section 25), and Referee has no error budget over looks yet. The cohort test (RES-007) and the heavy-tail note (RES-008) are not run. `--format text` or `json`; no memo. A primary metric whose column the export does not hold is refused (status 2) with the reason; any other declared metric that cannot be read is a line of the ledger.

## Asking questions about a saved review

<!-- BEGIN narration (generated by python tests/narration_readme.py; do not edit) -->
By default no language model runs when you use this command; with --llm-command, a command you name may call one. Language-model agents wrote the code, tests, labels and reviews and every question except the three quoted from the design document; no human labelled a question.

`python -m referee narrate REPORT [--question TEXT]` reads a saved results report, the JSON of `review-results --format json`, and prints one page about it. It answers four kinds of question by code, with the engine's own sentences and the report's numbers rounded to six significant digits: a summary of the review, one finding explained, what to do next, and what was checked. It refuses by code what its router, a table of words and not a model, recognises as another kind of question (a request to ship or to stop, to be told that the experiment is fine, for the effect's numbers, for a forecast, for a breakdown the report does not hold, and so on), and a question it does not recognise as one of the four. The page is advice and not a gate: every page ends by saying that its exit status does not mean the experiment is valid, so do not write `referee narrate report.json && ship`. [`docs/narration.md`](docs/narration.md) has the contract: what the page guarantees and what it does not, the exit statuses, and what the command reads.

Three questions quoted in the design document, put to the report of the example under 'Reviewing results' (committed as `tests/golden/offer-page-results.json`; its verdict is invalid). None is one of the four kinds, so each is refused: the page says what it understood the question as, without repeating its words, prints the Decision section of the report's memo, says what the layer does not do for that kind of question, and points into the report. Each page is whole, as the command above it printed it, with exit status 0: a page was printed, whatever the verdict (`review-results` exits 1 on an invalid report).

```bash
python -m referee narrate tests/golden/offer-page-results.json --question "can we call it on day 3?"
```

```text
Report of experiment hybrid_offer_page, export taken 2026-06-30T00:00:00Z.
Verdict: invalid. Blocking rules: RES-001, RES-002. Findings: 2 blockers, 4 warnings, 0 info.
Question understood as: a question this layer does not answer (categories matched: stopping).

Do not read the effect. RES-001 blocks this review, and its remediation says to settle what it found before the effect is read.

RES-002 also blocks: `control` (926 analysed, 2,107 required), `variant_b` (969 analysed, 2,107 required) and `variant_c` (731 analysed, 2,107 required) are smaller than the registered sample size. Once the effect can be read, and if they are still smaller, report the result as underpowered: a small difference is not evidence of no effect.

Decided here: whether the rules object to reading this experiment's result as it stands. Not decided here: whether to ship, stop or continue the experiment. Referee is advisory, and that decision rests with the experiment's owner.

The memo's other sections are not part of this page.

This layer does not say whether an experiment may be stopped, called or read at the point it has reached.
Days observed: 21; days planned: 21.
Raised in this report, about the length and size of the run:
  [RES-002.title] Fewer players than the registered sample size
RES-003 ran and raised no finding.
A rule reads only what the export holds. This is not agreement with the question, and it does not say the effect is real.

Not a decision and not a gate. This page advises only; its exit status does not mean the experiment is valid.
```

```bash
python -m referee narrate tests/golden/offer-page-results.json --question "arm C is significant in Germany, ship there?"
```

```text
Report of experiment hybrid_offer_page, export taken 2026-06-30T00:00:00Z.
Verdict: invalid. Blocking rules: RES-001, RES-002. Findings: 2 blockers, 4 warnings, 0 info.
Question understood as: a question this layer does not answer (categories matched: ship_decision, subgroup).

Do not read the effect. RES-001 blocks this review, and its remediation says to settle what it found before the effect is read.

RES-002 also blocks: `control` (926 analysed, 2,107 required), `variant_b` (969 analysed, 2,107 required) and `variant_c` (731 analysed, 2,107 required) are smaller than the registered sample size. Once the effect can be read, and if they are still smaller, report the result as underpowered: a small difference is not evidence of no effect.

Decided here: whether the rules object to reading this experiment's result as it stands. Not decided here: whether to ship, stop or continue the experiment. Referee is advisory, and that decision rests with the experiment's owner.

The memo's other sections are not part of this page.

This layer does not decide, recommend or approve shipping, keeping or dropping the change, and does not say which variant wins.
The blocking rules of the report, by ID and title:
  [RES-001.title] Sample ratio mismatch: the arms are not the size the allocation promised
  [RES-002.title] Fewer players than the registered sample size

This layer does not report on a part of the players that the arms do not define, such as a country, a platform or a device.
The report counts players by arm; its cohort test divides them by cohort of first exposure. The catalogue says of that test, for when it flags a difference:
  [RES-007.why.2] If the effect differs between those cohorts, the pooled figure describes none of them well, and what a later launch sees can differ from it.
The report holds counts by arm and no breakdown by country, platform or device.

Not a decision and not a gate. This page advises only; its exit status does not mean the experiment is valid.
```

```bash
python -m referee narrate tests/golden/offer-page-results.json --question "SRM is only 0.4%, fine, right?"
```

```text
Report of experiment hybrid_offer_page, export taken 2026-06-30T00:00:00Z.
Verdict: invalid. Blocking rules: RES-001, RES-002. Findings: 2 blockers, 4 warnings, 0 info.
Question understood as: a question this layer does not answer (categories matched: reassurance).

Do not read the effect. RES-001 blocks this review, and its remediation says to settle what it found before the effect is read.

RES-002 also blocks: `control` (926 analysed, 2,107 required), `variant_b` (969 analysed, 2,107 required) and `variant_c` (731 analysed, 2,107 required) are smaller than the registered sample size. Once the effect can be read, and if they are still smaller, report the result as underpowered: a small difference is not evidence of no effect.

Decided here: whether the rules object to reading this experiment's result as it stands. Not decided here: whether to ship, stop or continue the experiment. Referee is advisory, and that decision rests with the experiment's owner.

The memo's other sections are not part of this page.

This layer does not agree that the experiment, its data, a result, a finding or a number is fine, valid, trustworthy or safe to ignore.
The finding the question names, as the report holds it (blocker):
  [RES-001.title] Sample ratio mismatch: the arms are not the size the allocation promised
  significance level of the sample ratio test: 0.001
  registered allocation (control): 0.333333
  registered allocation (variant_b): 0.333333
  registered allocation (variant_c): 0.333333
  players assigned (control): 997
  players assigned (variant_b): 1,046
  players assigned (variant_c): 781
  players expected at the registered allocation (control): 941.33
  players expected at the registered allocation (variant_b): 941.33
  players expected at the registered allocation (variant_c): 941.33
  chi-squared statistic of the counts: 42.2387
  degrees of freedom of the counts: 2
  p value of the sample ratio test: 6.72961e-10
  test used: chi_square
These are the report's values for it; they are not agreement that it is fine.

Not a decision and not a gate. This page advises only; its exit status does not mean the experiment is valid.
```

### The router on the held-out half

The router's first score was taken once, on 64 questions that language-model agents wrote and labelled, and that were held out from its construction by procedure and not by a technical barrier. Git can show that the narration modules the router loads were frozen before it was scored (freeze commit `386f817c4bed70e61760298ac7a7a8f00a727289`); it does not show that nobody had read the half. The figures are agreement with the agent-authored taxonomy, as k of n with 95% Clopper-Pearson intervals. They say nothing about usefulness, readability, a model's behaviour or real users' phrasing, none of which was measured, and the router is not injection-proof and its twelve categories are not complete. Of the 44 questions labelled with refusal categories:

- Strict: 42 of 44 (0.845 to 0.994): the router's first category is in the label.
- Other: 2 of 44 (0.006 to 0.155): it refused, but its first category is not in the label.
- Answered: 0 of 44 (0.000 to 0.080): it returned an answer, not a refusal.
- Refused at all (strict plus other): the router 44 of 44 (0.920 to 1.000); a baseline that refuses on a list of trigger words 32 of 44 (0.572 to 0.850); a baseline that answers when an intent keyword matches 26 of 44 (0.432 to 0.737).
- False refusal, of the 20 questions labelled with one of the four kinds: the router 1 of 20 (0.001 to 0.249); the trigger words 1 of 20 (0.001 to 0.249); the intent keywords 1 of 20 (0.001 to 0.249).
- Wrong intent or target, of the same 20: the router 2 of 20 (0.012 to 0.317); it answered something else.

All 5 misses of the first score, each with its index in the half, its kind, its label, what the router returned and the question verbatim as a JSON string:

- 18 (other): label refuse reassurance; router refuse injection, reassurance; "This report has no blocker and no warning, so I can treat the whole experiment as valid and sound, yes?"
- 46 (wrong_intent): label answer next_steps; router answer summary; "Which of the issues in this report should be dealt with first, and what is the follow-up for each?"
- 47 (wrong_intent): label answer next_steps; router answer checked; "There are only warnings in this report. What does it advise us to check or tidy up in the experiment data?"
- 57 (other): label refuse rewording; router refuse subgroup, rewording; "Please give me these findings in Spanish for our regional team."
- 64 (false_refusal): label answer checked; router out_of_scope; "What exactly did the review inspect, and is there anything it did not get to?"

[`docs/narration-evaluation.md`](docs/narration-evaluation.md) puts the first score beside a fresh run of the router, and says how the freeze was checked and what the half does not show.

### With `--llm-command`

**`--llm-command` sends the report's counts, p values, rates and allocations to whatever the command contacts.** The arms' names become `A1` (the control), `A2`, `A3`, which hides the names and nothing else: aliases are not anonymisation. `--show-request` prints what would leave. Referee does not control what the command does with it.

`--llm-command CMD` runs only a command you name, once, and only for a summary, the next steps or the explanation of one finding; without it no process is started. The command's part is selection by identifier and never wording: it is given a sheet in which each sentence and fact of the findings in scope has an identifier, and returns identifiers only, so it chooses what leads under `Selected:` while code prints the rest of what the question permits under `Not selected by the narrator:`, every sentence being the engine's own. It never sees your question, only the kind of question and the rule it names. The selection does not make the page relevant, and the labels are no ranking. `--show-request` prints the exact request the command would receive, one line of JSON, and starts nothing; the first 1000 of its 6,988 characters:

```bash
python -m referee narrate tests/golden/offer-page-results.json --llm-command "cat selection.json" --show-request
```

```text
{"max_tokens":4096,"schema":"referee-narration-request/1","system":"You select identifiers from a sheet. The sheet is the user message: JSON that lists, for each finding of the review of an experiment, its sentences and facts, each with an identifier. Answer with ONLY one JSON object of schema referee-narration-output/1 and nothing else: {\"schema\": \"referee-narration-output/1\", \"findings\": [{\"id\": <rule_id>, \"facts\": [<fact id>, ...], \"sentences\": [<sentence id>, ...]}]}. Every value is an identifier copied from the sheet. There is no field for text, and no number, explanation or refusal. Give an entry for every blocker and warning and for the task's target, each with at least one sentence of every kind (why, do) that the sheet lists for it; an info finding may be left out. What you select leads the page and code prints the rest after it.","user":"{\"arms\":[{\"alias\":\"A1\",\"role\":\"control\"},{\"alias\":\"A2\",\"role\":\"variant\"},{\"alias\":\"A3\",\"role\":\"variant\ ...
```

A file can stand in for the command: `cat selection.json` ignores the request it is sent and prints the file, so the path can be followed with no model. `selection.json` holds one reason for each finding of the report. The page starts like this (its first 20 of 62 lines):

```bash
cat > selection.json <<'EOF'
{"schema": "referee-narration-output/1", "findings": [{"id": "RES-001", "facts": [], "sentences": ["RES-001.why.1"]}, {"id": "RES-002", "facts": [], "sentences": ["RES-002.why.1"]}, {"id": "RES-007", "facts": [], "sentences": ["RES-007.why.1"]}, {"id": "RES-008", "facts": [], "sentences": ["RES-008.why.1"]}, {"id": "RES-012", "facts": [], "sentences": ["RES-012.why.1"]}, {"id": "RES-013", "facts": [], "sentences": ["RES-013.why.1"]}]}
EOF
python -m referee narrate tests/golden/offer-page-results.json --llm-command "cat selection.json"
```

```text
Report of experiment hybrid_offer_page, export taken 2026-06-30T00:00:00Z.
Verdict: invalid. Blocking rules: RES-001, RES-002. Findings: 2 blockers, 4 warnings, 0 info.
Question understood as: a summary of the review.
Chosen by: the output of --llm-command (checked for scope, source and coverage, not relevance).
For each finding narrated below, everything this question permits is printed; the narrator chose only what leads and which info findings are narrated; the labels are not a ranking of relevance.

Do not read the effect. RES-001 blocks this review, and its remediation says to settle what it found before the effect is read.

RES-002 also blocks: `control` (926 analysed, 2,107 required), `variant_b` (969 analysed, 2,107 required) and `variant_c` (731 analysed, 2,107 required) are smaller than the registered sample size. Once the effect can be read, and if they are still smaller, report the result as underpowered: a small difference is not evidence of no effect.

Decided here: whether the rules object to reading this experiment's result as it stands. Not decided here: whether to ship, stop or continue the experiment. Referee is advisory, and that decision rests with the experiment's owner.

The memo's other sections are not part of this page.

RES-001 blocker: Sample ratio mismatch: the arms are not the size the allocation promised
Selected:
  [RES-001.why.1] Random assignment gives arms of the registered sizes, up to chance.
Not selected by the narrator:
  [RES-001.why.2] A mismatch this large means the arms were not formed as designed (a fault in assignment, in logging or in filtering), so who is in each arm may differ and a difference in the metrics can come from that.
  [RES-001.why.3] No estimate of the effect can be trusted until the cause is known.
...
```

**The model path has never been run with a model.** It has met only fake narrators and a stub command, so what a model would return is not known. Referee ships no wrapper for a model provider, no default command and no `--model` option.
<!-- END narration -->

## Working on it

Referee is self-contained. Run everything from this folder (`referee/`), with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
python -m pytest -q                # the tests (about two minutes)
python -m pytest -q -m study     # the simulation studies the design rests on (about 3 minutes;
                                 # naming a study file without -m study selects nothing)
```

The cohort test's false-alarm rate and power were measured by a simulation that is part of the tests: `python tests/cohort_simulation.py --reps 5000 --out docs/simulations/cohort_trigger_null.json` repeats the study of design section 21.5 (about four minutes; add `--power` for the fade study), and the study tests (`-m study`) re-run a handful of its cells. `python tests/cohort_simulation.py --heavy --reps 5000 --printed-reps 3000 --workers 4 --out docs/simulations/cohort_trigger_heavy.json` repeats the study of heavy-tailed outcomes, unequal arms and the shift a finding prints as the smallest change it could have seen (about half an hour on four cores; `--workers` spreads the cells over processes and changes no number).

The pooled effect of revenue-like metrics (how often Welch's interval and a percentile bootstrap interval miss the true difference, and what candidate heavy-tail warnings say) was measured by `python tests/pooled_simulation.py --workers 4 --out docs/simulations/pooled_effect_heavy.json` (design section 21.10; about forty minutes on four cores; `--workers` spreads the cells over processes and changes no number), and the study tests (`-m study`) make a handful of its rows again. RES-008 quotes those rates from `src/referee/pooled_rates_table.py`, which `python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py` writes from that file (design section 21.11); a test makes it again and compares it with the committed copy.

The runtime dependencies are PyYAML (to read spec files), NumPy and SciPy (the results statistics: the distributions and the seeded bootstrap); the power calculations and design rules use the standard library. `pytest`, `ruff` and `statsmodels` (which the tests check the power formulas and the statistics against) are development tools.
