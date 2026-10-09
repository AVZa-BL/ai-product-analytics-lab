# Tracking proposal: Alliance Treasure Hunt

**Status: OK**, no blocking problem remains (after 1 repair round). Tracewright advises; a person decides.

A 72-hour weekly alliance event: members earn Map Fragments from battles and daily quests, exchange ten fragments for a Treasure Chest, and unlock shared milestone rewards at 100, 250 and 500 opened chests. The design sets three measurable criteria: 40% of eligible alliances start a hunt, non-participants' day-7 retention does not drop, and Fragment Packs stay below 15% of fragments earned.

| New events | Extended | Reused | Metrics | Open questions |
| --- | --- | --- | --- | --- |
| 6 | 1 | 5 | 6 | 3 |

Evidence for 7 event(s): 6 quoted from the documents and found, 0 quoted but not found, 0 from a PDF (not machine-checked), 1 the analyst's judgement. A found quote shows the words are in the document, not that the event is the right one.

## New events

### `treasure_hunt_started` (must)

- **What it is:** An alliance leader starts a Treasure Hunt for the alliance.
- **Sent when:** The server confirms the 500 Ember Coins entry cost was taken from the alliance vault and the hunt is created.
- **Why:** The start is the numerator of the first success criterion (40% of eligible alliances start a hunt) and the anchor for every other hunt event.
- **Evidence** (gdd.md; quote found in the document):

> An alliance leader starts a hunt by paying an entry cost of 500 Ember Coins from the alliance vault.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `player_id` | string | yes | no | reused | Opaque id of the acting player. Ties the event to a player, as on every existing event. |
| `alliance_id` | string | yes | no | reused | Opaque id of the alliance. Lets every hunt metric be cut by alliance; same name and type as in alliance_joined. |
| `hunt_id` | string | yes | no | new | Id of one hunt of one alliance. Joins all events of a hunt together; a hunt is the unit the success criteria are measured on. |
| `alliance_size` | integer | yes | no | reused | Members of the alliance at the start. Eligibility is five members or more; the size also explains differences in progress speed. |
| `entry_cost` | integer | yes | no | new | Ember Coins paid from the vault. Keeps the metric valid if the entry cost is ever changed or tested. |

### `map_fragment_earned` (must)

- **What it is:** A player receives Map Fragments.
- **Sent when:** The server credits Map Fragments to the player.
- **Why:** Fragment inflow shows participation and pace, and its split by source gives the Fragment Pack share (below 15%) directly.
- **Evidence** (gdd.md; quote found in the document):

> Members earn Map Fragments from battles and daily quests.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `player_id` | string | yes | no | reused | Opaque id of the acting player. Ties the event to a player, as on every existing event. |
| `hunt_id` | string | yes | no | new | Id of one hunt of one alliance. Joins all events of a hunt together; a hunt is the unit the success criteria are measured on. |
| `source` | enum: battle, daily_quest, pack | yes | no | new | Where the fragments came from. The Fragment Pack criterion is the share of fragments with source pack. |
| `fragment_amount` | integer | yes | no | new | Fragments credited. Pace of the hunt and size of each source. |

### `treasure_chest_opened` (must)

- **What it is:** A player exchanges ten Map Fragments and opens a Treasure Chest.
- **Sent when:** The chest-opening animation completes and the reward is granted.
- **Why:** Chests opened drive the milestones and show how far each hunt gets. Tier and reward show what the event adds to the economy.
- **Evidence** (gdd.md; quote found in the document):

> Ten Map Fragments can be exchanged for one Treasure Chest.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `player_id` | string | yes | no | reused | Opaque id of the acting player. Ties the event to a player, as on every existing event. |
| `hunt_id` | string | yes | no | new | Id of one hunt of one alliance. Joins all events of a hunt together; a hunt is the unit the success criteria are measured on. |
| `chest_tier` | enum: bronze, silver, gold | yes | no | new | Tier of the chest. Tier depends on alliance rank, so it is the economy lever to monitor. |
| `reward_type` | enum: ember_coins, gems, speedups, hero_shards | yes | no | new | What the chest contained. Shows which currencies the event injects into the economy. |
| `reward_amount` | integer | yes | no | new | Whole units of the reward. Size of the economy injection. |

