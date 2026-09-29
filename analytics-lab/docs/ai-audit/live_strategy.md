# AI audit: live-strategy D7 retention diagnostic

## Review scope

This record separates AI proposals from accepted repository evidence. The permitted analytical surface for the final diagnostic was the governed relation `main_live_strategy.mart_live_strategy__d7_diagnostic_inputs`, its metric contract, the incident register, tested analysis code, and the generated results artifact. The recorded review date is **2026-09-10** and the reviewed analysis version is `6add51353110b0a6de6d4aee7c619c7aed2f9e0c`.

“Human validation performed” below records only operator actions evidenced in the supervised workflow: applying artifacts, running the stated checks, and returning their outcomes. Analytical suggestions were Codex-supervised; no independent domain-expert approval is implied.

## Accepted model-review suggestion

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | rejection or correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | Build player-level D7 eligibility and retention flags before aggregating to cohort grain; sum retained and eligible players rather than averaging cohort rates. | Governed retention and diagnostic marts, dbt contracts, synthetic test fixtures. | Execution evidence was supplied by the repository owner: the Task 5 full `dbt build` and targeted reconciliation, maturity, and control-total tests passed. No separate semantic sign-off was recorded. | Accepted by Codex-supervised model review after automated reconciliation and maturity checks. | None; retained as the governed aggregation design. | [`mart_live_strategy__d7_diagnostic_inputs`](../../game_analytics/models/live_strategy/marts/mart_live_strategy__d7_diagnostic_inputs.sql) |

## Rejected `DISTINCT` suggestion

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | rejection or correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | AI candidate approach: add `DISTINCT` in the gameplay-event path to make duplicate Android rows disappear. | Staging contracts, event-dedup audit, canonical valid-event model, incident tests. | Execution evidence was supplied by the repository owner: the live-strategy dbt build and staged-arrival, canonical-event, and expected-incident tests passed. No separate semantic sign-off was recorded. | Rejected by Codex-supervised contract review because `DISTINCT` would conceal the defect, may collapse legitimate equal-valued events, and provides no deterministic survivor rule. | Replaced with explicit duplicate auditing and deterministic canonicalization keyed by the event identity; the incident remains visible. | [`int_live_strategy__event_dedup_audit`](../../game_analytics/models/live_strategy/intermediate/int_live_strategy__event_dedup_audit.sql) |

## Corrected configuration join

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | rejection or correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | AI candidate approach: attribute gameplay events to configuration versions with a date-level equality or date-range join. | Governed event timestamps, configuration effective timestamps, attribution model, ambiguity test. | Execution evidence was supplied by the repository owner: `dbt parse --no-partial-parse`, the full selector build, and `assert_event_configuration_is_unambiguous` passed. No separate semantic sign-off was recorded. | Corrected by Codex-supervised contract review before acceptance. | Replaced the date-level join with exact timestamp half-open intervals (`effective_from_utc <= event time < effective_to_utc`) so intraday changes cannot double-attribute an event. A left join preserves unmatched valid events for audit rather than dropping them. | [`int_live_strategy__event_config_attribution`](../../game_analytics/models/live_strategy/intermediate/int_live_strategy__event_config_attribution.sql) |

## Rejected causal statement

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | rejection or correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10T10:52:26.954957Z | AI candidate statement: the season update caused the D7 retention decline and higher upgrade costs explain it. | Governed diagnostic mart, Task 8 results JSON, metric catalogue, incident register. | Execution evidence was supplied by the repository owner: the tested notebook ran at commit `6add51353110b0a6de6d4aee7c619c7aed2f9e0c`, and its complete JSON output was returned. It shows a -3.97-point change, a 95% interval of [-9.10, +1.06] points, shifted acquisition mix, and a -0.050 ecological upgrade-attempt association. No separate semantic sign-off was recorded. | Rejected by Codex-supervised evidence review as unsupported by observational evidence. | Reframed as a monitored risk and unconfirmed hypothesis for a holdout-compatible randomized experiment. | [`d7_retention_diagnostic.md`](../../reports/live_strategy/d7_retention_diagnostic.md) |

## Refused raw or staging access

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | rejection or correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | AI candidate approach: query raw parquet files or staging relations directly from the decision notebook to investigate the decline. | Approved governed diagnostic mart only; documented contracts and incident metadata for context. | Execution evidence was supplied by the repository owner: the notebook ran and its returned metadata lists only `main_live_strategy.mart_live_strategy__d7_diagnostic_inputs` under `input_relations`; Task 8 analysis tests passed under the worktree interpreter. No separate semantic sign-off was recorded. | Refused by Codex-supervised access review to preserve the governed analytical boundary and avoid bypassing contained defects. | Incident details are referenced from governed documentation; no raw or staging relation is queried by the notebook. | [`01_d7_retention_diagnostic.py`](../../notebooks/live_strategy/01_d7_retention_diagnostic.py) |

## Final evidence boundary

The final memo uses the executed JSON values as observed facts. Acquisition-mix and within-channel quantities remain descriptive associations. Android completed-session sensitivity is labeled measurement risk. The recommendation is an experiment design, not a retrospective causal verdict.

No AI-generated statement is represented as independently human-verified beyond the concrete operator-run checks recorded above. The analysis remains reproducible from the committed notebook source and the exact SHA recorded in the generated result.
