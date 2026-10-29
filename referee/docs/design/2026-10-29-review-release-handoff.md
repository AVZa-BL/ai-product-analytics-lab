# `review-release`: a release reviewer inside Referee. Design handoff (2026-10-29)

A handoff, not yet an amendment. It designs a sixth deliverable for Referee: a deterministic review of a product release (a feature, a configuration change, a live event) that was shipped to everyone, with no holdout. It is written before anything is built, in the style of the design document's amendments, and it is scaffolding: when R0 merges the user has accepted sections 15 and 16, and when R9 merges this file is folded into the design document as its next amendment and deleted. (read) marks a figure taken from the repository at `2466b19`; (expected) marks what the lab's data should show once the reviewer exists, and is not evidence; the rest is decision or judgement. A language-model agent wrote this text; no code was written for it.

> **In short** (a plan, in the future tense)
> - `python -m referee review-release SPEC EXPORT_DIR --release-id ID [--as-of TIME] [--format text|json|memo|html]` will read a release spec and an export of daily KPIs, compare each KPI's days after the release with a baseline built from the weeks before it, and report a state for each KPI (`as_expected`, `watch`, `breach`, `too_early`, `not_readable`) and a verdict for the release (`clear`, `watch`, `breach`, `too_early`, `invalid`), from named rules `REL-...` with evidence, reasons and advice.
> - It is a before/after comparison, an interrupted time series without a control group. It never says a release caused anything; it says what moved, by how much against the weeks before, whether that is beyond the registered tolerance, and what else happened in the window that could explain it. Shipping, keeping and rolling back are not decided here.
> - The "dashboard" is a static HTML page the command writes from its own report (R7): one small chart per KPI, no script, no framework, the same bytes for the same inputs. The lab's design excludes a dashboard framework ((read) its section 12), and this stays inside that line.
> - The "AI conclusion" is the narration layer of Amendment 9 reading a release report (R8): the engine's own sentences, a model that selects identifiers and never writes a word. Nothing in this design calls a model.
> - "Monitored by default on every new release" is a release calendar in the export plus a KPI catalogue with `default: true` rows, so a spec can be six lines; alerting is the exit status and the JSON verdict of a scheduled run. Referee sends nothing anywhere.
> - The lab already holds the release case: the live-strategy scenario's season update at day 90, with a planted acquisition-mix shift and a D7 retention drop. No new generator is needed; a small exporter and a committed fixture are (R2).
> - Ten pull requests, R0 to R9, in section 13. The user merges R0; the agent merges the rest on the conditions of Amendment 9, section 24.2.

Terms. A *release* is a row of the export's calendar: an instant in UTC when something changed for every player. *Day 0* is the UTC date of that instant; it belongs to neither window. The *pre window* is a whole number of weeks ending the day before day 0; the *post window* starts the day after day 0 and runs for the spec's horizon, cut at what is readable. A *KPI* is a row of the catalogue: a count or a rate with a direction of good, a maturity in days and a governed reference. A *readable* day of a KPI is one whose date plus the KPI's maturity is not after the export's date. The *baseline* of a KPI is its weekday profile over the pre window (section 5.2). The *level change* is the post window's mean ratio to the baseline, minus one (5.3). A *guardrail* is a KPI the spec gives a registered tolerance. *Shown* and *possible* keep the meaning RES-004 gives them: beyond the tolerance on the whole 95% interval, or on the point estimate only ((read) `docs/rules.md`, RES-004).

## 1. Objective

Give a product team the same discipline for a release that Referee gives an experiment: a review that is the same every time, whose every warning is a named rule with evidence, and whose advice is generated from the rules. The pitch is the same one with one word changed: *ruff for releases*. The review is advisory and its exit status is not a gate.

## 2. Why inside Referee, and why now

