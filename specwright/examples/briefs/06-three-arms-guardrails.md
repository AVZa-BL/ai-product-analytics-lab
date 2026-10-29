<!-- Synthetic brief, written by an agent for Specwright's examples. Not a real product or plan. -->
# Emberfall: bundle and discount test

Emberfall is a PC and console action RPG with an in-game store. The economy team wants to compare
two ways to sell the Ember Bundle: a 20% discount, or a three-item bundle at the same price.

**Hypothesis.** Either variant raises the share of players who buy the Ember Bundle within 7 days
of seeing it, compared with the current plain listing.

**Arms.** control (the plain listing), variant_b (20% discount) and variant_c (three-item bundle),
in thirds: 33.3% of the players each. Players are assigned individually when they first open the
store page. Existing players only. Players do not influence each other's store pages.

**Traffic.** 9,000 players a day open the store page for the first time.

**Primary metric.** Bundle purchase rate within 7 days: 3.0% today. We want to detect a 20%
relative lift in either variant. Alpha 0.05, power 80%, two-sided, with a Bonferroni correction
for the two comparisons against control.

**Guardrails.** Refund rate of bundle purchases (1.5% today) must not rise by more than 10%
relative. Average session length (18 minutes today, standard deviation 11) must not fall by more
than 5% relative. We also want to watch items bought per player (a count), with no tolerance.
We use the player's spend in the 28 days before they first see the page as a pre-period covariate.

**Schedule.** 28 days, and no less than 21 days.

**Procedure.** Fixed horizon: read once at the end. Check the sample ratio every day. The bucketing
salt is emberfall_bundle_2026_q4. Owner: economy-analytics.
