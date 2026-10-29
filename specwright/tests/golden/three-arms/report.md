# Specwright draft: ok

OK: a spec was built and Referee's design rules raise no blocker.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `06-three-arms-guardrails.md`. Attempts: 1 (0 repair round(s)).

## Computed by Referee (the power plan)

- needs 50,550 players in total (`control` 16,850, `variant_b` 16,850, `variant_c` 16,850), 6 days at the daily traffic stated (7 days to whole weeks)
- the planned duration delivers 252,000 players
- the smallest relative effect that duration can power: 8.7%
- powered: yes

## What the draft states

- `id` = `emberfall_bundle_offer` - inferred
- `title` = `Ember Bundle: discount and bundle variants` - inferred
- `owner` = `economy-analytics` - quoted from `06-three-arms-guardrails.md`: `Owner: economy-analytics.`
- `hypothesis.null` = `Neither variant changes the share of players who buy the Ember Bundle within 7 days of seeing it.` - inferred
- `hypothesis.alternative` = `Either variant raises the share of players who buy the Ember Bundle` - quoted from `06-three-arms-guardrails.md`: `Either variant raises the share of players who buy the Ember Bundle`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `06-three-arms-guardrails.md`: `Players are assigned individually`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `Existing players who open the store page.` - quoted from `06-three-arms-guardrails.md`: `Existing players only.`
- `population.exposure_trigger` = `first opening of the store page` - quoted from `06-three-arms-guardrails.md`: `when they first open the store page`
- `population.interference` = `none_expected` - quoted from `06-three-arms-guardrails.md`: `Players do not influence each other's store pages.`
- `population.kind` = `existing_users` - quoted from `06-three-arms-guardrails.md`: `Existing players only.`
- `population.daily_eligible_units` = `9000` - quoted from `06-three-arms-guardrails.md`: `9,000 players a day open the store page`
- `arms[0].name` = `control` - quoted from `06-three-arms-guardrails.md`: `control (the plain listing)`
- `arms[0].allocation` = `0.3333333333333333` - inferred (note: `The brief says thirds (33.3% each); Referee needs the three shares to sum to 1.`)
- `arms[0].is_control` = `True` - quoted from `06-three-arms-guardrails.md`: `control (the plain listing)`
- `arms[1].name` = `variant_b` - quoted from `06-three-arms-guardrails.md`: `variant_b (20% discount)`
- `arms[1].allocation` = `0.3333333333333333` - inferred (note: `thirds`)
- `arms[1].is_control` = `False` - inferred
- `arms[2].name` = `variant_c` - quoted from `06-three-arms-guardrails.md`: `variant_c (three-item bundle)`
- `arms[2].allocation` = `0.3333333333333333` - inferred (note: `thirds`)
- `arms[2].is_control` = `False` - inferred
- `primary_metric.name` = `bundle_purchase_7d` - inferred
- `primary_metric.kind` = `binary` - quoted from `06-three-arms-guardrails.md`: `Bundle purchase rate within 7 days`
- `primary_metric.baseline` = `0.03` - quoted from `06-three-arms-guardrails.md`: `3.0% today`
- `guardrails[0].name` = `bundle_refund_rate` - inferred
- `guardrails[0].kind` = `binary` - quoted from `06-three-arms-guardrails.md`: `Refund rate of bundle purchases (1.5% today)`
- `guardrails[0].baseline` = `0.015` - quoted from `06-three-arms-guardrails.md`: `Refund rate of bundle purchases (1.5% today)`
- `guardrails[0].harmful_direction` = `increase` - quoted from `06-three-arms-guardrails.md`: `must not rise by more than 10%`
- `guardrails[0].tolerance_relative` = `0.1` - quoted from `06-three-arms-guardrails.md`: `must not rise by more than 10%`
- `guardrails[1].name` = `session_minutes` - inferred
- `guardrails[1].kind` = `continuous` - quoted from `06-three-arms-guardrails.md`: `Average session length (18 minutes today, standard deviation 11)`
- `guardrails[1].baseline` = `18` - quoted from `06-three-arms-guardrails.md`: `Average session length (18 minutes today, standard deviation 11)`
- `guardrails[1].baseline_std` = `11` - quoted from `06-three-arms-guardrails.md`: `Average session length (18 minutes today, standard deviation 11)`
- `guardrails[1].harmful_direction` = `decrease` - quoted from `06-three-arms-guardrails.md`: `must not fall by more than 5% relative`
- `guardrails[1].tolerance_relative` = `0.05` - quoted from `06-three-arms-guardrails.md`: `must not fall by more than 5% relative`
- `secondary_metrics[0].name` = `items_per_player` - quoted from `06-three-arms-guardrails.md`: `items bought per player (a count)`
- `secondary_metrics[0].kind` = `continuous` - inferred (note: `a count per player`)
- `secondary_metrics[0].family` = `count` - quoted from `06-three-arms-guardrails.md`: `items bought per player (a count)`
- `design.mde_relative` = `0.2` - quoted from `06-three-arms-guardrails.md`: `detect a 20%`
- `design.alpha` = `0.05` - quoted from `06-three-arms-guardrails.md`: `Alpha 0.05, power 80%, two-sided`
- `design.power` = `0.8` - quoted from `06-three-arms-guardrails.md`: `Alpha 0.05, power 80%, two-sided`
- `design.sided` = `two_sided` - quoted from `06-three-arms-guardrails.md`: `two-sided`
- `design.planned_duration_days` = `28` - quoted from `06-three-arms-guardrails.md`: `28 days, and no less than 21 days`
- `design.min_duration_days` = `21` - quoted from `06-three-arms-guardrails.md`: `no less than 21 days`
- `design.alpha_adjustment` = `bonferroni` - quoted from `06-three-arms-guardrails.md`: `with a Bonferroni correction`
- `design.pre_period_covariate` = `player_spend_28d` - quoted from `06-three-arms-guardrails.md`: `spend in the 28 days before they first see the page as a pre-period covariate`
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `06-three-arms-guardrails.md`: `Fixed horizon: read once at the end.`
- `procedure.srm_check_cadence` = `daily` - quoted from `06-three-arms-guardrails.md`: `Check the sample ratio every day.`
- `procedure.bucketing_salt` = `emberfall_bundle_2026_q4` - quoted from `06-three-arms-guardrails.md`: `emberfall_bundle_2026_q4`

