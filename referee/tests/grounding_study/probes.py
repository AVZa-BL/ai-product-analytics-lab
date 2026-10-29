"""Hand-written harmful probes: a text, the sentences it cites and one line on why it is harmful.

Written by an agent in plain words, to be put to the checker; they are probes, not a sample of
anything, and the checker does not compute harm. The first group cites sentences that are free
once the list is cut to qualifiers and markers, and is built from their words; the second cites
sentences that are free only when it is cut to markers; the last holds a digit or a symbol, or
cites a sentence with a marker.
"""

from typing import NamedTuple


class Probe(NamedTuple):
    cited: tuple[str, ...]
    text: str
    harm: str


PROBES: tuple[Probe, ...] = (
    Probe(
        ("RES-012.do.1",),
        "Exposure is triggered.",
        "turns an instruction to check into a statement",
    ),
    Probe(
        ("RES-001.do.4",),
        "Rerun the experiment.",
        "drops the fix, so the same faulty experiment is rerun",
    ),
    Probe(
        ("RES-001.do.4",),
        "Fix the experiment and rerun the cause.",
        "swaps the objects of the two instructions",
    ),
    Probe(
        ("RES-013.title",),
        "The test changed the arm's configuration.",
        "adds a cause: the test, not a change made during it",
    ),
    Probe(
        ("RES-002.title",),
        "Players are the registered sample size.",
        "relates two numbers as equal where the title says fewer",
    ),
    Probe(
        ("RES-001.why.1",),
        "Random assignment gives arms of the registered sizes.",
        "drops 'up to chance', so the sizes read as exact",
    ),
    Probe(
        ("RES-007.do.1",),
        "Read the pooled effect before the table of cohorts in the evidence.",
        "reverses the order the advice sets",
    ),
    Probe(
        ("RES-012.title",),
        "Players were first exposed and their first purchase was after that.",
        "reverses the order of exposure and purchase",
    ),
    Probe(
        ("RES-007.why.1",),
        "The pooled effect is an average over players.",
        "drops 'first exposed at different times', which is why the average can mislead",
    ),
    Probe(
        ("RES-003.title",),
        "Ran for the registered minimum duration.",
        "drops 'less than', so a short run reads as one that met the minimum",
    ),
    Probe(
        ("RES-013.why.1",),
        "The arm is a second treatment.",
        "names the arm as the second treatment, where a change inside it is one",
    ),
    Probe(
        ("RES-003.why.1",),
        "The run gives effects that cover the weekly cycle.",
        "changes what covers the weekly cycle, the effects for the run",
    ),
    Probe(
        ("RES-001.do.1",),
        "Read the effect.",
        "reverses a negation: the instruction not to read the effect becomes one to read it",
    ),
    Probe(
        ("RES-002.do.3",), "Lower the registered n after seeing the data.", "reverses a negation"
    ),
    Probe(("RES-004.do.1",), "Decide on the primary metric alone.", "reverses a negation"),
    Probe(
        ("RES-001.why.3",),
        "The estimate of the effect can be trusted.",
        "drops 'no ... until the cause is known', so an untrusted estimate reads as trusted",
    ),
    Probe(
        ("RES-012.why.1",),
        "A purchase made before the player first saw the change is an effect of it.",
        "replaces 'cannot be' with 'is'",
    ),
    Probe(
        ("RES-004.why.6",),
        "A guardrail within its tolerance is a breach.",
        "hardens 'is not a finding' to a breach",
    ),
    Probe(
        ("RES-004.why.6",),
        "The data rule out a breach.",
        "softens 'cannot rule out a breach' to a clear guardrail",
    ),
    Probe(
        ("RES-013.do.2",),
        "Pool the versions and read a trend over weeks as novelty.",
        "reverses 'do not pool the versions and read a trend as novelty'",
    ),
    Probe(
        ("RES-011.do.2",),
        "Decide what to do with those weeks because leaving them out changes the result.",
        "turns 'never because' into the reason for the decision",
    ),
    Probe(
        ("RES-002.do.1",),
        "Keep the experiment running.",
        "drops the stopping condition, every arm at its registered n",
    ),
    Probe(
        ("RES-008.do.3",),
        "Call the result significant on one edge of this interval.",
        "reverses 'do not call the result significant on one edge'",
    ),
    Probe(
        ("RES-001.do.3",),
        "The mismatch began at a point in time.",
        "turns 'shows whether' into a fact about when it began",
    ),
    Probe(
        ("RES-013.do.3",),
        "The versions were randomised.",
        "reverses a negation: the versions were not randomised",
    ),
    Probe(
        ("RES-001.do.4", "RES-001.do.1"),
        "Fix the cause and read the effect.",
        "joins two sentences into advice to read the effect",
    ),
    Probe(
        ("RES-008.do.1",),
        "The interval is wrong in 10 percent of experiments.",
        "adds a number the sentence does not give",
    ),
    Probe(
        ("RES-008.why.6",),
        "A quiet rule is evidence that the interval is reliable.",
        "reverses the negation of a quiet rule, a reassurance",
    ),
)
