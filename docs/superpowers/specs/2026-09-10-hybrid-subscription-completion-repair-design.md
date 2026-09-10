# Hybrid Subscription completion repair design

**Date:** 2026-09-10  
**Branch:** `scenario/hybrid-subscription`  
**Status:** Approved design, pending implementation plan

## Purpose

Complete the Hybrid Subscription scenario against the approved repository specification before opening a pull request. The repair closes four review findings: the diagnostic uses the wrong index and an unmatched comparison, reward-track revenue leaks into standalone-store measures, required governed KPIs are missing, and the decision memo cites diagnostic outputs that are not published.

The result must remain deterministic, synthetic, reproducible, and explicit about observational limits. Passing tests must demonstrate the intended business contracts rather than merely preserve the current reduced implementation.

## Scope

The repair will:

1. Index diagnostic populations at the first incrementality-eligible marketing exposure.
2. Build deterministic one-to-one matched subscriber and non-subscriber pairs.
3. Publish the full KPI surface required by the original design.
4. Exclude subscription and reward-track products from standalone-store revenue.
5. Update the Python diagnostic, metric catalogue, memo, AI audit, and agent evaluation.
6. Commit the deterministic diagnostic results JSON while keeping generated notebook and figure outputs untracked.

The repair will not claim causal effects, build a production experimentation platform, estimate lifetime value, or introduce propensity-score or machine-learning matching.

## Population and index contract

`int_hybrid_subscription__analysis_population` will use the first exposure for which `is_incrementality_eligible` is true as `index_at_utc`. A player can enter the matched diagnostic only when:

- player identity and required matching covariates are valid;
- a first incrementality-eligible exposure exists;
- the exposure precedes subscription start for eventual subscribers;
- complete half-open pre and post windows exist: `[index - 28 days, index)` and `[index, index + 28 days)`;
- relevant session and transaction ingestion watermarks have passed the post-window maturity allowance.

Players without an eligible exposure or complete observation windows remain visible in population reconciliation counts and incident reporting but are excluded from matched outcome estimates. Eventual subscriber status remains a post-index classification and therefore cannot be treated as randomized assignment.

## Deterministic matching

Matching will be one-to-one without replacement.

1. Split eligible players into eventual subscribers and non-subscribers.
2. Require exact agreement on `prior_payer_status`, `platform`, and `acquisition_channel`.
3. Within each exact-match stratum, process subscribers in ascending order of pre-index session count and then stable `player_id`.
4. For each subscriber, select the still-unmatched control that minimizes absolute pre-index session-count distance; break ties by control pre-index session count and then stable control `player_id`.
5. Exclude subscribers for which no unmatched control remains, exclude all unused controls, and publish subscriber, control, matched, and unmatched counts.

The stable greedy nearest-control design is transparent, reproducible across runs, and fully specified by its ordering and tie-break rules. Pre-index session count is a baseline behavior covariate, not an outcome observed after exposure. Tests will assert that every pair has exactly one subscriber and one control, that no player appears in multiple pairs, that matched covariates agree, and that each selected control satisfies the specified nearest-control rule at its matching step.

## Revenue classification

Standalone-store revenue includes only governed store transactions whose product type is neither `subscription` nor `reward_track`. Total net revenue equals eligible standalone-store net revenue plus subscription net revenue. Currency grants are non-cash and excluded.

The exclusion must be implemented consistently in:

- player-period behavior;
- daily and monthly KPI aggregation;
- matched incrementality inputs;
- reconciliation tests and metric documentation.

A fixture-backed dbt test will fail if reward-track revenue contributes to standalone-store or total net revenue.

## Governed models

### Facts and intermediate models

- `fct_hybrid_subscription__sessions`: one canonical session per `session_id`, with player, UTC start, duration, and scenario run identity.
- `fct_hybrid_subscription__subscriber_daily`: one row per player and UTC date in which an entitlement is active at end of day.
- revised `int_hybrid_subscription__analysis_population`: eligible-exposure index and explicit eligibility/exclusion reasons.
- revised `int_hybrid_subscription__player_28d_behavior`: mature pre/post metrics around the exposure index with corrected product classification.
- `int_hybrid_subscription__matched_pairs`: one row per deterministic matched pair.

### Published marts

- `mart_hybrid_subscription__matched_incrementality`: pair-level and aggregate pre/post changes for sessions, LiveOps participation, standalone-store revenue, subscription revenue, and total net revenue.
- `mart_hybrid_subscription__subscription_cohorts`: eligible-exposure conversion and mature D30 subscriber retention inputs.
- `mart_hybrid_subscription__monthly_kpis`: calendar-month MAU, end-of-month active subscribers, churn inputs, ARPMAU inputs, discount-utilization inputs, and LiveOps participation inputs.
- revised `mart_hybrid_subscription__daily_kpis`: existing governed counts plus daily active subscribers and corrected standalone-store classification.
- revised engagement and cannibalization diagnostic marts: derived from the matched population and reconciled to pair-level controls.

