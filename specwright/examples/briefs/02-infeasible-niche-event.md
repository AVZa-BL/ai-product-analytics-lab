<!-- Synthetic brief, written by an agent for Specwright's examples. Not a real product or plan. -->
# Lantern Quest: guild leader event reward

Lantern Quest is a small community game. Design wants to test a bigger reward in the Lantern
Festival event, offered to guild leaders only. Variant: the larger reward. Control: today's reward.

**Hypothesis.** A larger reward makes more guild leaders complete the event.

**Who.** Guild leaders who open the event page. 300 guild leaders open it each day. Assignment is
per player, 50/50, between control and variant_a, when they first open the page (before they see
the reward). Guild leaders in different guilds do not interact.

**Metric.** Event completion within 7 days of opening the page: 2% today. We only care to detect
a 5% relative improvement. Alpha 0.05, power 80%, two-sided.

**Schedule.** The festival lasts 14 days and we cannot extend it; the test must run for exactly
those 14 days, and no less than 7 days.

**Procedure.** Read once at the end. Check the sample ratio every day. Owner: community-design.
