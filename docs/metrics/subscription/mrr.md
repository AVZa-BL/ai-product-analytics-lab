# Monthly Recurring Revenue

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `fct_subscription__daily_user_state`

## Grain
UTC calendar date.

## Eligibility
Paid-active user-day rows with a positive normalized monthly recurring revenue value.

## Formula
Sum of monthly recurring revenue across paid-active state on the metric date.

## Exclusions
Trial state, failed payments, refunded revenue, and inactive entitlement periods.

## Time rule
Paid state uses half-open UTC calendar-date entitlement intervals.

## Known limitations
Annual plans are normalized to monthly value; this is not recognized accounting revenue.

## Validation query
`select metric_date, paid_active_users, mrr_usd from mart_subscription__kpis_daily order by metric_date;`
