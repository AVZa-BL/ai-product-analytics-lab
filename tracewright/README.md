# Tracewright

Tracewright proposes the product tracking a new feature needs, and reviews tracking plans.

Give it the design document of a feature and the tracking you already have. It proposes the events to send, the properties of each with their data types, and **the reason each one is worth sending**, building on your existing structure instead of starting a new one. A model drafts the proposal; deterministic code then checks it, and sends it back when it fails. Advice is never improvised: every automatic objection is a named rule or a named check.

It is the tracking sibling of [Referee](../referee/README.md), which reviews A/B experiments. Like Referee it is advisory: it recommends, and a person decides.

All example data is synthetic. The repository contains no production, customer, or employer data.

## Status

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1 | Tracking-plan schema, 12 review rules, `review-plan` | Done |
| 2 | `propose`: feature documents + current plan → proposal with types and reasons; `import-plan` from CSV | Done, see *What is verified* |
| 3 | Run `propose` on a real design document with a real model, and judge the proposals against what an analyst would write | Next. Needs an API key and one real document |
| 4 | Read the current tracking from a **Google Sheet** (map the sheet's own columns), instead of a hand-made CSV | Planned. Needs the sheet's column layout, see *Next* |
| 5 | Compare a plan with events actually observed in an export (drift) | Planned |

## Next

Nothing in this section is built. It records what comes next and what is needed to start.

**Google Sheets as the input for the current tracking (milestone 4).** The tracking calls and their specifications live in a Google Sheet. Today `propose` reads a plan file, and `import-plan` reads one fixed CSV layout ([`docs/import-csv.md`](docs/import-csv.md)), so a real sheet will not load as it is: its headers will differ from ours, and any unknown column is refused. What decides the design is the sheet's actual layout, so before building I need, from you:

1. The **header row** of the sheet (column names only, no data needed), and whether it is one tab for all events or one tab per event or area.
2. Where the **specification** lives: free text in one column, or separate columns for trigger, owner and so on.
3. How the **property types** are written (for example `string`, `int`, `bool`, or something else).
4. How the tool should **reach** the sheet: by you exporting a tab to CSV (works today, see below), or by the tool reading the sheet directly. Reading it directly needs Google credentials that you set up (an OAuth login or a service account with read access to that sheet) and a new dependency; I would not start that without your decision.

A likely design, not decided: a small mapping from your headers to ours that you confirm once, optionally proposed by the model from the header row and the first rows. It is a proposal for you to correct, because a wrong guess about a column silently corrupts the plan.

**What works today for Google files** (nothing to build):

- *Tracking sheet:* open the tab, **File, Download, Comma Separated Values (.csv)**, rename the headers to the columns in [`docs/import-csv.md`](docs/import-csv.md), then run `import-plan`.
- *Design document in Google Docs:* **File, Download, Plain Text (.txt)** or **PDF Document (.pdf)**, then pass it with `--doc`.

**Milestone 3 first, in practice:** run `propose` once on one real document and read the result as the analyst who would have written it. That tells us whether the proposals are good enough to be worth connecting to more inputs.

## What is verified, and what is not

- **Verified by tests (offline):** the schema and its validation, the document loader, the evidence check, the collision/type/naming checks and the merge, the repair loop, the report files (golden files), the CSV importer, and the **real Anthropic SDK against a mocked HTTP transport**: the request body (including repair feedback), the streaming parse (including thinking blocks), a refusal, a truncated or otherwise unfinished response, an empty one, HTTP errors 400, 401, 403, 404, 429 and 500, a connection that fails before or during the response, and missing credentials or a missing profile. The tests run with the Anthropic credentials of the machine removed from the environment and from the home directory, and a test that opens a non-local network connection fails.
- **Not verified:** a live call to a model. No API credentials were available where this was built, so `propose` has never run against the real API. The request shape follows the SDK documentation and is accepted by the SDK, but the API's own validation of it has not been exercised.
- **Not evaluated:** how good the proposals are. The worked example below is **hand-written** to show what the output looks like and to exercise the checks; it is not model output. Judge proposal quality on your own documents before trusting it.

## Try it without a model

Once, from this folder, with Python 3.12: `python3.12 -m venv .venv && . .venv/bin/activate && python -m pip install -e .` (the model SDK is not needed for `--replay`).

The example is a made-up feature, "Alliance Treasure Hunt", for a made-up strategy game. `--replay` reads two saved responses instead of calling a model: the first has the mistakes a careless draft would have, the second fixes them.

```bash
python -m tracewright propose \
    --doc examples/alliance-treasure-hunt/gdd.md \
    --plan examples/alliance-treasure-hunt/current-tracking-plan.yaml \
    --replay examples/alliance-treasure-hunt/replayed-model-response.json \
    --out out/
```

```
attempt 1: 4 problem(s)
attempt 2: 0 problem(s)
status: ok; wrote proposal.md, proposal.json, merged-plan.yaml, plan.diff to out/
```

The four problems of attempt 1, found and sent back: a "new" event that already exists (`COLLISION`), a quotation that is not in the document (`EVIDENCE_QUOTE`), `alliance_id` typed `integer` where the plan has `string` (`SCH-001`), and a camelCase property (`NAM-002`). Open `out/proposal.md` for the result: six new events, one extended, five reused, six metrics, and for each event when it is sent, why, the quote that supports it, and a table of properties with type, required, PII and the reason each property exists. Compare with the committed copies in [`tests/golden/alliance-treasure-hunt/`](tests/golden/alliance-treasure-hunt/).

## Use it with a model

```bash
python -m pip install -e '.[llm]'          # adds the Anthropic SDK
export ANTHROPIC_API_KEY=...               # or run `ant auth login`
python -m tracewright propose --doc my-feature.md --doc balance.pdf \
    --plan my-current-plan.yaml --owner live-ops-analytics --out out/
```

- `--doc` is repeatable: Markdown, text, CSV, JSON, YAML, or PDF. Nothing is truncated; a file that is too large is refused with the limit.
- `--plan` is optional. If you track in a spreadsheet, [`import-plan`](docs/import-csv.md) turns a CSV into a plan file. With no plan, the proposal creates one and names its own identity keys.
- `--model` (default `claude-opus-5-5`), `--effort` (default `high`), `--max-repairs` 0 to 5 (default 2), `--owner` (recorded on the proposed events), `--force` (overwrite results of an earlier run in `--out`).
- **What is sent:** every document, your whole plan, and the previous proposal on each repair round go to the Anthropic API. Do not use it on documents you may not send there. [`docs/propose.md`](docs/propose.md#privacy-what-leaves-your-machine) has the details; with `--replay` nothing is sent.

How it works, every check, the output files, security notes and cost: [`docs/propose.md`](docs/propose.md).

| Exit status of `propose` | Meaning |
| --- | --- |
| 0 | A proposal with no blocking problem was written |
| 1 | A blocking problem remains after repair; the report says UNRESOLVED |
| 2 | An input cannot be read or is invalid (a document, the plan, a `--replay` file, or `--out`) |
| 3 | A failure inside Tracewright itself |
| 4 | The model could not be reached, refused, or was cut off |

## Reviewing a plan

The same rules that check a proposal also review any plan:

```bash
python -m tracewright review-plan examples/checkout-funnel-flawed.yaml
python -m tracewright review-plan examples/checkout-funnel-clean.yaml --format json
```

The first recommends **revise** (five blockers); the second **proceed** and is the one to copy. [`docs/rules.md`](docs/rules.md) is the catalogue of all 12 rules (naming, schema, documentation, governance, coverage), generated from the rule code. Exit status: 0 no blocker, 1 a blocker, 2 the plan is unreadable or invalid (every violation listed), 3 internal error.

A plan holds `identity_keys` (the properties that tie an event to a user or device), `events` (name, status `active`/`planned`/`deprecated`, description, trigger, owner, typed `properties`) and `metrics` (each lists the events it needs). Write the YAML by hand, import it from a CSV, or let `propose` extend it.

## Limits, stated plainly

- A proposal is a model's reading of your documents. The checks catch invented quotes, name and type clashes and rule violations; they cannot tell whether an event is the *right* one or whether the model understood the design. Read the reasons, not just the event list.
- A quote that is found proves the words are in the document, nothing more. Quotes from PDFs cannot be searched and are reported as not machine-checked.
- Reuse is checked by property name and type. The `pii` flag, allowed values and meaning of a reused property, and the status of a reused event (for example `deprecated`), are not compared with your plan.
- If your existing plan has a blocker of its own, a proposal can still be OK; the report names it, and `review-plan` on the merged plan will still say REVISE.
- GOV-001 recognises personal data by property **name** only (words split at underscores and camelCase boundaries); it misses a personal value with an innocent name and flags some harmless names (`phone_model`, `ip_country`). Treat a hit as a question.
- The rules encode common conventions (`object_action` snake_case names, one type per property name, an owner and a trigger per event), not a standard. Severities are defaults.
- Tracewright reads plans and documents, never the data the product actually sends.
- `proceed` and `ok` mean no listed objection was raised, not that the tracking is correct or worth having.
- The rules cite a textbook chapter on instrumentation and the GDPR articles on personal data and data minimisation. Tracewright gives no legal advice.

## Working on it

Self-contained. Run everything from this folder (`tracewright/`), with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
python -m pytest -q
```

Runtime dependency: PyYAML. The Anthropic SDK is needed only by `propose` without `--replay` (extra `llm`; `dev` includes it for the tests). Tests never touch the network and never read real credentials.

After changing a rule's text: `python -m tracewright.rules.docs > docs/rules.md` (a test fails if it drifts). After changing the example or the report format, regenerate the golden files:

```bash
python -m tracewright propose --doc examples/alliance-treasure-hunt/gdd.md \
    --plan examples/alliance-treasure-hunt/current-tracking-plan.yaml \
    --replay examples/alliance-treasure-hunt/replayed-model-response.json \
    --out tests/golden/alliance-treasure-hunt --force
python -m tracewright review-plan examples/<name>.yaml [--format json] > tests/golden/<name>.<txt|json>
```