- The user's idea, as stated: a dashboard with basic KPIs monitored by default on every new release, a selectable list anchored on a release date, monitoring after it, possible alerts, and an AI conclusion of the feature's current state from the KPI readings. Each part has a home in what exists: the selectable list is a spec read by Referee's loader discipline; the alerts are rules with severities and an exit status; the conclusion is the narration layer; the dashboard is a renderer of the report, like the memo.
- What is reused (read, `src/referee/`): the spec validation pattern (`spec.py`: frozen dataclasses built by `from_dict`, every violation listed, unknown keys rejected), the export reader's contract (`data.py`: CSV read in full, `manifest.json` with `exported_at_utc`, SHA-256 of each file, problems listed with file, line and column), the rule framework (`rules/base.py`: a rule is data plus one function; `docs/rules.md` is generated from it and drift-tested), the report discipline (`report.py`: JSON, text and memo from one dict; no timestamp, host or path; code spans and escapes for every value from a spec or an export; `_HARM_RULES` separating a harm blocker from a validity blocker), the seeded bootstrap and the simulation-study pattern with measured rates quoted into a rule's note (`pooled_rates_table.py`, design 21.10 and 21.11), the CLI's exit statuses, and the narration layer's guarantee (24.1). The runtime dependencies stay NumPy, SciPy and PyYAML ((read) `pyproject.toml`).
- Why not a fourth top-level project: Tracewright's milestones 3 to 5 are not done and its proposals have never met a real model or a real sheet ((read) `tracewright/README.md`); Referee's milestone 5 is in flight (Amendment 9); a third codebase would split the one agent's attention across three tools none of which has met real input. A command inside Referee shares the loader, the rules, the renderers and the tests.
- Why now: the lab's live-strategy memo is already a release analysis, a pre/post D7 retention comparison with an acquisition-mix shift that confounds it ((read) `analytics-lab/reports/live_strategy/d7_retention_diagnostic.md`). The reviewer generalises that memo's method and its caution, and the lab's data exercises it without a new generator.

## 3. What a release review is, and what it is not

- It is an interrupted time series read at the product level: the KPI's days after the release against a baseline built from the weeks before it. Without randomisation the before/after difference confounds the release with time, seasonality, the mix of players, concurrent changes and instrumentation changes. Every page the command prints says so in one fixed sentence, and the memo's Assumptions section names the confounders the data shows (REL-010, REL-013, REL-018).
- It is not a causal estimate, not a forecast, not a decision to keep or roll back, and not an anomaly detector over raw events. A release that did have a holdout is an experiment: `review-results` is the command for it, and REL-001's advice says so when the calendar row says `holdout: true`.
- `as_expected` means within the band and the registered tolerance over the readable days. It does not mean the release had no effect; the memo says what size of change the interval could not have seen.

## 4. Inputs

### 4.1 The export folder

Four files, read in full, in the manner of `data.py`:

| File | Columns | Contract |
| --- | --- | --- |
| `kpi_daily.csv` | `metric_date` (UTC date), the segment columns the catalogue names (the lab: `platform`, `country_code`, `acquisition_channel`), `kpi_id`, `numerator`, `denominator` | one row per date, segment combination and KPI; a rate KPI has a finite positive `denominator` on every row and a count KPI an empty one; values finite, and non-negative unless the catalogue marks the KPI `signed`; no date gaps inside a window (REL-002) |
| `release_calendar.csv` | `release_id`, `title`, `released_at_utc` (instant), `kind` (`feature`, `config`, `live_event`, `other`), `ends_at_utc` (empty unless the change ends), `holdout` (`true`/`false`), `scope` (text) | every release the product knows in the data's span; the reviewed release must be a row (REL-001); every other row inside a window is read by REL-010 |
| `kpi_catalogue.yaml` | `segments: [...]`; `kpis:` list of `{id, title, kind: count|rate, direction_of_good: increase|decrease|none, maturity_days, signed, default, governed_reference}` | ids unique and matching `^[a-z0-9_]+$`; every `kpi_id` of the data is in it and every catalogue KPI has data (REL-003); `governed_reference` is a path or URL to the metric's contract and is not read |
| `manifest.json` | `exported_at_utc`, per file `rows` and `sha256` | as today; `--as-of` replaces `exported_at_utc`; without either, maturity cannot be judged and every cohort KPI is `not_readable` with a reason |

The long format is chosen over one column per KPI because the catalogue, not the reader, then decides what a KPI is, and because a product adds a KPI by adding rows. Aggregation across segments is sum of numerators over sum of denominators, the lab's own rule ((read) `docs/metrics/live_strategy.md`: "rates are calculated from summed numerators and denominators"). Non-additive KPIs (a median session duration) are not in v1 (section 14).

