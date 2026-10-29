# Specwright draft: ok

OK: a spec was built and Referee's design rules raise no blocker.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `08-stated-size-differs.md`. Attempts: 1 (0 repair round(s)).

## Computed by Referee (the power plan)

- needs 16,412 players in total (`control` 8,206, `variant_a` 8,206), 5 days at the daily traffic stated (7 days to whole weeks)
- the planned duration delivers 56,000 players
- the smallest relative effect that duration can power: 3.2%
- powered: yes

## What the draft states

- `id` = `gloomwood_boss_damage` - inferred
- `title` = `Lower first-dungeon boss damage` - inferred
- `owner` = `dungeon-design` - quoted from `08-stated-size-differs.md`: `Owner: dungeon-design.`
- `hypothesis.null` = `The lower damage does not change how many players clear the first dungeon within 7 days.` - inferred
- `hypothesis.alternative` = `The lower damage makes more players clear the first dungeon` - quoted from `08-stated-size-differs.md`: `The lower damage makes more players clear the first dungeon`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `08-stated-size-differs.md`: `Assignment is per player, 50/50`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `Existing players who enter the first dungeon.` - quoted from `08-stated-size-differs.md`: `Existing players.`
- `population.exposure_trigger` = `first entry into the dungeon` - quoted from `08-stated-size-differs.md`: `when a player first enters the dungeon`
- `population.kind` = `existing_users` - quoted from `08-stated-size-differs.md`: `Existing players.`
- `population.daily_eligible_units` = `4000` - quoted from `08-stated-size-differs.md`: `4,000 players enter the dungeon for the first time each day`
- `arms[0].name` = `control` - quoted from `08-stated-size-differs.md`: `Control keeps the old damage`
- `arms[0].allocation` = `0.5` - quoted from `08-stated-size-differs.md`: `Assignment is per player, 50/50`
- `arms[0].is_control` = `True` - quoted from `08-stated-size-differs.md`: `Control keeps the old damage`
- `arms[1].name` = `variant_a` - quoted from `08-stated-size-differs.md`: `variant_a has the lower damage`
- `arms[1].allocation` = `0.5` - quoted from `08-stated-size-differs.md`: `Assignment is per player, 50/50`
- `arms[1].is_control` = `False` - inferred
- `primary_metric.name` = `dungeon_clear_7d` - inferred
- `primary_metric.kind` = `binary` - quoted from `08-stated-size-differs.md`: `Dungeon clear rate within 7 days`
- `primary_metric.baseline` = `0.35` - quoted from `08-stated-size-differs.md`: `35% today`
- `design.mde_relative` = `0.06` - quoted from `08-stated-size-differs.md`: `detect a 6% relative lift`
- `design.alpha` = `0.05` - quoted from `08-stated-size-differs.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.power` = `0.8` - quoted from `08-stated-size-differs.md`: `Alpha 0.05, power 80%, two-sided.`
- `design.sided` = `two_sided` - quoted from `08-stated-size-differs.md`: `two-sided`
- `design.planned_duration_days` = `14` - quoted from `08-stated-size-differs.md`: `14 days, and no less than 14 days`
- `design.min_duration_days` = `14` - quoted from `08-stated-size-differs.md`: `no less than 14 days`
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `08-stated-size-differs.md`: `Read once at the end.`
- `procedure.srm_check_cadence` = `daily` - quoted from `08-stated-size-differs.md`: `Check the sample ratio daily.`
- `stated.required_total_players` = `20000` - quoted from `08-stated-size-differs.md`: `we need 20,000 players in total`

## Inferred values to confirm

- `id` = `gloomwood_boss_damage`
- `title` = `Lower first-dungeon boss damage`
- `hypothesis.null` = `The lower damage does not change how many players clear the first dungeon within 7 days.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[1].is_control` = `False`
- `primary_metric.name` = `dungeon_clear_7d`

## Design review (Referee's HYP, DES and PRO rules)

- warning: `DES-006` `Interference between units is possible`. What to do: `Randomize at a level that contains the interaction (clusters of players), or set population.interference to none_expected and record why.`
- warning: `DES-008` `No pre-period covariate declared`. What to do: `Declare design.pre_period_covariate: the name of a column of the experiment's outcomes file that holds, for each player, a measure taken before the player's first exposure, for example the primary metric over the week before. The results review then shows the adjusted estimate, which is the registered analysis, beside the unadjusted one, and checks that the covariate is balanced across the arms. A measure taken after the treatment can act would remove part of the real effect.`
- warning: `HYP-002` `Primary metric has no governed reference`. What to do: `Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`
- warning: `PRO-003` `No guardrail metrics declared`. What to do: `Declare at least one guardrail with its harmful direction and a tolerance, for example a refund rate that must not rise by more than 10% relative.`
- info: `DES-009` `The cohort check of the results review would not run on this plan`. What to do: `If an effect that differs between the weeks players joined could matter for this change, plan at least 21 days (42 days or more allows blocks of 14 days, which need fewer players a week), bring in more eligible units each day or give the smaller arm a larger share, keep the arms within 9 to 1, and randomise and analyse in the same independent unit (player, user or device). The evidence gives the units a day that pass with even arrivals; allow more, because arrivals vary (design section 21.6: spiky arrivals need 1.5 to 3 times as much). Otherwise accept that the cohort check will not run: the other results checks are not affected.`
- info: `PRO-004` `Bucketing salt not declared`. What to do: `Set procedure.bucketing_salt to a value unique to this experiment, for example its id.`

## A stated size differs from Referee's

- `[SIZE_DIFFERS] stated.required_total_players: the draft states 20000 players; Referee's power plan for these inputs needs 16,412 players. Referee's figure is the one reported`

## Attempts

### Attempt 1 (`replay`)

0 blocker(s), 5 warning(s), 0 question(s).
- warning: `[RULE:DES-006] Interference between units is possible. Randomize at a level that contains the interaction (clusters of players), or set population.interference to none_expected and record why.`
- warning: `[RULE:DES-008] No pre-period covariate declared. Declare design.pre_period_covariate: the name of a column of the experiment's outcomes file that holds, for each player, a measure taken before the player's first exposure, for example the primary metric over the week before. The results review then shows the adjusted estimate, which is the registered analysis, beside the unadjusted one, and checks that the covariate is balanced across the arms. A measure taken after the treatment can act would remove part of the real effect.`
- warning: `[RULE:HYP-002] Primary metric has no governed reference. Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`
- warning: `[RULE:PRO-003] No guardrail metrics declared. Declare at least one guardrail with its harmful direction and a tolerance, for example a refund rate that must not rise by more than 10% relative.`
- warning: `[SIZE_DIFFERS] stated.required_total_players: the draft states 20000 players; Referee's power plan for these inputs needs 16,412 players. Referee's figure is the one reported`

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `08-stated-size-differs.md`: sha256 bb309f971da8cc9bc4928c181d6a7112694ad0f90a25ed177e2cb3876e1a9897, 925 bytes
- Specwright 0.1.0, Referee 0.1.0
- spec fingerprint: sha256:43cb04526ab00135229ae014109a543136061567c56c66fd4c00a40d5f783e8a
