# Specwright draft: needs answers

NEEDS ANSWERS: the documents do not give everything a spec needs. Nothing was invented to fill the gaps.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `03-missing-baseline.md`. Attempts: 1 (0 repair round(s)).

## Questions for the analyst

- `primary_metric.baseline` (missing): `What share of new players finish the old tutorial today? The brief says it has never been measured: a baseline from any earlier cohort or a pilot is needed to size the test.`
- `Is there an older cohort or a pilot from which the old tutorial's completion rate can be measured?`

## What the draft states

- `id` = `harbor_tales_tutorial` - inferred
- `title` = `New Harbor Tales tutorial` - inferred
- `owner` = `onboarding` - quoted from `03-missing-baseline.md`: `Owner: onboarding.`
- `hypothesis.null` = `The new tutorial does not change the share of new players who finish it.` - inferred
- `hypothesis.alternative` = `More new players finish the new tutorial than the old one.` - quoted from `03-missing-baseline.md`: `More new players finish the new tutorial than the old one.`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `03-missing-baseline.md`: `assigned per player at the first launch`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `New players.` - quoted from `03-missing-baseline.md`: `New players, assigned per player`
- `population.exposure_trigger` = `tutorial screen shown` - quoted from `03-missing-baseline.md`: `Exposure is the moment the tutorial screen is`
- `population.exposure_timing` = `pre_treatment` - quoted from `03-missing-baseline.md`: `which happens before any difference between the arms`
- `population.kind` = `new_users` - quoted from `03-missing-baseline.md`: `New players, assigned per player`
- `population.daily_eligible_units` = `2500` - quoted from `03-missing-baseline.md`: `2,500 new players start the`
- `arms[0].name` = `control` - quoted from `03-missing-baseline.md`: `the old tutorial (control)`
- `arms[0].allocation` = `0.5` - quoted from `03-missing-baseline.md`: `50/50 between the old tutorial`
- `arms[0].is_control` = `True` - quoted from `03-missing-baseline.md`: `the old tutorial (control)`
- `arms[1].name` = `variant_a` - quoted from `03-missing-baseline.md`: `the new one (variant_a)`
- `arms[1].allocation` = `0.5` - quoted from `03-missing-baseline.md`: `50/50 between the old tutorial`
- `arms[1].is_control` = `False` - inferred
- `primary_metric.name` = `tutorial_completion` - inferred
- `primary_metric.kind` = `binary` - inferred (note: `a completion rate`)
- `design.mde_relative` = `0.08` - quoted from `03-missing-baseline.md`: `improve it by 8% relative`
- `design.alpha` = `0.05` - quoted from `03-missing-baseline.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.power` = `0.8` - quoted from `03-missing-baseline.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.sided` = `two_sided` - quoted from `03-missing-baseline.md`: `two-sided`
- `design.planned_duration_days` = `14` - quoted from `03-missing-baseline.md`: `We plan 14 days`
- `design.min_duration_days` = `7` - quoted from `03-missing-baseline.md`: `would not stop before 7`
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `03-missing-baseline.md`: `Read once at the end of the test.`
- `procedure.srm_check_cadence` = `daily` - quoted from `03-missing-baseline.md`: `Check the sample ratio daily.`

## Inferred values to confirm

- `id` = `harbor_tales_tutorial`
- `title` = `New Harbor Tales tutorial`
- `hypothesis.null` = `The new tutorial does not change the share of new players who finish it.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[1].is_control` = `False`
- `primary_metric.name` = `tutorial_completion`
- `primary_metric.kind` = `binary`

## Attempts

### Attempt 1 (`replay`)

0 blocker(s), 0 warning(s), 1 question(s).

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `03-missing-baseline.md`: sha256 966642c31ffc6bc801bd18927bad2ab19e3eadb5dc55ac45a72cdb0272a9b9b2, 932 bytes
- Specwright 0.1.0, Referee 0.1.0