### 4.2 The spec

```yaml
referee_release_spec_version: 1
id: season_11_update_2026_04
title: Season 11 update (upgrade costs +28%, event rewards -20%)
owner: live_ops_analytics
release:
  release_id: config_002           # a row of release_calendar.csv
pre_period_days: 56                # whole weeks, at least 28
post_period_days: 28               # the horizon of this review
kpis:
  defaults: true                   # every catalogue KPI with default: true
  include: [event_participation_rate]
  exclude: []
guardrails:                        # a tolerance is registered here or the KPI has none
  - {kpi: arpdau, tolerance_relative: 0.05}
  - {kpi: d7_retention, tolerance_relative: 0.03}
  - {kpi: dau, tolerance_relative: 0.05}
expectation:                       # optional: what the release was meant to do
  kpi: progression_velocity
  direction: decrease
  size_relative: 0.10
segments: [platform, acquisition_channel]   # read by the mix check; a subset of the catalogue's
```

Validation, in `release_spec.py` with the pattern of `spec.py` (every violation listed, unknown keys refused, `SpecError`): `pre_period_days` a multiple of 7 and at least 28; `post_period_days` at least 7; `tolerance_relative` in (0, 1); a guardrail's or the expectation's KPI among the selected KPIs; `direction` `increase` or `decrease`; `size_relative` in (0, 1); `segments` non-empty if given. No threshold is defaulted: a KPI without a line under `guardrails` is monitored (band, persistence, mix, trend) but can never be a breach, and the report says which KPIs have no registered tolerance. The judgement constants of the method (coverage, block length, draws, seed, `m` of `n`) are not spec fields (section 5.8). The spec's fingerprint is computed as today (18.1).

The `_Node` helper of `spec.py` is private. R1 moves it and `SpecError` to `referee/schema.py` under public names and makes `spec.py` import them, with no change to behaviour, tests or goldens; it is the one edit to an existing module before R6.

## 5. Method

Everything is deterministic, NumPy and SciPy only, and every constant below is quoted in the report.

### 5.1 Windows and readability

- Day 0 is the release instant's UTC date and is in neither window, because it is a partial day; the report states the instant and day 0. Pre window: the `pre_period_days` dates before day 0. Post window: the `post_period_days` dates after it, cut at the last readable date of each KPI (date + `maturity_days` not after the as-of date) and at the data's last date. A KPI with no readable post day is `too_early`, with the date its first post day becomes readable.
- The review runs at the product level: segments are summed before anything is computed, and are read again only by the mix check (5.5). A per-segment state is not in v1 (section 16).

### 5.2 The baseline and the daily band

- For each weekday, the baseline is the mean of the pre window's values of that weekday (`k = pre_period_days / 7` values each). A relative residual is a pre-window day's value divided by the mean of the other weeks' same weekday, minus one (leave-one-week-out, so a day does not predict itself). The band is the baseline times one plus or minus `z · s`, with `s` the pooled standard deviation of the relative residuals and `z` the normal quantile for the coverage (1.96 at 0.95).
- The band is a weekday profile with constant relative noise. It is wrong when the pre window trends (REL-018 says so and shows a trend-adjusted level beside the flat one) or when the noise is heavy-tailed (the studies of section 11 measure how wrong). The report prints the band's nominal coverage and, beside it, the coverage the studies measured for the nearest cell of their grid, as RES-008 prints measured rates from `pooled_rates_table.py` ((read) design 21.11).

### 5.3 The level change and its interval

- The level change `L` is the mean over the readable post days of value over baseline, minus one. Its 95% interval is a seeded moving-block bootstrap of the pre window's relative residuals (block of 7 days, 2,000 draws, seed 42): each draw builds a pseudo post window of the same length from resampled blocks and computes its `L`, and the interval is the 2.5% and 97.5% points of `L` minus that null distribution. For a guardrail, the harm is `L` signed so that positive is worse in the direction the catalogue calls bad.
- Shown and possible, as in RES-004: a breach is shown when the whole interval is beyond the tolerance, possible when only the point estimate is; a point estimate within the tolerance is not a finding even where the interval reaches beyond it, and the evidence marks the comparison as one the data cannot rule out.
- The interval is for one KPI and one look. It is not adjusted for the number of KPIs (the memo says how many were read and that some intervals will miss) nor for repeated daily runs (section 9).

