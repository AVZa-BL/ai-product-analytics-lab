# Trial Activation Rate

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `mart_subscription__trial_conversion_diagnostic`

## Grain
Mature trial cohort date.

## Eligibility
Valid trial starts whose scheduled trial end and maturity cutoff are observable.

## Formula
Mature trials with activation on or before scheduled trial end divided by mature trials.

## Exclusions
Immature trials, invalid trial starts, and activation events after scheduled trial end.

## Time rule
Activation and reconstructed trial end are compared as UTC timestamps.

## Known limitations
The metric describes timing association and is not an estimate of activation's causal effect.

## Validation query
`select metric_date, trial_activation_numerator, trial_activation_denominator, trial_activation_rate from mart_subscription__kpis_daily order by metric_date;`
