# Product analytics portfolio

A home for portfolio projects in product analytics. Each project lives in its own folder with its own dependencies, tests and scripts, and is run from inside that folder. All data is synthetic; the repository contains no production, customer, or employer data.

## Projects

| Project | What it is | Status |
| --- | --- | --- |
| [`analytics-lab/`](analytics-lab/) | AI Product Analytics Lab: governed, reproducible product analytics across three synthetic business scenarios, with metric contracts, decision memos and trusted evaluation cases for AI-assisted analysis | Complete |
| [`referee/`](referee/) | Referee: a deterministic, rule-based reviewer for A/B/n experiment designs and readouts ("ruff for experiments") | In development |
| [`tracewright/`](tracewright/) | Tracewright: proposes the tracking a new feature needs (events, properties, data types and the reasons) from its design documents and the current tracking plan, and reviews tracking plans with deterministic rules | Proposer and reviewer built, not yet run against a live model. Next: a trial on a real document, then Google Sheets as the input |

Start with the lab's [README](analytics-lab/README.md), or go straight to its [getting-started guide](analytics-lab/docs/getting_started.md). The [Referee](referee/README.md) and [Tracewright](tracewright/README.md) READMEs show their status and how to run them.

## How the repository is organised

- `analytics-lab/`, `referee/` and `tracewright/` are independent projects, each with its own `pyproject.toml`, tests and virtual environment. The lab also keeps its own scripts and `.gitignore`.
- `.github/workflows/ci.yml` is the single CI workflow. GitHub reads workflows only from the repository root, so each job's steps start inside its project's folder.
- `SECURITY.md` is the reporting policy for the whole repository.