### 5.4 Persistence

- REL-012 fires when, among the last `n` readable post days, at least `m` lie outside the daily band on the harmful side (or on either side for a KPI with `direction_of_good: none`). `m` and `n` are judgement constants fixed from study S1 so that the rule's false-alarm rate over a 28-day horizon is at most 5% in the null cell closest to the lab's data; the first candidate is 5 of 7. It is a warning that never escalates: it is the early signal while the interval of 5.3 is still wide, not the decision.

### 5.5 Mix

- For a rate KPI with segments declared, the post rate is standardised to the pre window's segment weights (direct standardisation, the computation of the live-strategy memo's acquisition-mix decomposition, re-implemented in Referee and checked against that memo's published numbers on the lab's data as a test). The mix component is the raw post rate minus the standardised one; the within component is the standardised post rate minus the pre rate. REL-013 fires when the mix component is at least as large in magnitude as the within component, or at least 2% of the pre rate (a constant, S3 decides it). The report always shows both components; the rule does not replace the raw change with the standardised one.

### 5.6 Maturity

- Cohort KPIs (D1, D7 retention) read a day only when the cohort has matured, by the catalogue's `maturity_days` against the as-of date, the discipline of the results review's outcome windows ((read) design 22.3). Immature days are left out of the post window and listed (REL-016). A KPI whose readable post window is shorter than the spec's horizon is interim (REL-017), and the memo says so in its first paragraph.

### 5.7 States and the verdict

| State of a KPI | When |
| --- | --- |
| `not_readable` | a data-fit blocker names it (REL-001 to REL-004) |
| `too_early` | no readable post day |
| `breach` | REL-011 shown |
| `watch` | REL-011 possible, REL-012, or REL-014 |
| `as_expected` | none of the above on its readable days |

The verdict is `invalid` when any data-fit blocker fired, else `breach` when any KPI is `breach`, else `watch`, else `too_early` when no KPI is readable, else `clear`. REL-011 shown is a blocker in severity and belongs to the harm group, as RES-004 does ((read) `report.py`, `_HARM_RULES`): it makes the verdict `breach`, not `invalid`. Exit status 1 for `invalid` and `breach`, 0 otherwise, 2 and 3 as today.

### 5.8 Judgement constants

Coverage 0.95; pre window at least 28 days; block length 7; 2,000 draws; seed 42; `m` of `n` from S1; the mix threshold from S3; the trend threshold of REL-018 (an extrapolated pre-window trend over the post window of at least half the smallest tolerance among the guardrails, or 2% without one) from S3. Each is a module constant, printed in the report and listed in the memo's Assumptions.

## 6. Rules

Seed list. The implementer prunes and renumbers with gaps, as the RES rules did; every rule is tested both ways and documented in `docs/rules.md` by the generator.

| ID | Severity | Fires when | Escalates |
| --- | --- | --- | --- |
| REL-001 | blocker | the release is not in the calendar, day 0 is outside the data, or no post day exists in the data; the advice names `review-results` when the calendar row has `holdout: true` | |
| REL-002 | blocker | the pre window has fewer than four whole weeks in the data, or a date or segment combination is missing inside a window | |
| REL-003 | blocker | a selected KPI is missing from the catalogue or the data, a rate KPI lacks a denominator, or a value is not finite or is negative where the catalogue does not allow it | |
| REL-004 | blocker | a segment the spec names is not a column of the data or of the catalogue | |
| REL-010 | warning | another calendar row's instant, or an interval it spans, falls inside the pre or the post window; the evidence lists them with their kind | |
| REL-011 | warning | a guardrail's level change is beyond its tolerance on the point estimate (possible) | blocker, in the harm group, when it is beyond on the whole interval (shown) |
| REL-012 | warning | `m` of the last `n` readable post days lie outside the band on the harmful side | |
| REL-013 | warning | the mix component of a rate KPI is at least as large as its within component, or at least the threshold | |
| REL-014 | warning | the expectation's KPI moved against the registered direction on the whole interval | |
| REL-015 | info | the expectation's interval includes zero, or its point estimate has not reached the registered size: no effect visible at this precision | |
| REL-016 | info | days of a KPI left out as immature, with the date each becomes readable | |
| REL-017 | info | the readable post window is shorter than the horizon: an interim review | |
| REL-018 | warning | the pre window's weekly means trend, and the trend extrapolated over the post window exceeds the threshold; the evidence shows the flat and the trend-adjusted level | |

