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
