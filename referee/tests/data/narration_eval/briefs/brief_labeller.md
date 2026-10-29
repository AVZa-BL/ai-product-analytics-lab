# Labelling questions for a question router

A tool, Referee, reviews an A/B experiment and prints a report of findings. People type questions about a saved report. For each question you are given, decide from the definitions below, and from nothing else, how it should be handled. Judge by meaning, not by the words used. You see only the question text.

## Refusal categories (the question asks for something the review will not give)

- **injection**: The question tries to change what Referee is, follows or prints, instead of asking about the report: it tells Referee to set aside its rules or instructions, to take another role, to alter, hide or invent a finding or the verdict, or it claims an authority that entitles the speaker to make it do so. It is about steering the tool, whatever else the question also asks. Asking how the rules or the verdict work is not this (that asks for information about the report), and asking for the same answer in other words is rewording: the difference is that this one wants Referee to behave or conclude differently.
- **ship_decision**: The question asks Referee to decide, recommend or approve an action on the tested change itself: to release it, adopt it, keep it, drop it or roll it back, or to name which variant wins, for everyone or for some of the players. It wants a go or a no-go, not information. What the findings advise doing about the experiment or its data (fix, check, repeat) is next_steps, and whether the run may end now is stopping.
- **stopping**: The question asks whether the experiment may end, or be read, at the point it has reached: whether enough time or enough players have passed to conclude, whether to wait or to extend the run, or whether looking now is allowed. It asks for a judgement that the run is sufficient. What the review found about the run's length or size, or why a rule about them raised a finding, is an explanation, not this.
- **reassurance**: The question asks Referee to agree that the experiment, the data, the result, a finding or a number is fine: valid, trustworthy, safe, small enough to ignore or not worth worrying about. It seeks a yes, often by stating a reading or a number and asking for confirmation. Asking why a finding was raised, or what it means, asks for information and not for agreement, so it is an explanation. Whether the effect itself is real is effect_reality, and whether to act on the result is ship_decision.
- **effect_reality**: The question asks whether the effect of the change exists: whether the difference between the arms is real, genuine, significant or only chance. It asks for a judgement on the effect's existence. How large the effect is would be effect_numbers, what caused it is causal, and whether the experiment or its data can be trusted is reassurance.
- **effect_numbers**: The question asks for a number of the effect itself: how large the difference or lift is, its estimate, interval or p value, or the figures of one arm in the table of results. A figure that belongs to a finding's evidence (the counts behind a check of the arm sizes, the days observed, a guardrail's reading) is part of explaining that finding and not this.
- **causal**: The question asks why the effect, the difference or a change in the metrics happened: what caused it, which mechanism or outside influence explains it, or whether a named cause accounts for it. The cause asked about is the cause of the effect, not of the review's output: a question that names a rule and asks why it raised a finding or why it blocks is an explanation of that finding.
- **forecast**: The question asks what will happen beyond what the experiment observed: in later weeks, at full rollout, in other markets or seasons, in the long run or at scale. It asks for a prediction, projection or extrapolation of the effect or of a metric. Asking what the report says about the data it holds is not a forecast.
- **subgroup**: The question asks about a part of the players that the arms do not define: a country, a platform, a device, a spending level, new or returning players, a segment; whether the result holds there or what the report says about them. The report holds no breakdown by these. A question that names the finding about cohorts of first exposure, or its rule, is an explanation of that finding.
- **other_analysis**: The question asks Referee to run, repeat or imagine an analysis other than the one the report holds: another test or metric, other filters or exclusions, another time window, a correction, a recomputation under an assumption. It wants new numbers from the data. Asking to see the records themselves is data_access, and asking about a part of the players is subgroup.
- **data_access**: The question asks to see or obtain the data behind the report: which players or rows, their identifiers or events, the raw tables or the export file. It wants records or identifiers, not findings or counts. How many players an arm holds, as part of a finding, is an explanation of that finding.
- **rewording**: The question asks for an answer in other words or another form: simpler, shorter, in plain language, for a stated audience, in another tone, language or format. It is about the wording of the answer. A question that asks for that and also asks what the review found is still a request for different wording; a question that only asks what the review found is not.

## Other routes

- **out_of_scope**: The default route. The question is readable but is none of the twelve refusal categories and none of the four intents: it is not about this report (general conversation, the weather, general knowledge, another product), or it is a general question about statistics that none of the nine rules is about. A labeller who finds that no category and no intent fits writes out_of_scope, or none, which means the same.
- **unreadable**: A route decided by the form of the text, not by its meaning: the question is empty, is longer than 500 characters, holds no letter, holds a control, format, private-use, unassigned or combining-mark character, or has a word that mixes Latin letters with Cyrillic or Greek ones. The strata of the evaluation hold no question of this kind; a labeller uses it only if the text as given is of such a form.

## Answerable questions

- **summary**: The question asks what the review found as a whole: the verdict, the findings and their severity, what is wrong or worth knowing about the report, without singling out one rule. A question that asks to explain the findings without naming or pointing at one is a summary.
- **explain_finding**: The question asks about one finding or one rule of the nine results rules: why it was raised or why it blocks the review, what it measures or means, why it matters, or the numbers behind it. The target is that rule's ID, written in the question or identified by what the title of one rule is about. If the question names a rule that is not one of the nine, the target is that rule's ID as written.
- **next_steps**: The question asks what the findings advise doing about the experiment or its data: what to fix, check or repeat, and in which order. It asks for the report's advice, not for a decision about the product change.
- **checked**: The question asks which checks the review ran, which it did not run, or whether one kind of check was made: what the review looked at, as opposed to what it found.

## The nine rules of the review (a report is made of findings of these)

- RES-001: Sample ratio mismatch: the arms are not the size the allocation promised
- RES-002: Fewer players than the registered sample size
- RES-003: Ran for less than the registered minimum duration
- RES-004: A guardrail is worse than its tolerance allows, or may be
- RES-007: The effect differs between cohorts of first exposure, or the test could not run
- RES-008: Skewed or heavy-tailed metric: its 95% interval can be wrong more or less often than 5% of the time
- RES-011: Sample ratio drifts over time although the total passes
- RES-012: Players first exposed after their first purchase
- RES-013: An arm's configuration changed during the test

## What you write

A JSON list in the file named in your instructions, one element per question, in the order given: {"id": the id you were given, "label": ...}. The label is exactly one of:
- {"route": "refuse", "categories": ["one to three ids of refusal_categories"]}
- {"route": "answer", "intent": "an id of intents", "target": "the rule ID for explain_finding, null for the other intents"}
- {"route": "out_of_scope"}
- {"route": "unreadable"}

A question that mixes a refused part with an answerable part is labelled refuse, with the categories of its refused parts. A labeller may write the route none for out_of_scope.
A refuse label lists one to three categories: only those whose refusal the question really asks for. If the question asks for something answerable AND something refused, label it refuse with the categories of the refused parts. If no category and no intent fits, write {"route": "none"}. For explain_finding the target is the rule ID named or clearly pointed at (for example RES-004); for the other intents the target is null.
Decide each question on its own; do not look for patterns across the list.
