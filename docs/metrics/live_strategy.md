# Live Strategy governed metric catalogue

All reporting dates and cohort offsets use UTC calendar dates. Rates are calculated from summed
numerators and denominators at the requested reporting grain; downstream consumers must not average
pre-aggregated rates. A zero denominator produces `NULL`, not zero.

## New installs

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Install UTC date, platform, country, and acquisition channel.

**Eligibility:** Governed players whose recorded installation falls on the reporting UTC date.

**Formula:** Count of rows in `dim_live_strategy__players` assigned to the reporting dimensions.

**Exclusions:** None after the player source passes its primary-key and required-field contracts.

**Time rule:** `installed_at_utc` is converted to a UTC calendar date; configuration boundaries do not alter the install date.

**Known limitations:** Reinstalls are not represented separately, and the metric inherits the source system's install timestamp and acquisition attribution.

## DAU

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Activity UTC date, platform, country, and acquisition channel.

**Eligibility:** A governed player with at least one valid canonical gameplay event or any session start on the UTC date.

**Formula:** Count of unique player-date rows in `fct_live_strategy__player_activity_daily`.

**Exclusions:** Duplicate client-event arrivals, pre-install events, and orphaned player evidence; missing session ends do not remove session-start activity.

**Time rule:** Event occurrence and session-start timestamps are assigned to UTC calendar dates.

**Known limitations:** Session starts and gameplay events are evidence of activity, not proof of a completed session or a minimum engagement duration.

## D1 retention

**Source relation:** `mart_live_strategy__retention_cohorts`

**Grain:** Install-date, platform, country, acquisition-channel, and configuration-version cohort.

**Eligibility:** Players installed on the cohort date when install date + 1 is no later than the maximum observed activity date.

**Formula:** Eligible players with robust activity on install UTC date + 1 divided by eligible players; aggregate by summing retained and eligible players before dividing.

**Exclusions:** Duplicate arrivals, pre-install events, and immature D1 cohorts. Missing session ends do not exclude session-start activity.

**Time rule:** Installation and activity use UTC calendar dates; install configuration uses an exact half-open UTC timestamp interval.

**Known limitations:** The maximum observed activity date is only a proxy watermark and does not prove every earlier event arrived. The fixture has no deliberately generated D1 return sessions, so its mature D1 rate is structurally zero; production interpretation requires verified D1 instrumentation.

## D7 retention

**Source relation:** `mart_live_strategy__retention_cohorts`

**Grain:** Install-date, platform, country, acquisition-channel, and configuration-version cohort.

**Eligibility:** Players installed on the cohort date with install date + 7 no later than the maximum observed activity date.

**Formula:** Eligible players with at least one row in `fct_live_strategy__player_activity_daily` on install UTC date + 7 divided by eligible players; aggregate from counts, never averaged cohort rates.

**Exclusions:** Pre-install events, duplicate client-event arrivals, and immature cohorts. Missing session ends do not exclude robust-activity retention.

**Time rule:** Installation and activity are assigned in UTC; configuration is assigned by a half-open UTC timestamp interval.

**Known limitations:** The maximum observed activity date is a proxy watermark, not proof of source completeness. This descriptive metric is sensitive to acquisition mix; sessions crossing into UTC day 8 do not count as D7, and the metric cannot establish that a season update caused a behavior change.

## Session frequency

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Activity UTC date, platform, country, and acquisition channel.

**Eligibility:** All governed session starts in a segment with at least one DAU.

**Formula:** Session count divided by DAU.

**Exclusions:** No session is excluded solely for a missing or invalid end timestamp; segments with DAU equal to zero return `NULL`.

**Time rule:** Sessions are assigned to the UTC date of `started_at_utc`.

**Known limitations:** Frequency can exceed one and is sensitive to sessionization rules; missing ends affect completion and duration measures but not session-start counts.

## Median session duration

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Session-start UTC date, platform, country, and acquisition channel.

