# Subscription Data-Quality Incident — 2026-08-27

Raw subscription evidence is deliberately immutable. The modeled layer detects and contains each designed failure while preserving the source rows for audit.

## Duplicate lifecycle webhooks

### Detection
`int_subscription__quality_audit.duplicate_webhook_rows`, derived from repeated `webhook_id` values in `subscription_lifecycle_events`.

### Impact
Uncontained duplicates would multiply lifecycle transitions, conversions, and entitlement periods.

### Containment
`stg_subscription__subscription_events` retains the latest `ingested_at` record per `webhook_id` and exposes `source_webhook_duplicate_count`.

### Raw evidence retained
All duplicate rows remain unchanged in the raw Parquet table.

```sql
select webhook_id, count(*) from stg_subscription__subscription_events group by 1 having max(source_webhook_duplicate_count) > 1;
```

## Late cancellation delivery

### Detection
`int_subscription__quality_audit.late_cancellation_rows` compares cancellation `ingested_at` with `effective_at`.

### Impact
Using ingestion time would overstate paid activity, MRR, and retention before the webhook arrived.

### Containment
Lifecycle reconstruction uses `effective_at` for entitlement state while preserving occurrence and ingestion timestamps.

### Raw evidence retained
Late-arriving cancellation webhooks remain unchanged in raw evidence.

```sql
select * from stg_subscription__subscription_events where event_type = 'cancelled' and ingested_at > effective_at;
```

## Missing campaign identifiers

### Detection
`int_subscription__quality_audit.missing_campaign_users` counts users whose raw `campaign_id` is null.

### Impact
Ignoring missing attribution would bias channel conversion and CAC comparisons.

### Containment
`int_subscription__campaign_attribution` assigns the explicit `unknown` bucket and marks `attribution_status = 'missing_campaign'`.

### Raw evidence retained
The raw user record keeps its null campaign identifier.

```sql
select attribution_status, count(*) from int_subscription__campaign_attribution group by 1;
```

## Inconsistent activation event names

### Detection
The quality audit and staging checks compare raw product event names with `subscription_event_name_map`.

### Impact
Counting only one alias would understate activation and distort activation-segment conversion.

### Containment
The mapping seed converts supported aliases to `activation_completed` and exposes `is_activation_event`.

### Raw evidence retained
Original event names remain available beside the canonical name in staging.

```sql
select event_name, canonical_event_name, count(*) from stg_subscription__product_events group by 1, 2;
```

## Local-time trial ends labelled as UTC

### Detection
`int_subscription__quality_audit.local_time_trial_end_rows` counts non-UTC source timezones requiring reconstruction.

### Impact
Using the raw wall-clock value as UTC would shift trial maturity and conversion windows.

### Containment
Staging retains `raw_trial_end_at_reported_utc` and `trial_timezone` and publishes reconstructed `trial_end_at_utc`.

### Raw evidence retained
The original reported value and timezone remain available for audit.

```sql
select raw_trial_end_at_reported_utc, trial_timezone, trial_end_at_utc from stg_subscription__subscription_events where trial_timezone <> 'UTC';
```