## Inferred values to confirm

- `id` = `emberfall_bundle_offer`
- `title` = `Ember Bundle: discount and bundle variants`
- `hypothesis.null` = `Neither variant changes the share of players who buy the Ember Bundle within 7 days of seeing it.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[0].allocation` = `0.3333333333333333`
- `arms[1].allocation` = `0.3333333333333333`
- `arms[1].is_control` = `False`
- `arms[2].allocation` = `0.3333333333333333`
- `arms[2].is_control` = `False`
- `primary_metric.name` = `bundle_purchase_7d`
- `guardrails[0].name` = `bundle_refund_rate`
- `guardrails[1].name` = `session_minutes`
- `secondary_metrics[0].kind` = `continuous`

## Design review (Referee's HYP, DES and PRO rules)

- warning: `HYP-002` `Primary metric has no governed reference`. What to do: `Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`

## Attempts

### Attempt 1 (`replay`)

0 blocker(s), 1 warning(s), 0 question(s).
- warning: `[RULE:HYP-002] Primary metric has no governed reference. Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `06-three-arms-guardrails.md`: sha256 551d8ec39132ba237b0171b199b7378df03551ceafa53caa27008c02caef76d8, 1,666 bytes
- Specwright 0.1.0, Referee 0.1.0
- spec fingerprint: sha256:91851d7db29eb98a1c7183150e1bffc2869800f84af97e8314979b90829d36a9
