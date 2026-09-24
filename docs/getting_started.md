# Getting started

This repository generates synthetic data for three product-analytics scenarios, models it
with dbt into a local DuckDB file, and publishes governed metrics, diagnostics and decision
memos. Nothing is deployed and nothing talks to a network — everything below runs on your
machine and can be deleted afterwards.

Allow about ten minutes to get from a fresh clone to querying modelled data.

## Prerequisites

- **Python 3.12 exactly.** `pyproject.toml` pins `>=3.12,<3.13`; 3.11 and 3.13 will fail to install.
- **Git**
- **About 2 GB free disk** for the virtual environment, generated Parquet and the DuckDB file
- macOS or Linux, with `bash` or `zsh`

## 1. Install

```bash
git clone https://github.com/AVZa-BL/ai-product-analytics-lab.git
cd ai-product-analytics-lab
python3.12 -m venv .venv