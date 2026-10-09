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
code and a severity. `blocker` and `warning` problems are sent back to the model for repair (a
warning is sent back too, because the model can usually fix it: a camelCase name, say). `info`
problems are only reported. Only a `blocker` makes the status `unresolved` and the exit status 1.

| Code | Severity | Meaning |
| --- | --- | --- |
| `DUPLICATE` | blocker | An event name appears twice in the proposal, or in more than one list. |
| `COLLISION` | blocker | A new event has the name of an event the plan already has. |
| `UNKNOWN_EVENT` | blocker | An extended or reused event is not in the existing plan. |
| `AMBIGUOUS_EVENT` | blocker | A name matches two plan events that differ only in letter case. |
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
proposal **introduced** count against it. A finding the plan already had (same rule, same
evidence) is reported in the baseline count, with its severity, and not blamed on the proposal. If
the proposal changes a finding (a rule that lists every offender, such as `NAM-001`, now lists one
more), the finding is shown whole, including the offenders that were already there. `SCH-001` is
judged more finely, because the model cannot repair the plan's own type conflict: a proposal that
reuses a property the plan already has in two types is not blamed for it, and is blamed only for a
new conflicting property or a new type on a conflicting one. Details:

- The review treats the new events as **shipped** (`active`), because the question is whether the
  plan is sound once the feature is out. The merged plan written to disk marks them `planned`,
  which is the truth until they ship.
- `DOC-002` (no owner) and `COV-003` (a metric on an event the plan lists as `planned`) are
  reported but never sent back for repair: the model cannot know who owns an event, and cannot
  change the status of an event in your plan. Pass `--owner`, or give your plan a default `owner`.
- If the existing plan has a blocker of its own, the proposal can still be `ok` (exit 0) while
  `review-plan` on the merged plan says REVISE. The report says so, with the rule ids.
- Events are matched by exact name. If a name is not an exact match, it matches the one plan event
  that differs only in letter case; if two do, the proposal is told to use an exact name.
- Reuse is checked by property **name and type** (a type clash is `SCH-001`). Whether the `pii`
  flag, the allowed values or the meaning of a reused property, or the status of a reused event
  (for example `deprecated`), agree with the plan is not checked; read the property tables
  against your plan.

## Evidence: how "why" is kept honest

Every new or extended event carries evidence of one of two kinds:

- `document`: the name of a document and a **verbatim quote** from it. The quote is searched for in
  the document. Case, runs of whitespace, curly quotes, hyphens and dashes, zero-width characters,
  and the `*` and backtick marks of Markdown emphasis and code are ignored. Other markup
  (`_emphasis_`, links, escapes) must be quoted as it is written in the file. Words are not
  ignored: a quote may not start or end inside a word or a number, so `entry cost of 50` is not
  found in `entry cost of 500`. A quote that is not found is a blocker and is sent back.
- `inferred`: the event follows from the analyst's judgement, not from a sentence in the documents.
  The report says so in plain words.

A found quote proves the words are in the document. It does **not** prove the model read them
correctly, or that the event is the right one. The report states this next to the counts.

## Repair

If the checks find something the model can fix, the previous proposal and the list of problems are
sent back and the model is asked for a complete corrected proposal (default: up to 2 times,
`--max-repairs`). Each repair is a fresh request that carries the documents, the plan, the previous
proposal and the problems; nothing is edited by Tracewright itself. What is left after the last
round is reported as it is. An unresolved proposal exits with status 1 and its report starts with
**UNRESOLVED**. `merged-plan.yaml` and `plan.diff` are not written, and with `--force` any left
over from an earlier run in the same `--out` are removed, so the directory always matches the latest
run.

Each attempt's line (problems found, tokens spent) is printed to standard error as the attempt
finishes. If a repair round then fails (the API is down), the error says how many completed
attempts are discarded; their cost was already spent and is visible in those lines.

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
| `plan.diff` | What the proposal adds, as a unified diff between Tracewright's normalised rendering of your plan (left, `existing-plan.yaml`) and `merged-plan.yaml` (right). It is for reading and does not apply to your original file. Status OK, with a plan. |

Adopt `merged-plan.yaml` as a whole; it also rewrites your file's formatting and drops its
comments. Nothing is overwritten unless `--force` is given (a symbolic link in `--out` counts as
an existing file). `--out` is checked before the model is called, so a directory that cannot be
written costs nothing. Output is deterministic: no timestamps.

## Models and cost

The default model is `claude-opus-5-5` at `--effort high`; override with `--model` and `--effort`.
The model is given **no tools**; it reads text and returns one JSON object that matches a schema.
Credentials are read from the environment by the Anthropic SDK (`ANTHROPIC_API_KEY`, or the profile
from `ant auth login`) and are never written anywhere.

Cost is input tokens (your documents
plus the plan plus about 2,000 for the instructions) and output tokens (a proposal is typically
a few thousand), times the model's price per token. Check the current price of your model before a
large run; a repair round repeats the full input.

## Privacy: what leaves your machine

Without `--replay`, every `--doc` (a PDF as the PDF itself), your whole existing plan and, on each
repair round, the previous proposal are sent to the Anthropic API. Do not point it at documents you
may not send there. The data-retention and training terms of your Anthropic account apply; read
them before using confidential design documents. Tracewright keeps nothing elsewhere and writes only
to `--out`. With `--replay`, and for `review-plan` and `import-plan`, nothing is sent anywhere.

## Security notes

A design document is untrusted text that is placed in a prompt. Tracewright limits the damage
rather than claiming to prevent the attack:

- the model has no tools and cannot read files, run commands or call the network;
- documents are fenced by markers that carry the document's SHA-256, and the instructions say
  text inside them is data;
- the output is parsed against a strict schema and every claim is checked; nothing the model says
  is executed or used as a path;
- results are written to fixed file names in the directory you chose;
- text from the model is checked and escaped before it goes into the Markdown report: control and
  text-direction characters make a proposal invalid, `<` is written as an entity, square brackets
  are escaped (so `[text](url)` and `![alt](url)` appear as text and nothing is fetched), line
  breaks become spaces, and `|` and backticks cannot break a table or a code span.

A document can still make the model propose something bad (a misleading event, a leaked
instruction in a rationale). That is why the output is a proposal for a person to read.

## What it cannot do

- It does not know your product. Everything it proposes comes from the documents and the plan; what
  they leave out appears, if the model is honest, under *Questions the documents do not answer*.
- It does not check the implementation. A plan describes intent; whether the app sends these
  events is a separate question.
- It does not read your product's data or code. The merged plan describes intent.
- It does not rank proposals by business value, and it cannot measure how much a proposal would
  help. Quality of proposals has not been evaluated against a reference set; see the README.
