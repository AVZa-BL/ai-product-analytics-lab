# Specwright

Drafts the spec of an A/B test from a brief or a design document. A model reads the documents and
drafts the spec as a list of claims, each with its evidence; deterministic code then checks the
draft and [Referee](../referee/README.md) reads the spec, runs its design rules and works out the
sample size. Specwright is advisory: it drafts, and a person decides.

All example briefs are synthetic and written by an agent. The repository contains no production,
customer or employer data.

## Status

Built and tested offline, then run once against a live model (`claude-opus-5-5`) on the seven
synthetic briefs: see *Live results so far*. Nothing has been tried on a real plan.

## What it does

```
brief or design document ──► model drafts claims ──► checks ──┬──► ok / needs answers / infeasible
                                    ▲                          │
                                    └── blockers, as text ◄────┘   (at most 2 repairs, then as it is)
```

Each claim names a field of the spec (`primary_metric.baseline`, `arms[1].allocation`) and gives
its value with one kind of evidence:

| Kind | Meaning |
| --- | --- |
| `document` | The document's name and a verbatim quote of at least 8 characters. The quote is searched for in the document, and a number must be written in it with digits. |
| `inferred` | The value is the model's judgement, not a document's. It is listed for the analyst to confirm. |
| `missing` | The documents do not say. Value null, and a note saying what to ask. Nothing is guessed. |
| `ambiguous` | The documents give it only approximately ("about two weeks", "a few thousand"). Value null, and a note. Approximate wording is never turned into a number. |

The checks (all deterministic, [`src/specwright/check.py`](src/specwright/check.py)):