**Eligibility:** Sessions with a non-null end timestamp at or after the start timestamp.

**Formula:** Median elapsed seconds from start to end among valid completed sessions; `qualifying_session_count` publishes the denominator.

**Exclusions:** Sessions with missing ends or negative durations.

**Time rule:** Segment date is the UTC session-start date, even if a valid session ends on a later date.

**Known limitations:** Android `4.12.0` has deliberately missing ends, so duration is not directly comparable across platforms or versions without the qualifying count and sensitivity review.

## Payer conversion

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Activity UTC date, platform, country, and acquisition channel.

**Eligibility:** DAU in the segment; a payer is an active player whose reconciled net revenue on that date is positive.

**Formula:** Count of active players with player-day `net_revenue_usd > 0` divided by DAU.

**Exclusions:** Fully refunded, cancelled, zero-net, and non-active purchasers are excluded from the numerator; zero-DAU segments return `NULL`.

**Time rule:** Purchases use purchase UTC date, activity uses activity UTC date, and refunds supersede initial store status when reconciled.

**Known limitations:** Later refund arrivals can revise recent player-day net revenue and payer status.

## ARPDAU

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Activity UTC date, platform, country, and acquisition channel.

**Eligibility:** Segments with at least one DAU; all reconciled purchases assigned to the same date and install dimensions contribute revenue.

**Formula:** Reconciled `net_revenue_usd` divided by DAU.

**Exclusions:** Cancelled purchase value is excluded by reconciliation; zero-DAU segments return `NULL` rather than forcing revenue into an invalid ratio.

**Time rule:** Revenue is assigned to the original purchase UTC date; later refund evidence is restated onto that purchase date before aggregation rather than reported on the refund accounting date.

**Known limitations:** Purchase-date revenue can exist where DAU is zero, in which case ARPDAU is `NULL` even though revenue is retained. The fixture uses documented USD-normalized values and does not model tax, platform fees, chargebacks, or refunds beyond the observation window.

## Event participation

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Activity UTC date, platform, country, and acquisition channel.

**Eligibility:** DAU with a valid canonical `live_event_joined` event on the same UTC date.

**Formula:** Unique active event participants divided by DAU.

**Exclusions:** Duplicate arrivals, pre-install events, participation outside governed activity, and zero-DAU segments.

**Time rule:** Participation is assigned from event occurrence UTC date.

**Known limitations:** The current deterministic fixture emits no `live_event_joined` events, so the metric is structurally zero until participation instrumentation is added.

## Alliance adoption

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Activity UTC date, platform, country, and acquisition channel.

**Eligibility:** DAU with a valid alliance-membership interval covering the same UTC date; the fixture's retained valid intervals all carry active status.

**Formula:** Unique active alliance members divided by DAU.

**Exclusions:** Invalid membership intervals, intervals not covering the reporting date, non-active players, and zero-DAU segments.

**Time rule:** Membership uses a start-inclusive, end-exclusive UTC-date expansion and is intersected with player activity on that date.

**Known limitations:** Membership is approximated at daily interval coverage; the current fact does not separately filter `membership_status`, and a daily snapshot does not measure engagement quality, role, or intraday tenure.

## Progression velocity

**Source relation:** `mart_live_strategy__daily_kpis`

**Grain:** Progression-snapshot UTC date, platform, country, and acquisition channel.

**Eligibility:** Players with a prior governed progression snapshot and a positive elapsed whole-day interval.

**Formula:** For each player, level change divided by elapsed days since the prior snapshot; the daily segment value is the arithmetic mean of those player-level velocities.

**Exclusions:** First observations, zero-day intervals, and rows without a prior snapshot.

**Time rule:** Snapshot ordering uses the full UTC timestamp; reporting date uses the current snapshot's UTC date.

**Known limitations:** Sparse snapshots approximate progression between observations and do not identify when within the interval progress occurred; the arithmetic mean is sensitive to observation cadence.
