# Specwright draft: ok

OK: a spec was built and Referee's design rules raise no blocker.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `05-buried-in-design-doc.md`. Attempts: 1 (0 repair round(s)).

## Computed by Referee (the power plan)

- needs 73,182 players in total (`control` 36,591, `variant_a` 36,591), 13 days at the daily traffic stated (14 days to whole weeks)
- the planned duration delivers 168,000 players
- the smallest relative effect that duration can power: 5.2%
- powered: yes

## What the draft states

- `id` = `skyharbor_pass_price` - inferred
- `title` = `Season Pass price test` - inferred
- `owner` = `live-ops` - quoted from `05-buried-in-design-doc.md`: `Owner: live-ops.`
- `hypothesis.null` = `Lowering the Season Pass price to 7.99 USD does not change the share of players who buy it within 14 days of first seeing the pass screen.` - inferred
- `hypothesis.alternative` = `The lower price raises the pass purchase rate.` - quoted from `05-buried-in-design-doc.md`: `The goal metric is the Season Pass purchase rate`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `05-buried-in-design-doc.md`: `Players are assigned individually, 50/50`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `Existing players who see the pass screen.` - quoted from `05-buried-in-design-doc.md`: `Only existing players are included`
- `population.exposure_trigger` = `first sight of the pass screen` - quoted from `05-buried-in-design-doc.md`: `the first time they see the pass screen`
- `population.exposure_timing` = `pre_treatment` - quoted from `05-buried-in-design-doc.md`: `the price is shown after assignment`
- `population.interference` = `none_expected` - quoted from `05-buried-in-design-doc.md`: `players do not interact over the price`
- `population.kind` = `existing_users` - quoted from `05-buried-in-design-doc.md`: `Only existing players are included`
- `population.daily_eligible_units` = `6000` - quoted from `05-buried-in-design-doc.md`: `6,000 players a day see`
- `arms[0].name` = `control` - quoted from `05-buried-in-design-doc.md`: `Control keeps the price at 9.99 USD.`
- `arms[0].allocation` = `0.5` - quoted from `05-buried-in-design-doc.md`: `Players are assigned individually, 50/50`
- `arms[0].is_control` = `True` - quoted from `05-buried-in-design-doc.md`: `Control keeps the price at 9.99 USD.`
- `arms[1].name` = `variant_a` - quoted from `05-buried-in-design-doc.md`: `called variant_a, lowers it to 7.99 USD`
- `arms[1].allocation` = `0.5` - quoted from `05-buried-in-design-doc.md`: `Players are assigned individually, 50/50`
- `arms[1].is_control` = `False` - inferred
- `primary_metric.name` = `season_pass_purchase_14d` - inferred
- `primary_metric.kind` = `binary` - quoted from `05-buried-in-design-doc.md`: `the share of players who buy the pass within 14`
- `primary_metric.baseline` = `0.065` - quoted from `05-buried-in-design-doc.md`: `In the last season it was 6.5%.`
- `guardrails[0].name` = `active_days_14d` - inferred
- `guardrails[0].kind` = `continuous` - quoted from `05-buried-in-design-doc.md`: `(6.4 days on average, with`
- `guardrails[0].baseline` = `6.4` - quoted from `05-buried-in-design-doc.md`: `(6.4 days on average, with`
- `guardrails[0].baseline_std` = `3.9` - quoted from `05-buried-in-design-doc.md`: `a standard deviation of 3.9`
- `guardrails[0].harmful_direction` = `decrease` - quoted from `05-buried-in-design-doc.md`: `must not fall by more than 3% relative`
- `guardrails[0].tolerance_relative` = `0.03` - quoted from `05-buried-in-design-doc.md`: `must not fall by more than 3% relative`
- `design.mde_relative` = `0.08` - quoted from `05-buried-in-design-doc.md`: `We care about an 8%`
- `design.alpha` = `0.05` - quoted from `05-buried-in-design-doc.md`: `We use alpha 0.05, power 80% and a two-sided test.`
- `design.power` = `0.8` - quoted from `05-buried-in-design-doc.md`: `We use alpha 0.05, power 80% and a two-sided test.`
- `design.sided` = `two_sided` - quoted from `05-buried-in-design-doc.md`: `a two-sided test`
- `design.planned_duration_days` = `28` - quoted from `05-buried-in-design-doc.md`: `The test runs 28 days`
- `design.min_duration_days` = `21` - quoted from `05-buried-in-design-doc.md`: `not less than 21 days`
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `05-buried-in-design-doc.md`: `read once, at the end of the 28 days`
- `procedure.srm_check_cadence` = `daily` - quoted from `05-buried-in-design-doc.md`: `Check the sample ratio daily.`

## Inferred values to confirm

- `id` = `skyharbor_pass_price`
- `title` = `Season Pass price test`
- `hypothesis.null` = `Lowering the Season Pass price to 7.99 USD does not change the share of players who buy it within 14 days of first seeing the pass screen.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[1].is_control` = `False`
- `primary_metric.name` = `season_pass_purchase_14d`
- `guardrails[0].name` = `active_days_14d`

## Design review (Referee's HYP, DES and PRO rules)

- warning: `DES-008` `No pre-period covariate declared`. What to do: `Declare design.pre_period_covariate, for example the primary metric measured for each unit before exposure.`
- warning: `HYP-002` `Primary metric has no governed reference`. What to do: `Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`
- info: `PRO-004` `Bucketing salt not declared`. What to do: `Set procedure.bucketing_salt to a value unique to this experiment, for example its id.`

## Attempts

### Attempt 1 (`replay`)

0 blocker(s), 2 warning(s), 0 question(s).
- warning: `[RULE:DES-008] No pre-period covariate declared. Declare design.pre_period_covariate, for example the primary metric measured for each unit before exposure.`
- warning: `[RULE:HYP-002] Primary metric has no governed reference. Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `05-buried-in-design-doc.md`: sha256 595a1009eddcf91564356bf0b1613f18759ca74768c134bf1443b4ee4eec697c, 3,620 bytes
- Specwright 0.1.0, Referee 0.1.0
- spec fingerprint: sha256:359ff3e516580b90bb32acebe88a87e4cca25e7f5426d318a360a28847ae922f
