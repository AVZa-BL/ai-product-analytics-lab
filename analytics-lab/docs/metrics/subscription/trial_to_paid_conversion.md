# Trial-to-Paid Conversion

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `mart_subscription__trial_conversion_diagnostic`

## Grain
Mature trial cohort date; diagnostic dimensions are channel, campaign, plan, and activation segment.

## Eligibility
Valid trial starts whose 21-day maturity cutoff is within the observation window.

## Formula
Eligible trials with first paid entitlement no later than three days after scheduled trial end divided by eligible trials.

## Exclusions
Immature cohorts, duplicate webhooks after canonical selection, and trials without a valid trial-start event.

## Time rule
Trial end uses the reconstructed UTC timestamp derived from the recorded local value and source timezone.

## Known limitations
Payment failure is reported separately; channel comparisons are associative, not causal.

## Validation query
`select metric_date, trial_to_paid_numerator, trial_to_paid_denominator, trial_to_paid_rate from mart_subscription__kpis_daily order by metric_date;`
