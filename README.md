# Product analytics portfolio

A home for portfolio projects in product analytics. Each project lives in its own folder with its own dependencies, tests and scripts, and is run from inside that folder. All data is synthetic; the repository contains no production, customer, or employer data.

## Projects

| Project | What it is | Status |
| --- | --- | --- |
| [`analytics-lab/`](analytics-lab/) | AI Product Analytics Lab: governed, reproducible product analytics across three synthetic business scenarios, with metric contracts, decision memos and trusted evaluation cases for AI-assisted analysis | Complete |

Start with the lab's [README](analytics-lab/README.md), or go straight to its [getting-started guide](analytics-lab/docs/getting_started.md).

## How the repository is organised

- `analytics-lab/` holds the project above, with its own `pyproject.toml`, tests, scripts and `.gitignore`.
- `.github/workflows/ci.yml` is the single CI workflow. GitHub reads workflows only from the repository root, so its steps start inside each project's folder.
- `SECURITY.md` is the reporting policy for the whole repository.
