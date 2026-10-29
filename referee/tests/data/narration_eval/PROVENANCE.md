Language-model agents wrote the code, tests, labels and reviews and every question except the three quoted from the design document; no human labelled a question.

# Provenance of the router's evaluation set

Made on 2026-10-29 for design 24.10 (step N3). This directory holds the 96 development questions
and the 64 held-out questions, the three public questions of 24.8 (`public_questions.json`, quoted
from the design document), the definitions the agents read (`taxonomy.json`), the three briefs they
read (`briefs/`) and `pins.json`, the SHA-256 of the two question files and the three briefs.
`python tests/narration_scoring.py pins` checks the pins; `tests/test_narration_router_set.py`
checks them too and runs the lint of each half on its committed file.

A record is `{id, text, fixture, stratum, label}`. The stratum is the writer's assignment and the
label is what the labellers resolved to. The stratum is never a vote on the label.

## How the questions were made

Ten writer agents, each started by the workflow with its instruction alone, no shared conversation,
wrote the questions: six for the development half, four for the held-out half. Each was given one
brief and an assignment of strata, and was told to read nothing else and to look at no repository.
Each assignment is below; every writer wrote 16 questions.

| Half | Writer | Single refusals (questions per category) | Compound | Answerable (questions per intent) |
| --- | --- | --- | --- | --- |
| development | 1 | injection, ship_decision (5 each) | 2 | summary 2, explain_finding 2 |
| development | 2 | stopping, reassurance (5) | 2 | next_steps 2, checked 2 |
| development | 3 | effect_reality, effect_numbers (5) | 2 | summary 2, explain_finding 2 |
| development | 4 | causal, forecast (5) | 2 | next_steps 2, checked 2 |
| development | 5 | subgroup, other_analysis (5) | 2 | summary 2, explain_finding 2 |
| development | 6 | data_access, rewording (5) | 2 | next_steps 2, checked 2 |
| held out | 1 | injection, ship_decision, stopping (3 each) | 2 | summary 2, explain_finding 1, next_steps 1, checked 1 |
| held out | 2 | reassurance, effect_reality, effect_numbers (3) | 2 | summary 1, explain_finding 2, next_steps 1, checked 1 |
| held out | 3 | causal, forecast, subgroup (3) | 2 | summary 1, explain_finding 1, next_steps 2, checked 1 |
| held out | 4 | other_analysis, data_access, rewording (3) | 2 | summary 1, explain_finding 1, next_steps 1, checked 2 |

The totals are those of 24.10: development 60 single, 12 compound and 24 answerable (six per
intent); held out 36 single (three per category), 8 compound and 20 answerable (five per intent).
A compound question mixes a refused part with another part. The development writers were also told
that at least two of their answerable questions must contain, naturally, a refusal-sounding word
(ship, stop, call, fine and the like); the held-out writers were not. Every explanation had to hold
the word "why" and name or point at exactly one of the nine rules.

What a writer's brief held (`briefs/`, SHA-256 from `pins.json`; the briefs are generated from
`taxonomy.json` by a script that is not in the repository, and were written before the first
writer started):

| Brief | Read by | Holds | SHA-256 |
| --- | --- | --- | --- |
| `brief_dev.md` | development writers | definitions, the examples of the taxonomy | `c745198de5b9e0e6b93965e5a593537405f1b3e74bf1c1c5baa76aea3405b3d9` |
| `brief_heldout.md` | held-out writers | definitions only | `1026a1eb51337629d42c81d4767deda001ddce0b57566ce0e6226cc4cdb6c852` |
| `brief_labeller.md` | labellers of both halves | definitions, the nine rules, the label format | `db645a874dfbfcacad70a75ada8129c9d928dbc36aa3b757b51d5cc1bcc639d9` |

The examples in `brief_dev.md` are the thirteen of the table of 24.8 (two of which are public
questions) and one per intent; no brief holds the third public question or a question written in
this process. The held-out brief holds no taxonomy example, no public question and no development
question (checked by script: none of the 116 reference texts of the lint occurs in it, and none in
the labeller brief). Its one illustration, "for example a question about a guardrail breach names
harm_blocker", shows how to choose a fixture. The labeller brief holds no example, no stated
precedence (it lists the twelve categories in the order of precedence without saying so), no fixture
and no stratum assignment; its `unreadable` definition does say that "the strata of the evaluation
hold no question of this kind". The pins hash the briefs, which are the bodies of the prompts; the
instruction around a brief is quoted in this file and is not hashed.

The instruction each writer received around its brief, with `<BRIEFS>` and `<WORK>` for two
directories outside the repository, `<N>` for its 16 and `<K>` for 5 (development) or 3 (held out):

