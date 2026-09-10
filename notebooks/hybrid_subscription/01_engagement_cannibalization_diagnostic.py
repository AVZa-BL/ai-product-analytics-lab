# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Hybrid subscription engagement and cannibalization diagnostic
#
# This reproducible diagnostic asks whether subscribers show a different 28-day
# engagement movement and whether standalone-store displacement is offset by
# subscription revenue. It uses governed facts and diagnostic marts only.

# %% [markdown]
# ## TL;DR
#
# Execute all cells to populate observed values. Subscriber status is self-selected, so
# every comparison in this notebook is descriptive. The estimates do not establish that
# the subscription caused engagement or revenue changes.

# %%
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import Markdown, display


def find_repo_root() -> Path:
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "game_analytics"
        ).is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root")


@contextmanager
def working_directory(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


REPO_ROOT = find_repo_root()
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from analytics_lab.analysis.hybrid_subscription_diagnostic import (
    bootstrap_intervals,
    engagement_summary,
    reconcile_published_inputs,
    revenue_summary,
)

DB_PATH = REPO_ROOT / "game_analytics" / "dev.duckdb"
REPORT_PATH = (
    REPO_ROOT
    / "reports"
    / "hybrid_subscription"
    / "engagement_cannibalization_diagnostic_results.json"
)
FIGURE_DIR = REPO_ROOT / "reports" / "hybrid_subscription" / "figures"
BOOTSTRAP_SEED = 42
BOOTSTRAP_DRAWS = 2_000
INPUT_RELATIONS = {
    "player_behavior": "main_hybrid_subscription.fct_hybrid_subscription__player_behavior_28d",
    "engagement": "main_hybrid_subscription.mart_hybrid_subscription__engagement_lift_inputs",
    "cannibalization": "main_hybrid_subscription.mart_hybrid_subscription__cannibalization_inputs",
    "incidents": "main_hybrid_subscription.mart_hybrid_subscription__data_quality_incidents",
}

code_version = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPO_ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
executed_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
package_versions = {
    "python": platform.python_version(),
    "pandas": pd.__version__,
    "duckdb": duckdb.__version__,
    "numpy": np.__version__,
}

print(f"Repository: {REPO_ROOT}")
print(f"DuckDB: {DB_PATH}")
print(f"Code version: {code_version}")

# %% [markdown]
# ## Context & Methods
#
# ### Key assumptions
#
# - Pre and post windows are the governed half-open 28-day windows.
# - Only players with both periods enter paired calculations.
# - Revenue uses canonical transactions net of linked refunds.
# - The prior-payer store comparison is a difference-in-differences association.
# - Bootstrap resampling is stratified by subscriber status and clustered by player.
# - Published diagnostic marts must reconcile to the player-period fact before use.

# %% [markdown]
# ## Data
#
# The queries are bounded to four governed relations in `main_hybrid_subscription`.
# No raw, staging, or intermediate relation is queried.

# %%
if not DB_PATH.is_file():
    raise FileNotFoundError(f"DuckDB database does not exist: {DB_PATH}")

with working_directory(DB_PATH.parent):
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        player_behavior = connection.sql(
            f"select * from {INPUT_RELATIONS['player_behavior']} "
            "order by player_id, analysis_period"
        ).df()
        engagement_inputs = connection.sql(
            f"select * from {INPUT_RELATIONS['engagement']} "
            "order by analysis_period, is_subscriber, prior_payer_status, platform, acquisition_channel"
        ).df()
        cannibalization_inputs = connection.sql(
            f"select * from {INPUT_RELATIONS['cannibalization']} "
            "order by analysis_period, is_subscriber"
        ).df()
        incidents = connection.sql(
            f"select * from {INPUT_RELATIONS['incidents']} order by incident_code"
        ).df()
    finally:
        connection.close()

if player_behavior.empty:
    raise ValueError("Governed player behavior fact returned no rows")
reconcile_published_inputs(player_behavior, engagement_inputs, cannibalization_inputs)

display(player_behavior.head(10))
display(incidents)
print(f"Player-period rows: {len(player_behavior):,}")
print("Control totals: player fact reconciles to both diagnostic marts.")

# %% [markdown]
# ## Results

# %%
engagement = engagement_summary(player_behavior)
revenue = revenue_summary(player_behavior)
intervals = bootstrap_intervals(
    player_behavior, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED
)

display(pd.DataFrame([engagement]))
display(pd.DataFrame([revenue]))
display(pd.DataFrame([intervals]))

# %%
engagement_plot = pd.DataFrame(
    {
        "Subscriber": [
            engagement["subscriber_pre_sessions_per_player"],
            engagement["subscriber_post_sessions_per_player"],
        ],
        "Non-subscriber": [
            engagement["non_subscriber_pre_sessions_per_player"],
            engagement["non_subscriber_post_sessions_per_player"],
        ],
    },
    index=["Pre", "Post"],
)
axis = engagement_plot.plot.bar(figsize=(8, 4), color=["#3366CC", "#999999"])
axis.set_title("Mean sessions per player in mature 28-day windows")
axis.set_xlabel("Analysis period")
axis.set_ylabel("Sessions per player")
axis.legend(title="Observed group")
axis.grid(axis="y", alpha=0.25)
plt.xticks(rotation=0)
plt.tight_layout()
FIGURE_DIR.mkdir(parents=True, exist_ok=True)
plt.savefig(FIGURE_DIR / "engagement_by_period.png", dpi=150)
plt.show()
plt.close()

# %%
prior_payer_revenue = (
    player_behavior.loc[player_behavior["prior_payer_status"].eq("prior_payer")]
    .groupby(["analysis_period", "is_subscriber"], as_index=False)
    .agg(
        standalone_store=("standalone_store_net_revenue_usd", "mean"),
        subscription=("subscription_net_revenue_usd", "mean"),
    )
)
subscriber_revenue_plot = (
    prior_payer_revenue.loc[prior_payer_revenue["is_subscriber"]]
    .set_index("analysis_period")[["standalone_store", "subscription"]]
    .reindex(["pre", "post"])
)
axis = subscriber_revenue_plot.plot.bar(
    stacked=True, figsize=(8, 4), color=["#D95F02", "#1B9E77"]
)
axis.set_title("Prior-payer subscriber net revenue per player")
axis.set_xlabel("Analysis period")
axis.set_ylabel("Net revenue per player (USD)")
axis.legend(title="Revenue component")
axis.grid(axis="y", alpha=0.25)
plt.xticks(rotation=0)
plt.tight_layout()
plt.savefig(FIGURE_DIR / "subscriber_revenue_components.png", dpi=150)
plt.show()
plt.close()

# %% [markdown]
# ## Takeaways
#
# Observed facts below are direct calculations. Inferences are deliberately separated,
# and limitations state what this observational design cannot establish.

# %%
observed_facts = [
    (
        "Mean sessions per paired player moved from "
        f"{engagement['pre_sessions_per_player']:.2f} to "
        f"{engagement['post_sessions_per_player']:.2f}."
    ),
    (
        "The subscriber session change was "
        f"{engagement['subscriber_absolute_change']:+.2f}, versus "
        f"{engagement['non_subscriber_absolute_change']:+.2f} for non-subscribers."
    ),
    (
        "The prior-payer standalone-store difference-in-differences was "
        f"${revenue['standalone_store_difference_in_differences']:+.2f} per player."
    ),
    (
        "The corresponding total-net-revenue difference-in-differences was "
        f"${revenue['total_revenue_difference_in_differences']:+.2f} per player."
    ),
]
inferences = [
    (
        "Standalone-store displacement and total value answer different questions; "
        "a negative store estimate does not by itself imply value destruction."
    ),
    (
        "Subscriber and non-subscriber differences may reflect selection, acquisition "
        "mix, platform, payer history, or other uncontrolled composition."
    ),
]
limitations = [
    "Subscriber status was not randomized and is a post-index classification.",
    "The difference-in-differences parallel-trends assumption is not established.",
    "The 28-day window does not measure lifetime value, profitability, or renewal value.",
    "Bootstrap intervals quantify sampling variation, not bias from confounding.",
    (
        "Eligible marketing exposure is governed separately; the current outcome mart "
        "does not support an arm-level randomized treatment-effect estimate."
    ),
]

display(
    Markdown(
        "### Observed facts\n"
        + "\n".join(f"- {item}" for item in observed_facts)
        + "\n\n### Inferences\n"
        + "\n".join(f"- {item}" for item in inferences)
        + "\n\n### Limitations\n"
        + "\n".join(f"- {item}" for item in limitations)
    )
)

# %%
incident_records = incidents[
    ["incident_code", "affected_rows", "decision_status", "containment_rule"]
].to_dict(orient="records")
results = {
    "metadata": {
        "input_relations": list(INPUT_RELATIONS.values()),
        "filters": {
            "analysis_periods": ["pre", "post"],
            "revenue_population": "prior_payer",
            "pairing_rule": "player must have one mature row in both periods",
        },
        "code_version": code_version,
        "executed_at_utc": executed_at_utc,
        "package_versions": package_versions,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
    },
    "population": {
        "paired_players": engagement["paired_player_count"],
        "eligible_prior_payers": revenue["eligible_prior_payer_count"],
    },
    "results": {
        "engagement": engagement,
        "revenue": revenue,
        "bootstrap_intervals": intervals,
    },
    "data_quality_incidents": incident_records,
    "observed_facts": observed_facts,
    "inferences": inferences,
    "limitations": limitations,
}

REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORT_PATH.write_text(
    json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8"
)
print(f"Wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