Every published mart will expose component numerators and denominators so rates can be recomputed after aggregation. A zero denominator produces `null`, never zero.

## KPI contracts

| KPI | Grain | Definition | Maturity and interpretation |
| --- | --- | --- | --- |
| MAU | Calendar month | Distinct players with at least one canonical session | Descriptive activity measure |
| Active subscribers | UTC date | Distinct players with an entitlement active at end of day | Cancellation does not end access before expiry |
| Subscription conversion | Eligible-exposure cohort | Players starting a subscription within 28 days divided by eligible exposed players | Only mature 28-day cohorts publish a rate |
| Subscriber churn | Calendar month | Entitlements ending by expiry or revocation divided by subscribers active at month start | Cancellation alone is not churn |
| D30 subscriber retention | Subscription-start cohort | Mature starters entitled at day 30 divided by mature starters | Requires a complete 30-day observation window |
| ARPMAU | Calendar month | Recognized standalone-store plus subscription net revenue divided by MAU | Reward-track revenue and currency grants excluded |
| Incremental net revenue | Matched pair, pre/post | Subscriber total-revenue change minus matched-control change | Observational association, not a causal effect |
| Discount utilization | Calendar month | Discounted eligible standalone-store transactions divided by eligible standalone-store transactions | Count-based utilization; publish transaction counts |
| Engagement lift | Matched pair, pre/post | Subscriber session change minus matched-control session change | Observational association; bootstrap at pair grain |
| LiveOps participation | Calendar month | Active players with at least one governed participation divided by MAU | Descriptive participation rate |

## Diagnostic and statistical treatment

The Python diagnostic will read only governed hybrid facts and marts. It will validate pair uniqueness, complete periods, exact-match covariates, population control totals, and aggregate reconciliation before estimating outcomes.

Primary diagnostic quantities are:

- matched-pair engagement difference-in-differences;
- matched-pair standalone-store difference-in-differences;
- matched-pair subscription-revenue contribution;
- matched-pair total-net-revenue difference-in-differences;
- matched-pair LiveOps participation difference-in-differences.

Bootstrap intervals will resample matched pairs with a fixed seed. They quantify sampling variation in the synthetic matched population but do not remove selection bias, validate parallel trends, or establish causality.

The current executed values are invalidated by the population repair and must be regenerated. Documentation and evaluation fixtures will not retain old values unless they reconcile exactly after re-execution.

## Tests and reconciliation

Implementation follows test-driven development. New or revised tests will first fail against the current branch, then pass after each focused repair.

Required dbt tests:

- eligible exposure is present and precedes subscription for every included subscriber;
- diagnostic pre/post windows are complete and unique;
- each matched pair contains one subscriber and one non-subscriber;
- players and pair IDs are unique in the matched panel;
- exact-match covariates agree within each pair;
- matched and unmatched population counts reconcile;
- reward-track products contribute zero standalone-store and total net revenue;
- MAU, active-subscriber, conversion, churn, D30-retention, ARPMAU, discount-utilization, engagement, and LiveOps numerators and denominators reconcile to governed facts;
- zero denominators produce null rates;
- incident detection and containment continue to pass.

Required Python tests:

- deterministic matching and pair-grain bootstrap behavior;
- rejection of duplicate, incomplete, or covariate-mismatched pairs;
- reconciliation failure on mismatched published controls;
- correct separation of standalone, subscription, reward-track, and total value;
- deterministic regenerated JSON and complete provenance metadata.

The final gate is the full Python suite with warnings treated as errors, Ruff, dbt parse without partial parsing, the complete Hybrid Subscription selector build, evaluator execution, JSON validation, whitespace checks, and clean tracked status.

## Documentation and artifacts

Update the metric catalogue with all ten KPI contracts and the matched-population rules. Update the decision memo and AI audit to report only regenerated matched results and to preserve causal boundaries. Extend the trusted-agent questions to cover matched-population provenance, the full KPI surface, reward-track exclusion, maturity rules, and refusal of unsupported causal or lifetime-value claims.

Commit:

- the executable `.py` notebook source;
- the deterministic diagnostic results JSON;
- the decision memo, metric catalogue, AI audit, question catalogue, canonical answers, and evaluation report.

Do not commit generated `.ipynb` or figure outputs. Remove documentation links that imply those untracked files are published. The JSON will contain code version, execution timestamp, package versions, input relations, filters, matching rules, bootstrap seed, and bootstrap draws.

## Pull-request readiness

The pull request can be opened only when:

1. all Critical and Important review findings are resolved;
2. the full original KPI list is implemented and documented;
3. matched results replace the prior unmatched diagnostic;
4. deterministic result artifacts are committed and internally consistent;
5. the complete validation gate passes on the final branch head.
