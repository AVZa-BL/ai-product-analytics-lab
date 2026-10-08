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
| 4 | Read the current tracking from a **Google Sheet** (recognises common headers, `--map` for the rest, `--dry-run` to check) | Built and tested against stand-ins for Google; never run against a real sheet |
| 5 | Compare a plan with events actually observed in an export (drift) | Planned |

## Next

Nothing here is built yet.

1. **A trial on a real document with a real model (milestone 3).** Run `propose` once on one real design document and read the result as the analyst who would have written it. That tells us whether the proposals are good enough to be worth connecting to more inputs. Needs an API key and one real document.
2. **A first read of a real Google Sheet.** The Sheets input is built and tested against stand-ins for Google ([`docs/google-sheets.md`](docs/google-sheets.md)), but never run against a real sheet. Start with `--dry-run` on yours; the header row of your sheet, if you send it, lets me check the recognised spellings against it.
3. **The drift check (milestone 5).** Compare a plan with the events a product really sends.

## What is verified, and what is not

- **Verified by tests (offline):** the schema and its validation, the document loader, the evidence check, the collision/type/naming checks and the merge, the repair loop, the report files (golden files), the CSV and spreadsheet importer (column recognition, value cleaning, two hand-written example layouts, the Google Sheets reader against stand-ins for Google and against a server on this machine), and the **real Anthropic SDK against a mocked HTTP transport**: the request body (including repair feedback), the streaming parse (including thinking blocks), a refusal, a truncated or otherwise unfinished response, an empty one, HTTP errors 400, 401, 403, 404, 429 and 500, a connection that fails before or during the response, and missing credentials or a missing profile. The tests run with the Anthropic credentials of the machine removed from the environment and from the home directory, and a test that opens a non-local network connection fails.
- **Not verified:** a read from a real Google Sheet (no Google account was available), or the steps for getting a Google access token. See [`docs/google-sheets.md`](docs/google-sheets.md).
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
- `--plan` is optional. If you track in a Google Sheet or a spreadsheet, [`import-plan`](docs/google-sheets.md) turns it into a plan file. With no plan, the proposal creates one and names its own identity keys.
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