### `treasure_hunt_screen_viewed` (should)

- **What it is:** A player opens the hunt screen.
- **Sent when:** The hunt screen is shown to the player.
- **Why:** The first success criterion needs a denominator: how many eligible alliances were exposed to the event and did not start. Views by leaders versus other members show whether leaders found the feature.
- **Evidence:** analyst's judgement, not from the documents.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `player_id` | string | yes | no | reused | Opaque id of the acting player. Ties the event to a player, as on every existing event. |
| `alliance_id` | string | yes | no | reused | Opaque id of the alliance. Lets every hunt metric be cut by alliance; same name and type as in alliance_joined. |
| `is_leader` | boolean | yes | no | new | Whether the viewer is the alliance leader. Only leaders can start a hunt, so views are read separately for them. |
| `hunt_active` | boolean | yes | no | new | Whether the alliance has a running hunt. Separates browsing a running hunt from looking at the start option. |

### `treasure_milestone_reached` (should)

- **What it is:** An alliance reaches a chest milestone.
- **Sent when:** The server records the 100th, 250th or 500th opened chest of the hunt.
- **Why:** Milestones are the event's shared goal; reaching them is the completion measure of a hunt and the moment the milestone push goes out.
- **Evidence** (gdd.md; quote found in the document):

> When the alliance reaches 100, 250 and 500 opened chests, every member receives a milestone reward.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `player_id` | string | yes | no | reused | Opaque id of the acting player. Ties the event to a player, as on every existing event. |
| `alliance_id` | string | yes | no | reused | Opaque id of the alliance. Lets every hunt metric be cut by alliance; same name and type as in alliance_joined. |
| `hunt_id` | string | yes | no | new | Id of one hunt of one alliance. Joins all events of a hunt together; a hunt is the unit the success criteria are measured on. |
| `milestone` | integer | yes | no | new | Chest count of the milestone: 100, 250 or 500. Separates the three completion levels. |

### `treasure_share_forfeited` (could)

- **What it is:** A member loses their share of a milestone reward by leaving the alliance early.
- **Sent when:** The server withholds a milestone reward because the member left within two hours of the milestone.
- **Why:** Shows whether the forfeit rule is hit often, which would signal friction or abuse; alliance_left alone cannot tell when the leave cost a reward.
- **Evidence** (gdd.md; quote found in the document):

> Members who leave the alliance within two hours of a milestone forfeit their share of that milestone reward.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `player_id` | string | yes | no | reused | Opaque id of the acting player. Ties the event to a player, as on every existing event. |
| `alliance_id` | string | yes | no | reused | Opaque id of the alliance. Lets every hunt metric be cut by alliance; same name and type as in alliance_joined. |
| `hunt_id` | string | yes | no | new | Id of one hunt of one alliance. Joins all events of a hunt together; a hunt is the unit the success criteria are measured on. |
| `milestone` | integer | yes | no | new | Milestone whose reward was forfeited. Which milestone members leave around. |

## Existing events to extend

### `purchase_completed`

- **Why:** Fragment Pack revenue has to be separable from other purchases, and tied to a hunt, to read the monetisation side of the event.
- **Evidence** (gdd.md; quote found in the document):

> Players can buy Fragment Packs for real money, limited to three per day.

| Property | Type | Required | PII | Existing | Why it is needed |
| --- | --- | --- | --- | --- | --- |
| `hunt_id` | string | no | no | new | Hunt the purchase was made for; empty for other purchases. Links a purchase to a hunt so pack revenue and pack share can be computed per hunt. |

## Existing events that already cover part of the feature