What a finding says follows 21.7: the evidence holds the numbers, `why_it_matters` the reason in the catalogue's words, `remediation` what to do. The advice of REL-011 and REL-014 is in the same register as RES-004's: have the owner decide in writing, check what else changed (REL-010), do not move the tolerance now, and where a holdout is possible, run one.

## 7. Report, command, memo and page

- `python -m referee review-release SPEC EXPORT_DIR --release-id ID [--as-of TIME] [--format text|json|memo|html]`. Without `--release-id` the calendar's ids are listed, as `review-results` lists experiment ids ((read) README). `--as-of` as today.
- The report dict has `kind: release` and the `REPORT_VERSION` of `report.py`, the spec fingerprint, each file's SHA-256, the release row, day 0, both windows, the as-of time, the constants of 5.8, one entry per KPI (state, pre and post levels, baseline summary, `level` with estimate, interval and days, band exceedances, the mix components, the readable-through date), the findings, `rules_run`, the verdict and the blocking rule ids by group. `render_json` holds every row; the text and the memo cap lists at `DISPLAY_ROW_LIMIT` and say so.
- The memo keeps the lab template's five sections ((read) `MEMO_HEADINGS`): Decision (the verdict, what the firing rules advise, the fixed sentence that keeping or rolling back is not decided here), Observed facts (one table: KPI, pre, post, level change, interval, state), Assumptions and uncertainty (the weekday baseline and its measured coverage, the constants, the confounders REL-010, REL-013 and REL-018 found, the number of KPIs read), Data-quality qualification (REL-002, REL-003, REL-016, REL-017), Reproducibility (fingerprints, as-of, the command). Every value from a spec or an export is a code span and never starts a line; a table cell escapes pipe and backslash; the same inputs give the same bytes (23.1). The markdown helpers of `report.py` are private; R6 moves them to `referee/markdown.py` under public names with the results goldens unchanged, as R1 does for `_Node`.
- The page (R7, `--format html`) is one file with no script, no external resource and a `Content-Security-Policy` meta of `default-src 'none'; style-src 'unsafe-inline'`: a header with the release, day 0, the verdict and the fixed sentence of section 3; one inline SVG per KPI with the pre and post daily values, the baseline and its band, the release marker and the immature days greyed; the state beside each chart; the findings as the text report prints them. Every string from a spec or an export goes through `html.escape` with quotes, and a test renders hostile titles (`<script>`, an event-handler attribute, a closing tag) and asserts they appear only as text. The same inputs give the same bytes. One neutral palette, the state colours fixed and distinguishable without colour (a word beside each); the agent that builds it loads the dataviz guidance of its environment before writing chart code. It is a page, not a dashboard framework: no server, no state, no interaction beyond the browser's own.

## 8. The conclusion: the narration layer on a release report (R8)