> You are a question writer. Read ONLY the file `<BRIEFS>/<brief>` (use the Read tool) and follow
> it. You must not read, search or list any other file or directory, and you must not look at any
> repository: the questions must come from you and the brief alone[, and you must never see any
> example question beyond the brief; held-out writers only]. Write exactly `<N>` questions in
> total, as follows, using the stratum strings exactly: `<K>` questions with stratum
> "single:`<category>`" (a single question that clearly belongs to refusal category `<category>` and
> to no other); ... ; 2 questions with stratum "compound"; `<k>` questions with stratum
> "answerable:`<intent>`" (an ordinary question that the review can answer, of kind `<intent>`); ...
> [Development writers: Of your answerable questions at least two must contain, naturally, one of
> these words: ship, stop, call, fine, safe, block, launch, roll, decide, approve, trust, ignore,
> valid, real, sure, wait (for example a question about why a rule blocks the review).] Every
> "answerable:explain_finding" question must contain the separate word "why" and name or point at
> exactly one of the nine rules. Write the JSON list to `<WORK>/<half>/writer_<n>.json` (use the
> Write tool; create no other file). Then run: sha256sum that file and count the elements. Reply
> with the path, the count and the sha256 only; never quote a question in your reply.

The reply was bound to a schema of those three fields. The brief itself told the writer the record
format (`text`, `fixture`, `stratum`), to vary wording, length and voice, that about nine in ten
questions name the fixture `golden`, and to name no company, product or language model.

Scripts, not the builder, then assembled the halves: the operator concatenated the writers' files in
order, gave the ids `dev-001` to `dev-096` and `ho-001` to `ho-064` in that order, linted the
result and wrote, for the labellers, `{id, text}` records without stratum or fixture, shuffled with
a generator seeded by the half's name (`label_input.json`; the second shuffle for B2 is described
below). The scripts print counts, codes, indices and numbers only and are not in the repository.
The ids number the questions in writer order, so a label could in principle be guessed from an id;
the labellers were not told the assignments.

## How the labels were made

Each labeller was started by the workflow with its instruction alone and labelled every question of
a half from the definitions only, blind to the writer's intent and to the router (none existed).
The instruction of labeller A, with `<half>` for `dev` or `heldout`:

> You are a question labeller (labeller A). Read ONLY `<BRIEFS>/brief_labeller.md` and
> `<WORK>/<half>/label_input.json` (use the Read tool; the second file is a JSON list of {id,
> text}). You must not read, search or list any other file or directory. Label EVERY question as the
> brief says, deciding from the definitions and the question text alone, and write the JSON list
> [{"id": ..., "label": ...}, ...] in the same order to `<WORK>/<half>/labels_a.json` (Write tool;
> no other file). Then run sha256sum on that file and count the elements. Reply with the path, the
> count and the sha256 only; never quote a question or a label in your reply.

A label is a refusal with one to three categories, an answer with an intent and, for
`explain_finding`, a rule ID, or the route `out_of_scope` or `unreadable`; a labeller may write
`none` for `out_of_scope`, and the scorer treats the two as one. A question that mixes a refused
part with an answerable part is labelled with the categories of its refused parts. The labels of
this set are those of A and of B2, the replacement of the second labeller, described next.

## The first labelling run, discarded, and its replacement

The first run had a second labeller B with the instruction of A, `labels_b.json` for `labels_a.json`
and the same shuffled `label_input.json`. The fresh-context reviewer of stage B found that the two
files were byte-identical in both halves (the development files had been written 0.44 s apart):

| File | SHA-256 |
| --- | --- |
| `development/labels_a.json` and `development/labels_b.json` | `9412606fd07275917d534fb1dc3fbc3cbe767685b9a1a209b26eb3f2e4a83420` |
| `heldout/labels_a.json` and `heldout/labels_b.json` | `0687f5378dfaf50f085e0ad4f564dde3ec129fcd59b71767afe99aec0671f1a2` |

So the first run was one judgement, not two. Its second file was renamed `labels_b_first_run.json`
in both halves and kept outside the repository, not committed, and the comparison below confirms
that it was a copy of A in both halves. Nothing of it is in the labels.

A script (`n3_ops.py shuffle2`, not in the repository) then wrote a second shuffle of the
`{id, text}` records of each half with another seed (`label_input_b.json`: 96 and 64 questions), and
a fresh labeller B2, started with its instruction alone, labelled that copy and was told to read
nothing else. The comparison (a script that printed counts only):

| Half | A and B2 same bytes | Same ids | Same order | Labels that differ exactly | First run's B a copy of A |
| --- | --- | --- | --- | --- | --- |
| development | no | yes | no | 0 of 96 | yes |
| held out | no | yes | no | 0 of 64 | yes |

