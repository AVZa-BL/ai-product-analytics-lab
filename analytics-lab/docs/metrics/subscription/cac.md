# Customer Acquisition Cost

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily`, `fct_subscription__marketing_spend_daily`, and `dim_subscription__users`

## Grain
UTC calendar date.

## Eligibility
Tracked campaign spend and newly paid users attributed to a non-unknown campaign.

## Formula
Tracked campaign spend divided by attributed newly paid users.

## Exclusions
Unknown campaigns, unattributed paid users, and dates with zero attributed new paid users.

## Time rule
Spend date and first-paid cohort date are compared as UTC calendar dates.

## Known limitations
Attribution is synthetic last-known campaign evidence and excludes organic opportunity cost.

## Validation query
`select metric_date, cac_numerator_usd, cac_denominator, cac_usd from mart_subscription__kpis_daily order by metric_date;`
