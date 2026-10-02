# Hybrid subscription raw-data contract

The generator creates deterministic synthetic evidence for a free-to-play game
with a monthly subscription, currency grants, subscriber discounts, and an
exclusive reward track. Every table includes a `scenario_run_id`; player IDs
are synthetic and contain no personal information.

All monetary values use USD. Version 1 performs no foreign-exchange conversion.

Event tables also carry `ingested_at_utc`. The matched diagnostic derives source-specific event bounds, maximum ingestion timestamps and empirical maximum observed nonnegative ingestion lag from session, canonical transaction and LiveOps staging rows. Every source must cover both UTC windows and advance ingestion through the post endpoint plus this allowance. Missing/invalid/stale sources exclude candidates. No external source-completeness telemetry or operational watermark SLA is available; this conservative snapshot proxy cannot rule out unseen delayed events or player-level gaps. Source evidence and excluded-candidate counts are published in `mart_hybrid_subscription__match_population_summary`.

| Table | Grain and key | Required relationships | Time evidence |
| --- | --- | --- | --- |
| `players` | One player; `player_id` | None | `acquired_at_utc` |
| `sessions` | One session; `session_id` | `player_id` | `started_at_{raw,local,timezone,utc}` |
| `subscription_events` | One lifecycle event; `subscription_event_id` | `player_id` | `occurred_at_{raw,local,timezone,utc}` |
| `store_transactions` | One webhook row; business key `transaction_id` | `player_id`, `sku` | `transaction_at_{raw,local,timezone,utc}` |
| `currency_ledger` | One ledger entry; `ledger_entry_id` | `player_id`, optional subscription transaction | `occurred_at_{raw,local,timezone,utc}` |
| `live_event_participation` | One participation; `participation_id` | `player_id` | `participated_at_{raw,local,timezone,utc}` |
| `marketing_exposures` | One campaign exposure; `exposure_id` | `player_id` | `exposed_at_{raw,local,timezone,utc}` |
| `product_catalogue` | One product; `sku` | None | Not applicable |
| `experiment_assignments` | One logged player; `assignment_id`, one per `player_id` | `player_id` | `assigned_at_utc` only |
| `experiment_exposures` | One offer-page exposure, possibly several per player; `exposure_id` | `player_id` (an assigned player) | `exposed_at_utc` only |
| `experiment_outcomes` | One logged player; `player_id` | `player_id` (an assigned player) | `window_{start,end}_utc`, `first_purchase_at_utc` |

## Analytical signal

Subscriber selection is stratified by `prior_payer_status`. The data preserves
28-day pre/post behavior around each subscription start. Subscribers receive a
clear post-start session and LiveOps participation lift. Prior payers who
subscribe show lower post-start standalone store revenue. These are synthetic
diagnostic signals, not causal estimates; downstream analysis must compare
subscribers with matched non-subscriber controls and judge total net revenue.

## Deliberately injected defects

| Defect | Injection | Required downstream treatment |
| --- | --- | --- |
| Duplicate store webhook | Repeat 1.5% of transaction IDs with later ingestion | Deduplicate on business key, retaining the latest valid record |
| Cancellation semantics | Disable auto-renew before a future period end | Preserve entitlement until expiry or revocation |
| Mixed time zones | Sessions use `America/Los_Angeles`; transactions use `Europe/Berlin` | Preserve raw/local/zone fields and canonicalize to UTC |
| Missing grant link | Remove the subscription transaction link from 8% of grants | Flag and exclude from direct grant reconciliation |
| Late experiment exposure | Place 5% of subscriber exposures after subscription start | Exclude from acquisition and incrementality attribution |

Raw defects are immutable evidence. Staging and intermediate models must detect,
label, and contain them rather than rewriting the generated files.

## Synthetic offer-page experiment

The three `experiment_*` tables hold a three-arm offer-page test (`control`, `variant_b`,
`variant_c`) for the milestone 3 results reviewer. They are generated from their own random
stream, so adding them did not change any other table: the eight tables above have the same
content as before, and a test pins their fingerprints.

Players who never subscribe are assigned by hashing the player ID with a salt, over a 21-day
window that opens ten days after the subscription launch. Outcomes cover the seven days after
assignment. These tables carry UTC timestamps only, with no raw, local or time-zone evidence and
no `ingested_at_utc`, because no timestamp-normalisation defect is planted in them. A scenario
shorter than 90 days cannot hold the experiment and is refused.

`experiment_outcomes` is an addition to the two tables the design document names. The planted
effects need arm-dependent outcomes, and the scenario's existing tables must not change.

### Planted problems

The sizes are in `PlantedParameters`, and `ground_truth()` returns the plan as data. At the CI
scale of 1,000 players each problem is present but too small to test statistically. Statistical
claims are tested at a reference scale of 5,000 players.

| Problem | Injection | Required downstream treatment |
| --- | --- | --- |
| Sample-ratio mismatch in `variant_c` | From day 8 of the window a bucketing bug on android loses about 65% of arm C's assignments, mostly players with few sessions | Test the arm split against the registered allocation before reading any effect; the mismatch invalidates the arm even though the bias it causes is small |
| Exposure after purchase | 35% of players who purchase are first exposed after their first purchase | Detect and exclude from exposure-based comparisons, as for the late subscriber exposures above |
| Heavy-tailed revenue | Purchase amounts are lognormal with sigma 1.7 | Do not rely on a normal approximation of mean revenue per player |
| Novelty in `variant_b` | Purchase and session lifts in the first week fall and reverse by the third | Examine the effect by exposure week before calling a result stable |
| Configuration change in `variant_b` | `arm_config_version` moves from 1 to 2 on day 12 of the window | Treat the two versions as different treatments, and record the change in the incident register |

A player lost to the bucketing bug has no row in any experiment table; absence is the evidence.
