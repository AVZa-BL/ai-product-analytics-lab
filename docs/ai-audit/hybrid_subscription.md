# AI audit: hybrid subscription engagement and cannibalization diagnostic

## Review scope

This record separates AI proposals from accepted repository evidence. The permitted analytical surface consists of governed hybrid-subscription facts and diagnostic marts, their metric contracts, the incident register, tested analysis code, and the operator-returned execution result. The review date is **2026-09-10** and the executed analysis version is `f5e3288a3c1a519c2d5716de0d61f091020a1320`.

“Human validation performed” records only evidenced operator actions: running the stated checks and returning their output. It does not imply independent domain-expert or semantic approval.

## Accepted governed calculation design

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | Pair mature player-level pre/post windows, reconcile them to published aggregate marts, and bootstrap at player grain. | Governed hybrid player-behavior fact, diagnostic marts, incident mart, metric catalogue. | The repository owner returned 5 passing analysis tests, clean Ruff output, a 176/176 dbt build, and complete notebook JSON. | Accepted after automated pairing, determinism, reconciliation, and dbt checks. | The bootstrap implementation was optimized before publication to resample player deltas rather than repeatedly filter the full frame. | [`hybrid_subscription_diagnostic.py`](../../src/analytics_lab/analysis/hybrid_subscription_diagnostic.py) |

## Rejected causal engagement statement

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10T15:47:28.570410Z | AI candidate statement: the subscription caused higher player engagement because subscribers gained 2.97 sessions. | Executed diagnostic JSON, governed metric catalogue, tested notebook. | The returned output shows subscriber and non-subscriber changes of +2.97 and +1.09 sessions, respectively. Subscriber status is self-selected and post-index. | Rejected as unsupported by the observational design. | Reframed as a favorable engagement association that justifies a randomized intent-to-treat test. | [`engagement_cannibalization_decision_memo.md`](../../reports/hybrid_subscription/engagement_cannibalization_decision_memo.md) |

## Corrected cannibalization interpretation

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10T15:47:28.570410Z | AI candidate statement: a $24.66 standalone-store decline proves the subscription destroys $24.66 of player value. | Executed diagnostic JSON and governed revenue contracts. | The returned output separately reports -$24.66 standalone-store, +$9.99 subscription, and -$14.67 total-net-revenue difference-in-differences estimates. | Corrected because store displacement and total value are different quantities, and neither observational estimate proves causality. | The decision uses total net revenue as the primary value guardrail and keeps standalone-store revenue as a substitution diagnostic. | [`hybrid_subscription.md`](../metrics/hybrid_subscription.md) |

## Rejected post-treatment primary analysis

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | AI candidate experiment design: estimate incrementality by comparing eventual subscribers with non-subscribers. | Governed exposure fact, player behavior fact, metric catalogue. | The dbt contracts confirm an incrementality-eligibility flag, while the executed notebook identifies eventual subscriber status as observational. | Rejected because eventual conversion is a post-treatment outcome and introduces selection bias. | The proposed experiment uses randomized pre-exposure assignment and player-level intent-to-treat analysis. | [`fct_hybrid_subscription__marketing_exposures`](../../game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__marketing_exposures.sql) |

## Refused raw or staging access

| timestamp_utc | proposed work | allowed sources | human validation performed | outcome | correction | artifact link |
|---|---|---|---|---|---|---|
| 2026-09-10 | AI candidate approach: query raw transactions or staging exposures directly to improve the decision narrative. | Approved governed facts, diagnostic marts, metric catalogue, and incident metadata. | The returned JSON metadata lists only four `main_hybrid_subscription` governed relations. | Refused to prevent bypassing canonicalization, entitlement reconstruction, and incident containment. | Known defects are reported through the governed incident mart; the notebook does not query raw or staging relations. | [`01_engagement_cannibalization_diagnostic.py`](../../notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py) |

## Final evidence boundary

The final memo treats the engagement, store, subscription, and total-revenue quantities as observed associations. Bootstrap intervals describe player-level sampling variation only. The recommendation to withhold expansion is a risk-management decision under uncertainty, not a retrospective claim that the subscription caused the measured revenue difference.

No AI-generated conclusion is represented as independently human-verified beyond the concrete operator-run checks recorded above.
