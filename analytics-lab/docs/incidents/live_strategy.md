# Live Strategy data-quality incidents

This register records the six intentional defects in the deterministic Live Strategy fixture.
Raw and staging evidence remains unchanged. Each downstream rule is explicit so a metric consumer
can distinguish excluded evidence from repaired or qualified evidence.

## `duplicate_android_client_events`

- **symptom:** Android produces repeated arrivals with the same `client_event_id` but different ingestion IDs.
- **detector:** `duplicate_client_event_id` flags rows where the arrival rank within a client event exceeds one.
- **affected raw evidence:** Duplicate rows remain in `gameplay_events.parquet` and the typed staging relation.
- **metric impact:** Counting arrivals would overstate activity and any event-based conversion or participation measure.
- **downstream containment:** `int_live_strategy__valid_gameplay_events` retains one canonical arrival per client event using a deterministic window rank.
- **what remains uncertain:** A duplicate detector cannot prove whether two semantically distinct actions reused a client ID.
- **raw preservation:** No raw arrival is deleted or rewritten; rejected arrivals remain queryable in `int_live_strategy__event_dedup_audit`.

## `missing_android_session_ends`

- **symptom:** Some Android `4.12.0` sessions have a start timestamp but no end timestamp.
- **detector:** `missing_android_session_end` counts Android rows where `has_missing_end` is true.
- **affected raw evidence:** The null end timestamps remain in `sessions.parquet`, staging, and the governed session fact.
- **metric impact:** Session-duration distributions and completed-session retention are understated if the affected sessions are treated as completed observations.
- **downstream containment:** Sessions remain valid start/activity evidence but are excluded from duration statistics and from the completed-session D7 sensitivity signal. Robust activity D7 remains the governed retention measure.
- **what remains uncertain:** The true duration and completion state of a session without an end event cannot be recovered from this fixture.
- **raw preservation:** Missing ends are never imputed or removed.

## `purchase_refund_status_lag`

- **symptom:** A store purchase report remains completed after later ledger evidence records a full refund.
- **detector:** `refund_supersedes_store_status` compares the initial store status with the reconciled final status.
- **affected raw evidence:** The completed purchase report and its later refund ledger entry are both retained.
- **metric impact:** Unreconciled reporting overstates net revenue and can overstate payer conversion if fully refunded players are counted as payers.
- **downstream containment:** Refund ledger evidence supersedes the initial status in `int_live_strategy__purchase_reconciliation` and `fct_live_strategy__purchases`; net revenue is gross less reconciled refunds, and payers require positive daily net revenue.
- **what remains uncertain:** Refunds arriving after the observation window would not yet be visible and can still revise recent revenue.
- **raw preservation:** Neither the original purchase status nor the refund transaction is overwritten.

## `events_before_install`

- **symptom:** Some event timestamps precede the recorded installation timestamp for the same player.
- **detector:** `event_timestamp_before_install` compares each event timestamp with its player's install timestamp.
- **affected raw evidence:** Time-invalid events remain in the raw arrival table, staging, and the event-deduplication audit.
- **metric impact:** Including them would create impossible pre-install activity and contaminate retention or acquisition-cohort metrics.
- **downstream containment:** Pre-install events are excluded from `int_live_strategy__valid_gameplay_events` and therefore omitted from governed activity.
- **what remains uncertain:** The fixture cannot determine whether the event clock or install clock is the incorrect source.
- **raw preservation:** The rejected rows remain available in `int_live_strategy__event_dedup_audit` with `is_before_install = true`.

## `invalid_membership_interval`

- **symptom:** Some alliance memberships have `valid_to_utc` earlier than `valid_from_utc`.
- **detector:** `membership_valid_to_before_valid_from` directly compares the two raw validity bounds.
- **affected raw evidence:** Invalid intervals remain in `alliance_memberships.parquet` and staging.
- **metric impact:** Expanding invalid intervals can produce impossible membership dates or distort alliance adoption.
- **downstream containment:** Invalid intervals are excluded by `int_live_strategy__valid_alliance_memberships` before daily membership expansion.
- **what remains uncertain:** The correct start, end, or membership status cannot be inferred safely.
- **raw preservation:** No interval boundary is corrected in place; the rejected count is retained in the governed intermediate layer.

## `ambiguous_intraday_configuration_join`

- **symptom:** Collapsing configuration boundaries to UTC dates makes events on an intraday change date match more than one configuration row.
- **detector:** `date_level_config_join_fanout` deliberately performs the unsafe inclusive date-level join and counts events with multiple matches.
- **affected raw evidence:** Valid events and all intraday configuration versions remain unchanged.
- **metric impact:** A date-level join can duplicate events or attach the wrong cost and reward configuration, corrupting KPI and progression comparisons.
- **downstream containment:** `int_live_strategy__event_config_attribution` uses the exact UTC timestamp with half-open intervals: `occurred_at_utc >= effective_from_utc` and `occurred_at_utc < effective_to_utc`.
- **what remains uncertain:** Configuration changes outside the recorded version history cannot be attributed.
- **raw preservation:** Configuration timestamps retain their full intraday precision; no boundary is rounded to a calendar date.