"Differ exactly" counts the questions whose two labels are not equal as written, a stricter test
than the disagreement of the resolution below. B2's wording is not reproduced here beyond what the
operator reported: its input was the differently shuffled copy and it was told to read nothing else.

## Resolution

Resolution (24.10, and `resolve` in `tests/narration_scoring.py`, which hand-computed cases pin):

- Two labellers agree when their routes match and their category sets intersect, or their intent
  and target are equal. The label is then the intersection of the categories, in the order of
  precedence, or the shared intent and target.
- If they disagree, a third labeller, started the same way and given only those questions, decides.
  If the third agrees with exactly one of them, the label is that agreement. If it agrees with both
  or with neither, the question is excluded and counted.
- The writer's intent is never a vote. `none` is `out_of_scope`.
- Without fresh-context agents the writer's label would stand and the set would be called
  writer-labelled. Here no label is a writer's. That each agent shared no context with any other is
  how the workflow starts agents; it was not audited.

| Half | Questions | Agreed by the first two (A, B2) | Decided by a third | Excluded |
| --- | --- | --- | --- | --- |
| development | 96 | 96 | 0 | 0 |
| held out | 64 | 64 | 0 | 0 |

Both question files were written from these labels (lint problems 0 in each half), `pins.json` was
written again for its five files and `check_pins` reported none. No question of either half needed a
third labeller and none was excluded, so no third labeller was started and neither the
third-labeller path nor the exclusion was exercised on this data (hand-made labels pin both). For
the development half, which may be read: A and B2 wrote the same label on all 96 questions, and the
resolved label agrees with the writer's stratum on all 96 (the stratum's category is in a single
refusal's label, a compound is a refusal, an answerable has its intent). The development labels are
72 refusals (4 with two categories), 24 answers (six per intent) and no `out_of_scope` or
`unreadable`, as the strata have none. The same figures for the held-out half are not recorded
here: no builder read its labels (a reviewer printed label aggregates, see the held-out half below).

## Lint

`python tests/narration_scoring.py lint` (24.10; the code is committed and hand-tested). Both halves
pass with no problem.

| | Development | Held out |
| --- | --- | --- |
| Questions | 96 | 64 |
| Strata | exactly as in 24.10 | exactly as in 24.10 |
| Fixture names | all one of the eight | all one of the eight |
| Naming `golden` (at least 80%) | 78 of 96 | 53 of 64 |
| Why-explanations of a finding (at least 4) | 6 | 5 |
| Answerable with a refusal-sounding word | 16 of 24 (at least 1) | 2 of 20 (no minimum) |
| Largest trigram similarity above 0.6 | not computed | 1 of 64 (index 50, 0.912) |

The development fixtures are `golden` 78, `clear` 3, `weekly_drift` 4, `warnings_only` 4,
`harm_blocker` 3, `short_run` 2, `short_arms` 2 and `unattainable_design` 0. The held-out fixtures,
counted by a script that printed numbers only, are `golden` 53, `clear` 4, `weekly_drift` 3,
`warnings_only` 2, `harm_blocker` 1, `short_run` 1, `short_arms` 0 and `unattainable_design` 0.
`dev-026` named `golden` until the final resolution: its text says there are only warnings, which
the golden report is not, so its fixture is now `warnings_only`; no text changed. The similarity is
to a development question, an example of 24.8 or a public question; the threshold 0.6 was fixed in
the design before any question existed. Four held-out questions lie between 0.5 and 0.6. The count
measures near-copies, not shared trigger words. Why one question of 64 sits at 0.912 is not
established: the held-out brief held none of the 116 reference texts, which excludes only a verbatim
copy. The scorer reports the headline also without the questions above the threshold.

## The held-out half

- Mechanism. The writers and labellers ran outside the repository's data and replied with a path, a
  count and a SHA-256 only. Scripts, not the builder, assembled, linted and hashed the file. It is
  committed in this pull request, with its hash in `pins.json`, as the pre-registration (24.10).
- What git proves. The history is the freeze proof: this file is committed before the router (N5)
  exists and no score is committed, so the router can be shown to have been frozen before it was
  scored. It does not show that the half is unseen; the repository is open to every later reader
  and nothing technical stops one.
- Procedure. The author of the router (N5) does not open the file; only the scorer (N8) reads it. The
  lint and the data tests read it by script and print ids, counts and numbers, no question.
