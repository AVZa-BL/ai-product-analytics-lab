# Product analytics portfolio

A home for portfolio projects in product analytics. Each project lives in its own folder with its own dependencies, tests and scripts, and is run from inside that folder. All data is synthetic; the repository contains no production, customer, or employer data.

## Projects

| Project | What it is | Status |
| --- | --- | --- |
| [`analytics-lab/`](analytics-lab/) | AI Product Analytics Lab: governed, reproducible product analytics across three synthetic business scenarios, with metric contracts, decision memos and trusted evaluation cases for AI-assisted analysis | Complete |
| [`referee/`](referee/) | Referee: a deterministic, rule-based reviewer for A/B/n experiment designs and readouts ("ruff for experiments") | In development |

Start with the lab's [README](analytics-lab/README.md), or go straight to its [getting-started guide](analytics-lab/docs/getting_started.md). Referee's [README](referee/README.md) shows its status and how to run it.

## How the repository is organised

- `analytics-lab/` and `referee/` are independent projects, each with its own `pyproject.toml`, tests and virtual environment. The lab also keeps its own scripts and `.gitignore`.
- `.github/workflows/ci.yml` is the single CI workflow. GitHub reads workflows only from the repository root, so each job's steps start inside its project's folder.
- `SECURITY.md` is the reporting policy for the whole repository.
