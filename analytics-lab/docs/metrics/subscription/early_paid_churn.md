# Early Paid Churn

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `int_subscription__subscription_periods`

## Grain
First-paid cohort date.

## Eligibility
Users with a valid first paid entitlement and 30 complete days of observation.

## Formula
Eligible first-paid users with an effective cancellation within 30 days divided by eligible first-paid users.

## Exclusions
Immature cohorts and cancellations lacking a valid effective timestamp.

## Time rule
Churn uses lifecycle `effective_at`, not delayed webhook ingestion time.

## Known limitations
The synthetic lifecycle does not model every pause, grace-period, or reactivation policy.

## Validation query
`select metric_date, early_paid_churn_numerator, early_paid_churn_denominator, early_paid_churn_rate from mart_subscription__kpis_daily order by metric_date;`
