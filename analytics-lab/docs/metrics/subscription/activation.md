# Activation Rate

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily`

## Grain
Signup cohort date.

## Eligibility
Users who signed up on the metric date; the cohort is reportable after seven complete days.

## Formula
Signups with a canonical activation event within seven days of signup divided by signups.

## Exclusions
Immature cohorts, events before signup, events after day seven, and unmapped product events.

## Time rule
The seven-day window is measured from the UTC signup timestamp.

## Known limitations
Activation is an observed event and does not prove durable engagement.

## Validation query
`select metric_date, activation_numerator, activation_denominator, activation_rate from mart_subscription__kpis_daily order by metric_date;`
