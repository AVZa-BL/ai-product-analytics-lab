# D30 Paid Retention

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `fct_subscription__daily_user_state`

## Grain
First-paid cohort date.

## Eligibility
Users whose first paid entitlement began exactly 30 days before the reporting date.

## Formula
Eligible first-paid users active on paid day 30 divided by eligible first-paid users.

## Exclusions
Cohorts without 30 days of follow-up and users without a valid first paid entitlement.

## Time rule
Day 30 is based on UTC calendar dates and half-open entitlement intervals.

## Known limitations
Calendar-day retention can differ from exact 720-hour retention near day boundaries.

## Validation query
`select metric_date, d30_paid_retention_numerator, d30_paid_retention_denominator, d30_paid_retention_rate from mart_subscription__kpis_daily order by metric_date;`
