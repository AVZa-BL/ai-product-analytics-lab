# How `tracewright propose` works

You give it documents about a new feature (a game design document, a spec) and, if you have one,
your existing tracking plan. It returns the tracking the feature needs: events, properties, data
types, the reason for each, and the metrics they make possible.

```
documents ──┐
            ├─► model drafts a proposal ─► deterministic checks ─┬─► ok ─► proposal.md, .json,
existing  ──┘          ▲                                          │       merged-plan.yaml, plan.diff
plan                   │                                          └─► problems ─► sent back (≤ N times)
                       └──────────────── problems, as text ◄─────────────┘     then reported as they are
```

A model does the part that needs reading and judgement. Everything it says is then checked by code
that does not trust it.

## The checks

Each check is deterministic: the same proposal gives the same result. A problem is reported with a
code; `blocker` problems make the status `unresolved` and are sent back to the model for repair.

| Code | Severity | Meaning |
| --- | --- | --- |
| `DUPLICATE` | blocker | An event name appears twice in the proposal, or in more than one list. |
| `COLLISION` | blocker | A new event has the name of an event the plan already has. |
| `UNKNOWN_EVENT` | blocker | An extended or reused event is not in the existing plan. |
| `DUPLICATE_PROPERTY` | blocker | An extended event adds a property it already has. |
| `IDENTITY` | blocker | There is no existing plan, and `identity_keys` or `feature.id` is missing. |
| `METRIC_COLLISION` | blocker | A proposed metric has the name of a metric the plan already has. |
| `EVIDENCE_DOCUMENT` | blocker | Evidence cites a document that was not provided. |
| `EVIDENCE_QUOTE` | blocker | A quote is not found in the document it is attributed to. |
| `EVIDENCE_UNVERIFIABLE` | info | A quote is from a PDF, which cannot be searched. |
| `REUSE_CLAIM` | warning | A property is marked `reuses_existing`, but the plan has no such property. |
| `REUSE_UNFLAGGED` | info | A property already exists in the plan but is not marked `reuses_existing`. |
| `PLAN` | blocker | The merged result is not a valid tracking plan. |

On top of that, the proposal is merged into your plan and the 12 rules of
[`rules.md`](rules.md) run on the result, exactly as `review-plan` would. Only the findings the
proposal **introduced** count against it: a finding the plan already had (same rule, same
evidence) is reported in the baseline count and not blamed on the proposal. Two details:

- The review treats the new events as **shipped** (`active`), because the question is whether the
  plan is sound once the feature is out. The merged plan written to disk marks them `planned`,
  which is the truth until they ship.
- `DOC-002` (no owner) is reported but never sent back for repair: the model cannot know who owns
  an event. Pass `--owner`, or give your plan a default `owner`.

## Evidence: how "why" is kept honest

Every new or extended event carries evidence of one of two kinds:

- `document`: the name of a document and a **verbatim quote** from it. The quote is searched for in
  the document (case, whitespace, curly quotes, dashes and Markdown emphasis are ignored; words are
  not). A quote that is not found is a blocker and is sent back.
- `inferred`: the event follows from the analyst's judgement, not from a sentence in the documents.
  The report says so in plain words.

A found quote proves the words are in the document. It does **not** prove the model read them
correctly, or that the event is the right one. The report states this next to the counts.

## Repair

If the checks find something the model can fix, the previous proposal and the list of problems are
sent back and the model is asked for a complete corrected proposal (default: up to 2 times,
`--max-repairs`). Each repair is a fresh request that carries the documents, the plan, the previous
proposal and the problems; nothing is edited by Tracewright itself. What is left after the last
round is reported as it is. An unresolved proposal exits with status 1, its report starts with
**UNRESOLVED**, and `merged-plan.yaml` and `plan.diff` are not written.

## Inputs

- `--doc PATH` (repeatable): `.md .markdown .txt .rst .csv .tsv .json .yaml .yml` as text, or
  `.pdf`. Text is read as UTF-8. Files over 2 MB (text) or 20 MB (PDF), more than 20 documents, or
  over 20 MB in total are **refused, never truncated**. Convert `.docx` and other formats to text or
  PDF first. File names are used to cite evidence, so they must be distinct and must not contain
  quotes, backslashes, `<`, `>` or control characters. A SHA-256 of each file is recorded in the
  report.
- `--plan PATH`: a tracking plan in YAML. Build one from a spreadsheet with
  [`import-plan`](import-csv.md). Without it the proposal is for a new plan and must name its own
  `identity_keys`.

## Outputs (in `--out`)

| File | Content |
| --- | --- |
| `proposal.md` | The report for people: summary, each new event with trigger, reason, evidence and a property table with types, then extended and reused events, metrics, what was deliberately not tracked, assumptions, open questions, the automatic checks and provenance. |
| `proposal.json` | The same, for machines, including every attempt's problems. |
| `merged-plan.yaml` | Your plan with the proposal applied (status OK only). Valid input for `review-plan`. Comments in a hand-written plan are not kept. |
| `plan.diff` | A unified diff from your plan to the merged plan (status OK, with a plan). |

Nothing is overwritten unless `--force` is given. Output is deterministic: no timestamps.

## Models and cost

The default model is `claude-opus-5-5` at `--effort high`; override with `--model` and `--effort`.
The model is given **no tools**; it reads text and returns one JSON object that matches a schema.
Credentials are read from the environment by the Anthropic SDK (`ANTHROPIC_API_KEY`, or the profile
from `ant auth login`) and are never written anywhere.

Each attempt's token counts are printed on standard error. Cost is input tokens (your documents
plus the plan plus about 2,000 for the instructions) and output tokens (a proposal is typically
a few thousand), times the model's price per token. Check the current price of your model before a
large run; a repair round repeats the full input.

## Security notes

A design document is untrusted text that is placed in a prompt. Tracewright limits the damage
rather than claiming to prevent the attack:

- the model has no tools and cannot read files, run commands or call the network;
- documents are fenced by markers that carry the document's SHA-256, and the instructions say
  text inside them is data;
- the output is parsed against a strict schema and every claim is checked; nothing the model says
  is executed or used as a path;
- results are written to fixed file names in the directory you chose;
- text from the model is escaped before it goes into the Markdown report.

A document can still make the model propose something bad (a misleading event, a leaked
instruction in a rationale). That is why the output is a proposal for a person to read.

## What it cannot do

- It does not know your product. Everything it proposes comes from the documents and the plan; what
  they leave out appears, if the model is honest, under *Questions the documents do not answer*.
- It does not check the implementation. A plan describes intent; whether the app sends these
  events is a separate question.
- It does not rank proposals by business value, and it cannot measure how much a proposal would
  help. Quality of proposals has not been evaluated against a reference set; see the README.
