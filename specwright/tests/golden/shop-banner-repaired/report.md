# Specwright draft: ok

OK: a spec was built and Referee's design rules raise no blocker.

> Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
> A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.

Documents: `01-shop-banner.md`. Attempts: 2 (1 repair round(s)).

## Computed by Referee (the power plan)

- needs 75,026 players in total (`control` 37,513, `variant_a` 37,513), 7 days at the daily traffic stated (7 days to whole weeks)
- the planned duration delivers 252,000 players
- the smallest relative effect that duration can power: 5.4%
- powered: yes

## What the draft states

- `id` = `shop_banner_starter_pack` - inferred
- `title` = `Starter Pack banner first in the shop` - inferred
- `owner` = `monetisation-analytics` - quoted from `01-shop-banner.md`: `The test belongs to the monetisation-analytics team.`
- `hypothesis.null` = `Showing the Starter Pack banner first does not change the share of players who buy within 7 days of opening the shop.` - inferred
- `hypothesis.alternative` = `The Starter Pack banner first makes more players buy within 7 days.` - quoted from `01-shop-banner.md`: `more players make a purchase within 7 days of first opening the shop`
- `hypothesis.direction` = `increase` - inferred
- `population.randomization_unit` = `player` - quoted from `01-shop-banner.md`: `Assignment is per player, 50/50`
- `population.analysis_unit` = `player` - inferred
- `population.eligibility` = `Existing players who open the shop.` - quoted from `01-shop-banner.md`: `Existing players who open the shop.`
- `population.exposure_trigger` = `first opening of the shop` - quoted from `01-shop-banner.md`: `A player is counted when they first open the shop`
- `population.exposure_timing` = `pre_treatment` - quoted from `01-shop-banner.md`: `before they see either banner`
- `population.interference` = `none_expected` - quoted from `01-shop-banner.md`: `Players do not affect each other's banners.`
- `population.kind` = `existing_users` - quoted from `01-shop-banner.md`: `Existing players who open the shop.`
- `population.daily_eligible_units` = `12000` - quoted from `01-shop-banner.md`: `12,000 players a day open the shop for the first time`
- `arms[0].name` = `control` - quoted from `01-shop-banner.md`: `The current banner is the control.`
- `arms[0].allocation` = `0.5` - quoted from `01-shop-banner.md`: `Assignment is per player, 50/50`
- `arms[0].is_control` = `True` - quoted from `01-shop-banner.md`: `The current banner is the control.`
- `arms[1].name` = `variant_a` - quoted from `01-shop-banner.md`: `one variant, called variant_a`
- `arms[1].allocation` = `0.5` - quoted from `01-shop-banner.md`: `Assignment is per player, 50/50`
- `arms[1].is_control` = `False` - inferred
- `primary_metric.name` = `purchase_conversion_7d` - inferred
- `primary_metric.kind` = `binary` - quoted from `01-shop-banner.md`: `the share of players who make at least one purchase in`
- `primary_metric.baseline` = `0.042` - quoted from `01-shop-banner.md`: `Today it is 4.2%.`
- `guardrails[0].name` = `day1_retention` - inferred
- `guardrails[0].kind` = `binary` - quoted from `01-shop-banner.md`: `Day-1 retention (38% today)`
- `guardrails[0].baseline` = `0.38` - quoted from `01-shop-banner.md`: `Day-1 retention (38% today)`
- `guardrails[0].harmful_direction` = `decrease` - quoted from `01-shop-banner.md`: `must not fall by more than 5% relative`
- `guardrails[0].tolerance_relative` = `0.05` - quoted from `01-shop-banner.md`: `must not fall by more than 5% relative`
- `design.mde_relative` = `0.1` - quoted from `01-shop-banner.md`: `We care about a 10% relative lift`
- `design.alpha` = `0.05` - quoted from `01-shop-banner.md`: `Alpha 0.05, power 80%, two-sided test`
- `design.power` = `0.8` - quoted from `01-shop-banner.md`: `Alpha 0.05, power 80%, two-sided test`
- `design.sided` = `two_sided` - quoted from `01-shop-banner.md`: `two-sided test`
- `design.planned_duration_days` = `21` - quoted from `01-shop-banner.md`: `The test runs for 3 weeks (21 days)`
- `design.min_duration_days` = `14` - quoted from `01-shop-banner.md`: `not less than 14 days in any case`
- `procedure.stopping_rule` = `fixed_horizon` - quoted from `01-shop-banner.md`: `The result is read once, at the end of the 21 days.`
- `procedure.srm_check_cadence` = `daily` - quoted from `01-shop-banner.md`: `The sample ratio is checked`

