<!-- Synthetic brief, written by an agent for Specwright's examples. Not a real product or plan. -->
# Frontier Forge: Starter Pack banner test

Frontier Forge is a mobile strategy game. Live-ops wants to know whether showing the Starter Pack
banner at the top of the shop, instead of the current rotating banner, makes more players buy.

**Hypothesis.** With the Starter Pack banner first, more players make a purchase within 7 days of
first opening the shop than with the current banner. The current banner is the control.

**Who.** Existing players who open the shop. Assignment is per player, 50/50 between the control and
one variant, called variant_a. A player is counted when they first open the shop, before they see
either banner. Players do not affect each other's banners.

**Traffic.** 12,000 players a day open the shop for the first time in the test window. The
test runs for 3 weeks (21 days), and not less than 14 days in any case, because weekends differ.

**Primary metric.** Purchase conversion: the share of players who make at least one purchase in
the 7 days after they first open the shop. Today it is 4.2%. We care about a 10% relative lift
(4.2% to 4.62%). Alpha 0.05, power 80%, two-sided test.

**Guardrail.** Day-1 retention (38% today) must not fall by more than 5% relative.

**Procedure.** The result is read once, at the end of the 21 days. The sample ratio is checked
every day. The test belongs to the monetisation-analytics team.