- How many held-out questions any builder saw: none of the 64. The agents that built the taxonomy,
  the scoring code, the lint, the operators' scripts and this documentation, and the orchestrating
  session, handled the half by script and saw the lint's numbers (each question's largest
  similarity, by index), the counts and indices of the summary and the pinned SHA-256, no text and
  no label. Of necessity, each held-out writer saw the 16 questions it wrote and no other (each of
  the 64 by exactly one writer), and each of the three held-out labeller agents (A, the first
  run's B whose output was discarded, and B2, which read a second order) saw all 64, with ids and
  without strata. No third labeller was started. Their instruction not to read anything else is an
  instruction, not a barrier, and was not audited. The fixture counts above and the count of
  why-explanations come from a script that printed numbers only.
- Label aggregates. A reviewer of stage B printed aggregates of the held-out labels: counts only,
  no text and no per-question label. They are not recorded in this file. They are noted because the
  lapse rule below speaks of a label read; no question text and no label of a single question was
  shown.
- A lapse. If any builder is found to have read a held-out question or label, the whole half is
  relabelled "dev, not held out" here, in the evaluation report and in the README, and its score is
  a development score.

## The scorer's all-errors variant

For the questions excluded by the labellers the scorer reports an all-errors variant of the headline
with only the strict and the refused-at-all figures, the excluded questions added to each
denominator and to no numerator. "Other" and "answered" are not given there because adding excluded
questions as misses would make them look better, not worse. Both halves have 0 excluded questions,
so here the variant equals the headline.

## Limits

- One kind of agent, from one family of prompts, wrote and labelled everything: the taxonomy, the
  definitions, the 160 questions, the labels and the reviews. Agreement among them is not
  independence in a human sense, and no human labelled a question. Nor are A and B2 shown to be two
  independent judgements: B2 labelled a differently shuffled copy and was told to read nothing
  else, but whether B2 saw A's file was not audited beyond the byte comparison (the files differ)
  and the different order (a copy could have been re-sorted). That 0 of 160 labels differ exactly
  fits clear definitions and fits a labeller that saw the other file; nothing here tells them apart.
- The definitions leak vocabulary. Writers and labellers read the same words ("release", "roll
  back", "genuine", "significant") and the questions echo them, so a router built from the same
  definitions meets an easier task than real phrasing. Agreement with an agent-authored taxonomy is
  not recall on real users' questions.
- A and B2 agreed on every question of both halves, and on the development half also with the
  writer on all 96. That shows the definitions are applied consistently by this kind of agent (or
  that B2 saw A's file, see the first limit), not that they are unambiguous: the writers were asked
  for questions unambiguous to a reader of the definitions, the labelling added no signal beyond
  the writers' intent, and the third labeller and the exclusion never ran.
- Three questions per category (held out) and five (development) rest on nothing: a perfect 3 of 3
  has a 95% lower bound of 0.29 and 5 of 5 of 0.48. Per-category recall is counts only.
- The development half holds near-copies of itself: four pairs lie above 0.6 (`dev-012`, `dev-027`
  and `dev-059` worded alike, and `dev-015` with `dev-047`), so its 12 compound questions are fewer
  than 12 distinct ones. Four of the 12 also end in a launch or roll question about variant B
  (`dev-028`, `dev-044`, `dev-075`, `dev-091`) and a fifth in a launch question about the offer page
  (`dev-011`). The same is not measured for the held-out half; the lint does not.
- The held-out half has 2 answerable questions with a refusal-sounding word (the development half
  16 of 24), so its false-refusal rate says little about the case the development half was built for.
- The strata of both halves hold no `out_of_scope` and no `unreadable` question, so the default
  route and the unreadable route are measured by nothing here: the development labels hold none and
  the held-out labels are not tallied in this file.
- Every `explain_finding` question of both halves holds the word "why" (6 of 6 and 5 of 5; the
  writers were told to write them so). The set cannot show a router that sends "why" with a rule to
  `explain_finding` failing on "what does RES-003 measure" or "what are the numbers behind RES-004",
  which the definition counts as explanations too. The six development explanations target three of
  the nine rules, RES-011 (3), RES-004 (2) and RES-002 (1); the held-out targets are not recorded
  here.
- The writers named a fixture from a generic description and were told to rely on no figure of a
  report. 78 of 96 and 53 of 64 name `golden`, so a page test that runs the questions on their
  fixtures exercises the seven others little: `unattainable_design` is named by no question of
  either half and `short_arms` by none of the held-out half. `dev-022`, `dev-023` and `dev-025` rely
  on details that the descriptions of their fixtures do not give (a split off by under half a
  percent, a tiny guardrail dip, a skewed revenue metric), against the brief; their labels do not
  depend on the premise being true, but a page test meets a report that may say otherwise. `dev-065`
  names two mobile platforms, Android and iOS, although the brief asked for no company or product
  name; it asks about a subgroup and its label does not depend on the names.