## Inferred values to confirm

- `id` = `shop_banner_starter_pack`
- `title` = `Starter Pack banner first in the shop`
- `hypothesis.null` = `Showing the Starter Pack banner first does not change the share of players who buy within 7 days of opening the shop.`
- `hypothesis.direction` = `increase`
- `population.analysis_unit` = `player`
- `arms[1].is_control` = `False`
- `primary_metric.name` = `purchase_conversion_7d`
- `guardrails[0].name` = `day1_retention`

## Design review (Referee's HYP, DES and PRO rules)

- warning: `DES-008` `No pre-period covariate declared`. What to do: `Declare design.pre_period_covariate: the name of a column of the experiment's outcomes file that holds, for each player, a measure taken before the player's first exposure, for example the primary metric over the week before. The results review then shows the adjusted estimate, which is the registered analysis, beside the unadjusted one, and checks that the covariate is balanced across the arms. A measure taken after the treatment can act would remove part of the real effect.`
- warning: `HYP-002` `Primary metric has no governed reference`. What to do: `Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`
- info: `PRO-004` `Bucketing salt not declared`. What to do: `Set procedure.bucketing_salt to a value unique to this experiment, for example its id.`

## Attempts

### Attempt 1 (`replay`)

4 blocker(s), 0 warning(s), 1 question(s).
- blocker: `[QUOTE_NOT_FOUND] design.mde_relative: the quote 'We want a ten percent lift in purchases' is not in '01-shop-banner.md'; quote the document exactly (at least 8 characters), or label the claim inferred, missing or ambiguous`
- blocker: `[NUMBER_NOT_IN_QUOTE] design.mde_relative: the value 0.1 is not written in the quote 'We want a ten percent lift in purchases': quote the sentence that gives the number, or label the claim inferred (a number in words, or one you worked out, is inferred)`
- blocker: `[NUMBER_NOT_IN_QUOTE] design.min_duration_days: the value 14 is not written in the quote 'The test runs for 3 weeks': quote the sentence that gives the number, or label the claim inferred (a number in words, or one you worked out, is inferred)`
- blocker: `[FIELD_OMITTED] design.alpha: a required field has no claim: state it, or label it missing (value null, with a note saying what to ask)`

Sent back to the model: 4 problem(s).

### Attempt 2 (`replay`)

0 blocker(s), 2 warning(s), 0 question(s).
- warning: `[RULE:DES-008] No pre-period covariate declared. Declare design.pre_period_covariate: the name of a column of the experiment's outcomes file that holds, for each player, a measure taken before the player's first exposure, for example the primary metric over the week before. The results review then shows the adjusted estimate, which is the registered analysis, beside the unadjusted one, and checks that the covariate is balanced across the arms. A measure taken after the treatment can act would remove part of the real effect.`
- warning: `[RULE:HYP-002] Primary metric has no governed reference. Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file.`

Nothing sent back.

## What this does not tell you

- Passing these checks proves the draft is consistent with the documents and with Referee's design rules. It does not prove the experiment is well designed.
- A quote that is found proves the words are in the document, not that the model read them correctly. Check each claim against its quote.
- A value labelled inferred comes from the model's judgement and not from a document: confirm each one. A vague phrase that the model chose not to quote cannot be detected.
- Sample sizes and durations are worked out by Referee's power plan from the stated numbers, never by the model.

## Provenance

- `01-shop-banner.md`: sha256 f02b67b7158c69708367b7c95b485299b13d2833c53700ed24218444226c3497, 1,465 bytes
- Specwright 0.1.0, Referee 0.1.0
- spec fingerprint: sha256:4cff528463e3a7f697117d308a17435748b9482a3fcc0e1e7773538e19bf2587