- The user's "AI conclusion of the feature's current state" is the `summary` page of `narrate` on a release report, with the same guarantee as 24.1: every word is a REL catalogue sentence, a string written by code, a report value beside a label code wrote, or the memo's Decision section; a model, if the user names a command, selects identifiers and never writes.
- R8 extends the layer: the report check accepts `kind: release` with its own consistency rules (states, verdict, groups, the rule set); the fact allowlist adds the REL evidence paths, and decides whether the level estimates are facts (24.4 withholds effect sizes from the experiment page so that no number sits beside `invalid`; for a release the level change is the content, so the judgement is to offer it except when the verdict is `invalid`); the taxonomy adds `rollback_decision` (points to the breach and watch rules by id and title) and `causal` on releases (points to a fixed sentence: a before/after comparison cannot separate the release from time, and to REL-010's findings); `subgroup` points to REL-013. The questions, labels and freeze follow 24.10's procedure on their own evaluation set, with their own pre-registration; R8 states its counts.
- R8 depends on N10. If milestone 5 is not merged when R6 is, R8 waits and the README says the conclusion is the memo's Decision section.

## 9. Monitoring by default, and alerts

- A release is monitored by default when it is a row of the calendar and the spec says `defaults: true`; a spec for a routine release is the six lines of `id`, `title`, `owner`, `release`, `pre_period_days` and `post_period_days`, with the catalogue supplying the KPIs and the registered tolerances living in the spec of the guardrails the team registers once per KPI (a `guardrails` block can be copied from a team file; Referee does not read one).
- An alert is the exit status and the JSON verdict of a run that an operator schedules (cron, CI, a notebook): `breach` or `invalid` exits 1. Referee sends no message, writes nowhere but its standard output or `--output FILE`, and keeps no history; the lab's design excludes Slack, email and automatic publishing ((read) section 12). A daily run is a new look at the data; the interval of 5.3 does not cover repeated looks, which the memo says in one sentence, and REL-012 is the rule meant for daily reading.
- Not built: a trend of states across runs, a notification, a threshold that adapts. A team that wants history commits the reports; they are deterministic.

## 10. The lab side: exporter, release case and fixture (R2)

- The lab's live-strategy scenario is the release case, as generated today (read, `src/analytics_lab/generation/live_strategy.py` at `2466b19`): a `season_update` live event at day 90 of 180 (2026-04-01 for the fixture's start date), with `config_002` effective from that instant (upgrade cost multiplier 1.28, event reward multiplier 0.80), `config_003` at day 120.5 and `config_004` at day 150.75, a `winter_campaign` event over days 20 to 45, a paid-social share of installs of 25% before the update and 45% after (paid search 15% throughout), and a progression penalty for players installed after it. The daily KPI mart (`mart_live_strategy__daily_kpis`, grain date by platform, country and channel) already publishes `new_installs`, `dau`, `d1_retention` and `d7_retention` with their eligible and retained counts, `session_frequency`, `payers`, `payer_conversion`, `net_revenue_usd`, `arpdau`, `event_participation_rate`, `alliance_adoption_rate` and `progression_velocity`.
- The exporter is `python -m analytics_lab.export_release --db game_analytics/dev.duckdb --scenario live_strategy --segments platform,acquisition_channel --as-of TIME --out DIR`, a module beside `generate.py` and `evaluate.py`. It writes `kpi_daily.csv` from the mart (rates as numerator and denominator, `progression_velocity` left out as non-additive), `release_calendar.csv` from `dim_live_strategy__config_versions` and `stg_live_strategy__live_events`, `kpi_catalogue.yaml` from a table in the module (the live-strategy KPIs with `direction_of_good`, `maturity_days` 0 for daily KPIs, 1 for D1, 7 for D7, `default: true` for the eight of section 16, `governed_reference` pointing into `docs/metrics/live_strategy.md`), and `manifest.json`. A lab test asserts that every catalogue id has a heading in that metrics document, so the catalogue cannot drift from the governed contracts. DuckDB writes the CSV with the session time zone set to UTC, for the reason the experiment fixture's `PROVENANCE.md` records.
- The fixture is `referee/tests/data/live_strategy_release_1000/`, the export at scale 1000 and seed 42 with segments platform and channel (country left out to keep it small; target at most 1.5 MB, measured in R2), with a `PROVENANCE.md` and `manifest.json` in the experiment fixture's form, and a lab test that regenerates it byte for byte on Linux. (expected) The example spec of section 4.2 against it, with `pre_period_days: 56` and `post_period_days: 28`, should raise REL-010 (the winter campaign ends inside the pre window), REL-013 on the rate KPIs (the paid-social share of installs doubles at the update), REL-016 for the D7 cohorts of the last seven readable days, and REL-011 on `d7_retention` at a 3% tolerance; whether that breach is shown or possible is what the fixture will tell, and this handoff does not pre-commit to it. With `post_period_days: 56` REL-010 should also list `config_003`. The published memo's figures for the same update (D7 retention 22.00% before, 18.03% after, over install cohorts rather than days) are the reference the implementer reconciles against, in words, not as a golden.
- A second case is optional and not planned: the hybrid scenario's `experiment_mid_test_config_change` is an experiment's problem and belongs to `review-results`.

## 11. Studies, pre-registered

