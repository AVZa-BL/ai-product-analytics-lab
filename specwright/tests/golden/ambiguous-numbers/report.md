# Specwright draft: needs answers

NEEDS ANSWERS: the documents do not give everything a spec needs. Nothing was invented to fill the gaps.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `04-ambiguous-numbers.md`. Attempts: 1 (0 repair round(s)).

## Questions for the analyst

- `population.daily_eligible_units` (ambiguous): `The brief says "A few thousand players open it every day". How many players, as a number, enter the garage each day?`
- `design.mde_relative` (ambiguous): `The brief hopes for "roughly a 10% relative lift". What relative lift is the smallest worth detecting?`
- `design.planned_duration_days` (ambiguous): `The brief says "about two weeks". How many days will the test run?`

## What the draft states

- `id` = `comet_racers_upgrade_prompt` - inferred
- `title` = `Garage upgrade prompt` - inferred
- `owner` = `racing-live` - quoted from `04-ambiguous-numbers.md`: `Owner: racing-live.`
- `hypothesis.null` = `The new prompt does not change the share of players who upgrade a car in the first week.` - inferred
- `hypothesis.alternative` = `The new prompt makes more players upgrade a car` - quoted from `04-ambiguous-numbers.md`: `The new prompt makes more players upgrade a car`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `04-ambiguous-numbers.md`: `Assignment is per player`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `Existing players who open the garage.` - quoted from `04-ambiguous-numbers.md`: `Existing players who open the garage.`
- `population.exposure_trigger` = `first opening of the garage` - quoted from `04-ambiguous-numbers.md`: `at the moment a player first opens the garage`
- `population.kind` = `existing_users` - quoted from `04-ambiguous-numbers.md`: `Existing players who open the garage.`
- `arms[0].name` = `control` - quoted from `04-ambiguous-numbers.md`: `The old prompt is the control`
- `arms[0].allocation` = `0.5` - quoted from `04-ambiguous-numbers.md`: `50/50, at the moment`
- `arms[0].is_control` = `True` - quoted from `04-ambiguous-numbers.md`: `The old prompt is the control`
- `arms[1].name` = `variant_a` - quoted from `04-ambiguous-numbers.md`: `the new one is variant_a`
- `arms[1].allocation` = `0.5` - quoted from `04-ambiguous-numbers.md`: `50/50, at the moment`
- `arms[1].is_control` = `False` - inferred
- `primary_metric.name` = `car_upgrade_7d` - inferred
- `primary_metric.kind` = `binary` - quoted from `04-ambiguous-numbers.md`: `Share of players who upgrade a car within 7 days`
- `primary_metric.baseline` = `0.22` - quoted from `04-ambiguous-numbers.md`: `22% today`
- `design.alpha` = `0.05` - quoted from `04-ambiguous-numbers.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.power` = `0.8` - quoted from `04-ambiguous-numbers.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.sided` = `two_sided` - quoted from `04-ambiguous-numbers.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.min_duration_days` = `7` - inferred (note: `The brief says "certainly not less than a week"; a week is taken as 7 days. Confirm.`)
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `04-ambiguous-numbers.md`: `We will look at it when it is done.`
- `procedure.srm_check_cadence` = `daily` - quoted from `04-ambiguous-numbers.md`: `Check the sample ratio daily.`

## Inferred values to confirm

- `id` = `comet_racers_upgrade_prompt`
- `title` = `Garage upgrade prompt`
- `hypothesis.null` = `The new prompt does not change the share of players who upgrade a car in the first week.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[1].is_control` = `False`
- `primary_metric.name` = `car_upgrade_7d`
- `design.min_duration_days` = `7`

## Attempts

### Attempt 1 (`replay`)

0 blocker(s), 0 warning(s), 3 question(s).

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `04-ambiguous-numbers.md`: sha256 9a46bdfbb5d84e9f661cc6c071f855a701241223050eac66d9f341d71d58ff82, 896 bytes
- Specwright 0.1.0, Referee 0.1.0
