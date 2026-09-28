# Net Revenue Retention

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `fct_subscription__daily_user_state`

## Grain
UTC calendar date for the paid cohort active at the start of that reporting month.

## Eligibility
Users paid-active on the first calendar day of the reporting month with positive starting MRR.

## Formula
Current MRR from the month-start paid cohort, net of churn, divided by that cohort's starting MRR.

## Exclusions
New paid users after month start and months with zero starting cohort MRR.

## Time rule
Month boundaries and daily state use UTC calendar dates.

## Known limitations
The synthetic scenario contains no upgrades, downgrades, or currency movement.

## Validation query
`select metric_date, nrr_numerator_usd, nrr_denominator_usd, nrr from mart_subscription__kpis_daily order by metric_date;`
