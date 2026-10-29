# Specwright draft: infeasible

INFEASIBLE: the numbers the documents give cannot reach the power the spec asks for.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `02-infeasible-niche-event.md`. Attempts: 1 (0 repair round(s)).

## Why it is infeasible

- the design needs 630,412 players, and 14 days at 300 players a day deliver 4,200; that duration can only power a relative effect of 70.1% (the draft asks for 5.0%). Run for 2,102 days, bring in more eligible players, or accept a larger effect. The numbers are the documents' own, and none was changed to make the design pass

## Computed by Referee (the power plan)

- needs 630,412 players in total (`control` 315,206, `variant_a` 315,206), 2,102 days at the daily traffic stated (2,107 days to whole weeks)
- the planned duration delivers 4,200 players
- the smallest relative effect that duration can power: 70.1%
- powered: no

## What the draft states

- `id` = `lantern_festival_reward` - inferred
- `title` = `Larger Lantern Festival reward for guild leaders` - inferred
- `owner` = `community-design` - quoted from `02-infeasible-niche-event.md`: `Owner: community-design.`
- `hypothesis.null` = `A larger reward does not change how many guild leaders complete the event.` - inferred
- `hypothesis.alternative` = `A larger reward makes more guild leaders complete the event.` - quoted from `02-infeasible-niche-event.md`: `A larger reward makes more guild leaders complete the event.`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `02-infeasible-niche-event.md`: `Assignment is per player, 50/50`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `Guild leaders who open the event page.` - quoted from `02-infeasible-niche-event.md`: `Guild leaders who open the event page.`
- `population.exposure_trigger` = `first opening of the event page` - quoted from `02-infeasible-niche-event.md`: `when they first open the page`
- `population.exposure_timing` = `pre_treatment` - quoted from `02-infeasible-niche-event.md`: `before they see the reward`
- `population.interference` = `none_expected` - quoted from `02-infeasible-niche-event.md`: `Guild leaders in different guilds do not interact.`
- `population.kind` = `existing_users` - quoted from `02-infeasible-niche-event.md`: `Guild leaders who open the event page.`
- `population.daily_eligible_units` = `300` - quoted from `02-infeasible-niche-event.md`: `300 guild leaders open it each day`
- `arms[0].name` = `control` - quoted from `02-infeasible-niche-event.md`: `Control: today's reward.`
- `arms[0].allocation` = `0.5` - quoted from `02-infeasible-niche-event.md`: `Assignment is per player, 50/50`
- `arms[0].is_control` = `True` - quoted from `02-infeasible-niche-event.md`: `Control: today's reward.`
- `arms[1].name` = `variant_a` - quoted from `02-infeasible-niche-event.md`: `between control and variant_a`
- `arms[1].allocation` = `0.5` - quoted from `02-infeasible-niche-event.md`: `Assignment is per player, 50/50`
- `arms[1].is_control` = `False` - inferred
- `primary_metric.name` = `event_completion_7d` - inferred
- `primary_metric.kind` = `binary` - quoted from `02-infeasible-niche-event.md`: `Event completion within 7 days of opening the page`
- `primary_metric.baseline` = `0.02` - quoted from `02-infeasible-niche-event.md`: `2% today`
- `design.mde_relative` = `0.05` - quoted from `02-infeasible-niche-event.md`: `detect a 5% relative improvement`
- `design.alpha` = `0.05` - quoted from `02-infeasible-niche-event.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.power` = `0.8` - quoted from `02-infeasible-niche-event.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.sided` = `two_sided` - quoted from `02-infeasible-niche-event.md`: `two-sided`
- `design.planned_duration_days` = `14` - quoted from `02-infeasible-niche-event.md`: `those 14 days, and no less than 7 days`
- `design.min_duration_days` = `7` - quoted from `02-infeasible-niche-event.md`: `no less than 7 days`
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `02-infeasible-niche-event.md`: `Read once at the end.`
- `procedure.srm_check_cadence` = `daily` - quoted from `02-infeasible-niche-event.md`: `Check the sample ratio every day.`

## Inferred values to confirm

- `id` = `lantern_festival_reward`
- `title` = `Larger Lantern Festival reward for guild leaders`
- `hypothesis.null` = `A larger reward does not change how many guild leaders complete the event.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[1].is_control` = `False`
- `primary_metric.name` = `event_completion_7d`

## Design review (Referee's HYP, DES and PRO rules)

- blocker: `DES-001` `Design cannot reach the planned power`. What to do: `Run for the required days, bring in more eligible units, accept the larger minimum detectable effect the evidence reports, or choose a target effect that can exist.`
- warning: `DES-008` `No pre-period covariate declared`. What to do: `Declare design.pre_period_covariate, for example the primary metric measured for each unit before exposure.`
- warning: `HYP-002` `Primary metric has no governed reference`. What to do: `Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`
- warning: `PRO-003` `No guardrail metrics declared`. What to do: `Declare at least one guardrail with its harmful direction and a tolerance, for example a refund rate that must not rise by more than 10% relative.`
- info: `DES-009` `The cohort check of the results review would not run on this plan`. What to do: `If an effect that differs between the weeks players joined could matter for this change, plan at least 21 days (42 days or more allows blocks of 14 days, which need fewer players a week), bring in more eligible units each day or give the smaller arm a larger share, keep the arms within 9 to 1, and randomise and analyse in the same independent unit (player, user or device). The evidence gives the units a day that pass with even arrivals; allow more, because arrivals vary (design section 21.6: spiky arrivals need 1.5 to 3 times as much). Otherwise accept that the cohort check will not run: the other results checks are not affected.`
- info: `PRO-004` `Bucketing salt not declared`. What to do: `Set procedure.bucketing_salt to a value unique to this experiment, for example its id.`

## Attempts

### Attempt 1 (`replay`)

1 blocker(s), 3 warning(s), 0 question(s).
- blocker: `[RULE:DES-001] Design cannot reach the planned power. Run for the required days, bring in more eligible units, accept the larger minimum detectable effect the evidence reports, or choose a target effect that can exist.`
- warning: `[RULE:DES-008] No pre-period covariate declared. Declare design.pre_period_covariate, for example the primary metric measured for each unit before exposure.`
- warning: `[RULE:HYP-002] Primary metric has no governed reference. Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`
- warning: `[RULE:PRO-003] No guardrail metrics declared. Declare at least one guardrail with its harmful direction and a tolerance, for example a refund rate that must not rise by more than 10% relative.`

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `02-infeasible-niche-event.md`: sha256 0520c79e3ed0a48e2d62be546197956fb5b83ea720d22d17d3ddb76581fbd32c, 1,069 bytes
- Specwright 0.1.0, Referee 0.1.0
- spec fingerprint: sha256:2e04447e06593ca7b31582a2c2450553fb813e9082509409a79e8569e417297d
