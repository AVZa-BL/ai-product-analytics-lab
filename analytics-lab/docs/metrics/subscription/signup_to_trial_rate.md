# Signup-to-Trial Rate

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily`

## Grain
Signup cohort date.

## Eligibility
Users who signed up on the metric date; the cohort is reportable after seven complete days.

## Formula
Signups whose first trial begins within seven days of signup divided by signups.

## Exclusions
Immature cohorts and records without a valid signup.

## Time rule
Signup and trial timestamps use UTC; values remain null until the seven-day window matures.

## Known limitations
Synthetic acquisition data does not establish causal channel effects.

## Validation query
`select metric_date, signup_to_trial_numerator, signup_to_trial_denominator, signup_to_trial_rate from mart_subscription__kpis_daily order by metric_date;`
