<!-- Synthetic design document, written by an agent for Specwright's examples. Not a real product or plan. -->
# Skyharbor: Season 4 design document

Version 0.7. Skyharbor is a free-to-play airship trading game with about 30,000 daily active
players. Season 4, "The Long Night", lasts 12 weeks and adds a night cycle, three new routes and a
rebuilt Season Pass screen. This document covers art, narrative, economy, interface and launch.

## 1. Art direction
The night cycle needs a new sky shader and lantern lighting on every harbor. Concept art is due in
week 2. The pass screen gets a darker palette; the reward icons are redrawn at 128 px. Animation
budget: 14 days of animator time for the lantern sway and the airship wake.

## 2. Narrative
Season 4 follows Captain Ilse Varga as she follows a lighthouse signal north. There are 9 story
chapters, one a week for 9 weeks, then three weeks of epilogue events. Writers target 400 words a
chapter. Voice work is out of scope for this season.

## 3. Economy
Trade routes pay out in coins; the three new routes pay 8%, 11% and 15% more than the old average
because they are longer. Coin sinks: hull upgrades, harbor fees and the lantern shop. We expect
coin income per player per day to rise by 5% and want the sinks to follow. The premium currency,
"stars", is unchanged. The Season Pass costs 9.99 USD and returns 40 reward tiers.

## 4. Interface
The home screen gets a night toggle. The route map is rebuilt for small phones, with larger tap
targets (48 px). The Season Pass screen moves from the third tab to the first and shows the next
three rewards instead of the whole track. Accessibility: every night colour pair must reach a
contrast ratio of 4.5.

## 5. Events and live-ops
A "Night Market" weekend event runs in weeks 4 and 8. Support will get a macro for lost voyages.
Community managers post patch notes on Tuesdays.

## 6. Technical
The night cycle is client-side only; there is no server change. Crash budget: no more than 0.4%
of sessions. Build size grows by 38 MB, which is acceptable on both stores.

## 7. Telemetry
New events: night_toggle, route_started, pass_screen_viewed, pass_purchased. See the tracking plan
for properties.

## 8. Rollout
The season ships on a Tuesday in all regions at once. A staged rollout was rejected: the stores
differ too much.

## 9. Launch experiments

### 9.1 Night toggle default
Not tested; the default is on.

### 9.2 Season Pass price test
We will test the price of the Season Pass. Control keeps the price at 9.99 USD. The variant,
called variant_a, lowers it to 7.99 USD. Players are assigned individually, 50/50, the first time
they see the pass screen, and the price is shown after assignment, so assignment cannot depend on
it. Only existing players are included, and players do not interact over the price.

The goal metric is the Season Pass purchase rate: the share of players who buy the pass within 14
days of first seeing the pass screen. In the last season it was 6.5%. We care about an 8%
relative lift. We use alpha 0.05, power 80% and a two-sided test. 6,000 players a day see
the pass screen for the first time. The test runs 28 days, and not less than 21 days.

Guardrail: the number of days a player is active in their first 14 days (6.4 days on average, with
a standard deviation of 3.9) must not fall by more than 3% relative.

Procedure: read once, at the end of the 28 days. Check the sample ratio daily. Owner: live-ops.

### 9.3 Route map tap targets
Observational only; no test.

## 10. Risks
The night cycle may reduce readability on bright outdoor screens. Mitigation: the toggle.