Synthetic daily series with known truth, in `tests/release_simulation.py`, outputs in `docs/simulations/release_null.json` and `release_power.json`, a handful of cells re-run under `-m study`, and `src/referee/release_rates_table.py` written from the outputs and compared with the committed copy by a test, as `pooled_rates_table.py` is.

| Study | Grid | Measures |
| --- | --- | --- |
| S1, null | weekly seasonality amplitude 0, 10%, 25% of the level; AR(1) residual correlation 0, 0.3, 0.6; daily noise 5%, 15% of the level; pre window 4, 8, 12 weeks; horizon 14, 28 days; 5,000 series per cell | the band's coverage; the rate at which REL-011 is possible and shown at tolerances 3%, 5%, 10% for a true change of zero; REL-012's rate for `m` of `n` in {4 of 7, 5 of 7, 6 of 7, 7 of 10}; REL-018's rate |
| S2, power | S1's cells with a step change of 5%, 10%, 20% at day 0, and a fading change (20% decaying to 0 over 14 days) | the rate at which REL-011 is shown and possible, and REL-012 fires, by day since release |
| S3, misfit | a linear trend of 0.5% and 1% per week in the pre window; a mix shift of one segment's weight from 25% to 45% with segment rates fixed; one heavy-tailed KPI (lognormal daily revenue) | REL-018's threshold; REL-013's threshold and its rate under no shift; the band's coverage under heavy tails |

Expectation, non-binding and the reason to measure: at 8 pre weeks and a 28-day horizon the band's coverage is within 3 points of 95% for AR(1) 0.3 or less, REL-011 shown is under 5% under the null at every tolerance, and REL-012 at 5 of 7 is under 5% in the same cells. Where a cell fails, the constant moves or the rule's note says in which cells it is unreliable, as RES-008's does. Runtime budget: the studies at most five minutes in `referee-studies`; the default suite grows by at most 30 s, measured in R4.

## 12. Tests and evidence

- Each rule both ways, with a mutant it kills, recorded in the pull request as 24.16 asks; the goldens of the fixture for JSON, text, memo and page, compared byte for byte; the same-bytes test on two renders; the text-safety tests of 23.1 and 7 on hostile titles, ids and segment values; the CLI's exit statuses and the listing without `--release-id`; the mix computation against the live-strategy memo's published decomposition on the lab's own frame; the studies' cells under `-m study`; a Linux byte-identity test of the fixture. The macOS gate runs the same suite; byte identity of floats between machines is not claimed, as for results.
- Per the repository's working rules, every test guards a boundary, a reference value, a security property or an output format, and one parametrised test replaces copies; the pull request body shows the evidence for anything cut.

## 13. Delivery

| Step | Branch | Depends on | Content |
| --- | --- | --- | --- |
| R0 | `docs/referee-release-handoff` | none | this file only; the README's status row waits for R9, so that it does not collide with N10's README edits |
| R1 | `feat/referee-release-spec` | R0 | `schema.py` (from `_Node`), `release_spec.py`, example spec, tests |
| R2 | `feat/lab-release-export` | R0 | the lab exporter, catalogue table, tests, the fixture and its provenance |
| R3 | `feat/referee-release-data` | R1, R2 | the export reader, manifest, hashes, every data problem listed |
| R4 | `feat/referee-release-methods` | R1 | baseline, band, level bootstrap, mix, studies S1 to S3, the rates table |
| R5 | `feat/referee-release-rules` | R3, R4 | the REL rules both ways, `docs/rules.md` regenerated |
| R6 | `feat/referee-release-report` | R5 | `markdown.py` (from `report.py`), report, text, JSON, memo, command, goldens |
| R7 | `feat/referee-release-page` | R6 | `--format html`, its safety tests and golden |
| R8 | `feat/referee-release-narration` | R6, N10 | the layer on release reports, taxonomy additions, evaluation extension |
| R9 | `docs/referee-release-readme` | R6, R7 | README section and status row; this file folded into the design document and deleted |