1. A quote must be in the document it names (Tracewright's quote check).
2. A number must be written in its quote (`4.2%`, `12,000`, `3 weeks` for 21 days); a number in words is not found, so it must be `inferred`.
3. A quote with approximate wording ("roughly 10%", "up to 14 days", "a few") cannot give a number.
4. Every required field must have a claim, even if only to say `missing`. If any required field is `missing` or `ambiguous`, no spec is built: the result is **needs answers**, with a partial draft and the questions.
5. Otherwise the spec is built and read by Referee, its design rules (HYP, DES and PRO) run, and the sample size and duration come from Referee's power plan, never from the model. A size the draft states that differs from Referee's is flagged, and Referee's is the one reported.

A blocker the model can fix goes back to it (at most 2 repairs by default, 5 at most). Warnings are
findings about the design and are reported, not sent back: fixing one would often mean inventing
something the documents do not say. `DES-001` (the stated numbers cannot reach the stated power)
is not sent back either: it is a fact about the brief, and the result is **infeasible**, with the
numbers.

## Running it

From this folder, with Python 3.12 (Referee and Tracewright are installed from their folders first):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -e ../referee -e ../tracewright -e '.[dev]'

python -m specwright draft --doc examples/briefs/01-shop-banner.md \
    --replay examples/replays/01-shop-banner.json --out out/
```

`--replay` reads saved responses instead of calling a model. The responses in `examples/replays/`
are written by hand: they show what a careful model's answer looks like and exercise the checks,
and `01-shop-banner.repair.json` shows a first answer with mistakes and its repair. With a model:
`python -m pip install -e '.[llm]'`, set `ANTHROPIC_API_KEY` in the environment (a key is never an
argument and is never written anywhere), and leave `--replay` out. **What is sent:** every
document, and on a repair round the previous draft and the problems, go to the Anthropic API.
Do not use it on documents you may not send there.

| Exit status | Meaning |
| --- | --- |
| 0 | A spec was drafted and Referee's design rules raise no blocker |
| 1 | A blocker is left after the repairs |
| 2 | An input cannot be used (a document, `--out`, `--max-repairs`) |
| 3 | A failure inside Specwright |
| 4 | The model could not be reached, refused, was cut off, or the replay ran out |
| 5 | **Needs answers**: the documents do not give everything a spec needs |
| 6 | **Infeasible**: the numbers the documents give cannot reach the power the spec asks for |

`--out` receives `report.md` (for people), `draft.json` (the same, for machines, with every
attempt's problems), and either `draft-spec.yaml` (status 0 and 6) or `partial-draft.yaml` (the
stated fields and the questions as comments). Nothing is overwritten without `--force`. Everything
a document or the model wrote reaches the report as an escaped code span.

## The examples

`examples/briefs/` holds seven synthetic briefs, and `tests/golden/` the exact output for each:
a clear brief (`01`, also with a repair round), an infeasible one (`02`), one with no baseline
(`03`), one with approximate numbers (`04`), an experiment buried in a long design document with
distractor numbers (`05`), three arms with two guardrails, a secondary metric and a covariate
(`06`), and one that states a sample size that differs from Referee's (`08`). The owner's real plans
are meant to be added next to them.

## Evaluating a model

```bash
python -m specwright.evaluate --out out/eval-self                 # self-test, no model
python -m specwright.evaluate --out out/eval-live --live          # a real model; ANTHROPIC_API_KEY
python -m specwright.evaluate --out out/eval-live --live --only 01-shop-banner   # one case first
```

`examples/evaluation-cases.json` lists the cases: documents, the status a careful reading gives,
and a reference draft (here, the hand-written replay). A run writes `evaluation.json` and
`evaluation.md` with, for each case and in total: the status against the expected one, the
quotes that were still not found after the repairs, the repairs and tokens used, how many stated
values (numbers, enumerations, booleans) agree with the reference, how many of the gaps the
documents leave (a missing figure, an approximate one) were left as gaps, and how many values the
model **invented** for a gap. `--token-budget` (default 400,000) stops new cases once that many
tokens are spent. To add a real plan, add a case with `"reference": null`: it then gets the scores
that need no reference (status, quotes not found, repairs, tokens). The self-test is perfect by
construction and only tests the scorer. The briefs and references are written by an agent, so
agreement with them is not accuracy on real plans.

### Live results so far

Model `claude-opus-5-5`, effort `high`, one run per case, evaluator defaults.

**First pass, original briefs:** status as expected 6 of 7; quotes not found after the repairs 0;
values agreeing with the reference 156 of 161; gaps left as gaps 4 of 4; **values invented for a
gap 0**; 6 repairs; 76,210 input and 57,462 output tokens. The five disagreeing values:

| case | field | reference / model | what it was |
| --- | --- | --- | --- |
| 05 | `hypothesis.direction` | `increase` / `two_sided` | Model error. The brief says "a two-sided test", which is `design.sided`; it gives no direction, and "we care about an 8% relative lift" for a lower price reads as an increase. The model put the test's sidedness into the direction field. |
| 06 | `arms[0..2].allocation` | 1/3 / 0.333 | Ambiguous brief. It says "in thirds: 33.3% of the players each"; the model copied the written figure, the reference read it as exact thirds. Both are defensible. The draft was never built (see next row), so the sum check (0.999) did not run. |
| 06 | `guardrails[0].kind` | `binary` / `ratio` | Ambiguous brief, and the reference was the less careful reading (below). |

**Case 06 history.** With the original brief, case 06 gave `needs_answers` (expected `ok`) in 6 of
7 live runs: the evaluation run and five repeats, against one `ok`. The brief gave "refund rate
of bundle purchases (1.5% today)" and no standard deviation. The model read it as a ratio (refunds
per purchase, so the denominator is not players) and asked for the standard deviation; the one
`ok` run labelled it `binary`. The model's reading may well have been reasonable: a per-player
refund rate can be a ratio. The brief then gained "standard deviation 0.15 per player" (an invented
figure), and the reference became `ratio` with that value quoted. Three further runs on the edited
brief gave `ok`, 35 of 35 values agreeing. **That pass is on an edited brief and a changed
reference; it does not show the model improved.** No case now tests a missing standard deviation
on a ratio metric.

## What is verified, and what is not

- **Verified by tests:** the claim table against Referee's spec (every option of every field is one Referee accepts, and the powered example assembles back to its fingerprint), the number and approximate-wording rules on reference cases, every check, the repair loop (what goes back, the limit of repairs, when it stops), the command, its exit statuses and the golden outputs, the escaping, and the **real Anthropic SDK against a mocked HTTP transport** (request body, streaming parse, a refusal, truncation, HTTP errors, a dropped connection, missing credentials). 21 deliberate faults in the code were each caught by a test.
- **Not verified:** whether a model drafts well on real plans. The API accepts the request and the output schema (see *Live results so far*), but the briefs and references are written by an agent, and the replays are hand-written.
- **Not detectable:** a vague phrase the model chose not to quote, or labelled `inferred`, looks like a judgement; it is listed for confirmation and nothing more. A found quote proves the words are in the document, not that the model read them correctly.
- **Not a judgement of the design.** Passing the checks proves the draft is consistent with the documents and with Referee's rules. It does not prove the experiment is well designed, worth running, or sized for the right effect; the report says so.
- **Limits:** one alpha adjustment as Referee plans it; ratio metrics and secondary metrics are drafted but Referee's results review does not analyse the latter; documents are read as Tracewright reads them (text and PDF; a PDF's quotes cannot be searched).
