# Linesman

A deterministic reviewer for product tracking plans: *ruff for event instrumentation*. It is the sibling of [Referee](../referee/README.md): Referee reviews experiments, Linesman reviews what the product sends to analytics. Every warning is a named rule, and advice is generated from rules, not improvised. Linesman is advisory only. It never blocks a release; it returns findings with severity, evidence and remediation.

The name follows the metaphor: the referee decides the match, the linesman watches the lines, here the boundaries of events and properties.

All plans in this project are synthetic. It contains no production, customer, or employer data.

## Status

Milestone 1 of a small project:

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1 | Tracking-plan schema and validation, 12 rules, `review-plan` CLI | Done |
| 2 | Compare a plan with events actually observed in a synthetic export (drift: undeclared events, type mismatches, missing required properties) | Planned |

## Reviewing a plan

Write the tracking plan as YAML, then run the review from this folder:

```bash
python -m linesman review-plan examples/checkout-funnel-flawed.yaml
python -m linesman review-plan examples/checkout-funnel-clean.yaml --format json
```

The first recommends **revise** (five blockers: a deprecated and an undefined event behind metrics, personal data not marked, a property with two types, an event with no identity key). The second recommends **proceed**; it is the one to copy. Both are commented.

| Exit status | Meaning |
| --- | --- |
| 0 | The review found no blocker |
| 1 | It found at least one blocker |
| 2 | The plan cannot be read or is not valid (every violation is listed) |
| 3 | A failure inside Linesman itself |

[`docs/rules.md`](docs/rules.md) is the catalogue of all 12 rules (naming, schema, documentation, governance, coverage), generated from the rule code, with what triggers each and why it matters.

What a plan contains: `identity_keys` (the properties that tie an event to a user or device), `events` (name, status `active`/`planned`/`deprecated`, description, trigger, owner, typed `properties`) and `metrics` (each lists the events it depends on).

## Limits, stated plainly

- Linesman reads the **plan**, never the data the product really sends. A plan can be flawless and the implementation still wrong; milestone 2 is meant to close that gap.
- GOV-001 recognises personal data **by property name**. It will miss a personal value with an innocent name and may flag a harmless one. Treat a hit as a question.
- The rules encode conventions (`object_action` snake_case names, one type per property name, an owner and a trigger per event) that are common practice, not a standard. Teams may reasonably differ; severities are defaults.
- `proceed` means no listed objection was raised, not that the tracking is correct or worth having.
- The two cited sources are general (a textbook chapter on instrumentation, the GDPR articles on personal data and data minimisation). Linesman gives no legal advice.

## Working on it

Linesman is self-contained. Run everything from this folder (`linesman/`), with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
python -m pytest -q
```

The only runtime dependency is PyYAML. After changing a rule's text, regenerate the catalogue (a test fails if it drifts):

```bash
python -m linesman.rules.docs > docs/rules.md
```

After changing an example or the report format, regenerate the golden files in `tests/golden/` the same way the tests compare them: `python -m linesman review-plan examples/<name>.yaml [--format json] > tests/golden/<name>.<txt|json>`.