- `currency_spent`: The entry cost is an Ember Coins sink and is already captured here. Agree the sink value treasure_hunt_entry so it can be filtered.
- `alliance_left`: Needed to read the early-leave rule together with treasure_share_forfeited; no change required.
- `push_opened`: Opens of the milestone push are already captured with campaign_id. Agree a campaign id for hunt milestones.
- `alliance_joined`: Gives alliance size over time, which defines which alliances are eligible.
- `session_started`: Day-7 retention of non-participants is read from sessions; no change required.

## Metrics this tracking makes possible

- **hunt_start_rate_eligible_alliances**: Share of alliances with five or more members that start a hunt in the first month. Needs: `treasure_hunt_screen_viewed`, `treasure_hunt_started`, `alliance_joined`. Why: First success criterion (40%).
- **hunt_funnel**: Per hunt: started, fragments earned, chests opened, milestones reached. Needs: `treasure_hunt_started`, `map_fragment_earned`, `treasure_chest_opened`, `treasure_milestone_reached`. Why: Shows where hunts stall.
- **fragment_pack_share**: Fragments earned from packs divided by all fragments earned. Needs: `map_fragment_earned`, `purchase_completed`. Why: Third success criterion (below 15%).
- **non_participant_d7_retention**: Day-7 retention of players in eligible alliances who earned no fragments, against a comparable baseline. Needs: `session_started`, `map_fragment_earned`, `treasure_chest_opened`. Why: Second success criterion: the event must not hurt players who skip it.
- **early_leave_forfeit_rate**: Forfeited shares divided by milestone rewards granted. Needs: `treasure_share_forfeited`, `treasure_milestone_reached`, `alliance_left`. Why: Checks the leave rule for friction and abuse.
- **event_economy_injection**: Currency granted by chests per hunt, against the entry cost sink. Needs: `treasure_chest_opened`, `currency_spent`. Why: Economy health.

## Deliberately not tracked

- One event per Map Fragment drop inside battles.: High volume and no extra question answered: fragments are summed per source in map_fragment_earned.
- Individual items inside a chest.: reward_type and reward_amount answer the economy question without a new event per item.
- Views of the member contribution list.: The design leaves its visibility undecided; add it when the question exists.

## Assumptions the proposal makes

- hunt_id is generated by the server when the hunt is created and is stable for its 72 hours.
- Only one hunt can run per alliance at a time, as the document states, so hunt_id is unique per alliance and week.
- Ember Coins corresponds to the value ember_coins of currency_spent.currency.

## Questions the documents do not answer

- Should chest contents be allowed to raise battle power? If yes, battle_finished needs a chest-bonus property.
- What exactly makes an alliance eligible on Monday (member count at unlock, or at start)?
- In which time zone does the Monday unlock happen? It decides how days are cut in the funnel.

## Automatic checks

No problems found in the proposal.

The existing plan already has 1 finding(s) from `tracewright review-plan` (0 blocker, 1 warning, 0 info). They are not counted against this proposal, unless the proposal changes a finding, in which case that finding is shown whole. The merged plan was reviewed as if the feature had shipped.

`merged-plan.yaml` marks the new events `planned`, because they have not shipped. Running `tracewright review-plan merged-plan.yaml` therefore also reports COV-003 (warning: a metric depends on a planned event) for the new metrics. That is expected; it clears when you set those events to `active` at release.

## Provenance

- Document `gdd.md`: text, 1,804 bytes, sha256 `d4cd0631b6fdb4f3cbdd186a95b7fc69bc035e419a2adb98e4240652e4f92a1b`
- Existing plan `realm_of_ember_core`: sha256 `719c80fe791f7f213b69ec51ac28cbfa7a9a2b2c3a9332922207afb6a9f7338f`
- Attempts: 2 (repairs: 1); model: replay; Tracewright 0.1.0
- **This proposal was replayed from a saved file. No model produced it in this run.**
- A model wrote this proposal, so it can be wrong in ways the automatic checks cannot see. Read the reasoning, not only the event list.
