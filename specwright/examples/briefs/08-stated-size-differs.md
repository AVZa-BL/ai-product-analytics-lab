<!-- Synthetic brief, written by an agent for Specwright's examples. Not a real product or plan. -->
# Gloomwood: dungeon difficulty tweak

Design lowered the damage of the first dungeon's boss. We want to test whether this makes more
players clear the dungeon.

**Hypothesis.** The lower damage makes more players clear the first dungeon within 7 days of
entering it. Control keeps the old damage; variant_a has the lower damage. Assignment is per
player, 50/50, when a player first enters the dungeon.

**Who.** Existing players. 4,000 players enter the dungeon for the first time each day.

**Metric.** Dungeon clear rate within 7 days: 35% today; we want to detect a 6% relative lift.
Alpha 0.05, power 80%, two-sided. A colleague worked out that we need 20,000 players in total.

**Schedule.** 14 days, and no less than 14 days.

**Procedure.** Read once at the end. Check the sample ratio daily. Owner: dungeon-design.