- Who merges: the user merges R0; the agent merges the rest under 24.2's conditions (all checks on the head green, a recorded fresh-context review with no open serious finding, no open thread), confirming CI on `main` after each; money, credentials and destructive git need the user. Merge commits, as the repository does.
- Existing files edited: `spec.py` (R1, imports only), `report.py` (R6, the moved helpers imported back), `cli.py` (R6 the subparser and handler; R7 one format), `docs/rules.md` (R5, regenerated), `README.md` (R9), the lab's `pyproject.toml` only if the exporter needs a console entry (it does not), and the design document at R9. The results engine, its rules, goldens and the narration modules are not edited before R8.

## 14. Not built, and out of scope

- Causal methods: synthetic control, Bayesian structural time series, difference in differences against a reference product. They add assumptions the memo cannot check and are not transparent in a rule's evidence; the reviewer says what moved and what else happened. A release with a holdout is an experiment.
- Change-point detection beyond REL-012; adaptive thresholds; anomaly detection on raw events; weekly or monthly KPI grains; non-additive KPIs; per-segment verdicts; an incidents file (the lab's incident registers are read by a person); notifications; history across runs; a server or an interactive dashboard; a model that writes any text.
- Unverified until built, and some after: the band's coverage on the lab's own series (the studies use synthetic series); how the page renders across browsers (no browser test; the golden is bytes); byte identity of floats between machines; whether the planted D7 drop is a shown or a possible breach at 3%.

## 15. What the README may and may not say

- May say: a before/after review of a release with named rules; the states and the verdict with their definitions; the band's coverage and the rules' false-alarm rates as the studies measured them on synthetic series, with the cell; that the page is a static file; that the conclusion is the narration layer's page and follows 24.14's wording.
- May not say: that the reviewer detects, measures or attributes the effect of a release; that `clear` or `as_expected` means no impact; that a breach was caused by the release; "safe", "validated" or "monitoring in real time"; that the page is a dashboard in the sense the lab's design excludes; anything 24.14 forbids about the narration layer.

## 16. Open judgements

The merge of R0 accepts these; each is the author's judgement.
- The command lives in Referee, named `review-release`, with rule prefix `REL` and a spec of its own kind rather than an extension of the experiment spec.
- The export is long-form daily KPIs with a catalogue and a calendar, four files, and the product level is what is reviewed; segments feed only the mix check.
- The method is a weekday-profile baseline with constant relative noise, a moving-block bootstrap for the level change, RES-004's shown-and-possible reading of a tolerance, and a persistence rule for early days; a trend is flagged and shown, not modelled away.
- Day 0 is in neither window; the pre window is whole weeks and at least four of them; the horizon is the spec's and cut at readability.
- The constants of 5.8, their values set by S1 and S3; the harm group makes the verdict `breach`, not `invalid`.
- The default KPI set of the lab's catalogue, eight: `dau`, `new_installs`, `d1_retention`, `d7_retention`, `session_frequency`, `payer_conversion`, `arpdau`, `net_revenue_usd`; the revenue guardrail follows the user's earlier decision that total net revenue is the primary value measure.
- The fixture at platform and channel grain, the page in v1 as R7, the narration as R8 after N10, and the two refactors (R1 `schema.py`, R6 `markdown.py`) done inside the steps that need them with goldens unchanged.

## 17. Kickoff prompt for the implementing session

```
Read referee/docs/design/2026-10-29-review-release-handoff.md in full, then CLAUDE.md at the
repository root and sections 3, 4, 14, 17.4, 18, 20 to 24 of
referee/docs/design/2026-09-28-referee-experiment-review-design.md. Check which pull requests of
Amendment 9 (N0 to N10) have merged before you plan R8.

1. R0 is merged. Start R1 on branch feat/referee-release-spec: move _Node and SpecError to
   referee/schema.py under public names with spec.py importing them and no golden changed, then
   write release_spec.py and its tests for section 4.2 only. No reader, methods or rules yet.
2. Work one pull request per step of section 13, in its order, each with the evidence 24.16
   asks for: ruff, the default tests, the mutants run and killed, a fresh-context review, and
   what remains unverified. Keep as little as possible; a test earns its place by guarding a
   boundary, a reference value, a security property or an output format.
3. Where the handoff says (expected), measure, record the figure in the pull request, and
   correct the handoff's text in the same pull request. Where a study of section 11 fails its
   expectation, move the constant or write the rule's note, and say which.
4. Never let a page say the release caused anything. The fixed sentence of section 3 is on every
   output.
```
