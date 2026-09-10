# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Hybrid subscription: matched engagement and cannibalization
#
# ## TL;DR
#
# Execute top-to-bottom for observed estimates and 95% pair-bootstrap intervals.
# Every estimate is a **28-day matched observational difference**: subscriber
# (post minus pre) minus control (post minus pre). This synthetic lab diagnostic
# does not establish causality. Calendar-month and cohort metrics are descriptive
# context, not replications of the matched estimate.

# %%
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from IPython.display import Markdown, display
except ImportError:
    # The percent-format source also supports direct Python execution.
    Markdown = str
    display = print

REPO_ROOT = next(
    path
    for path in (Path.cwd(), *Path.cwd().parents)
    if (path / "pyproject.toml").is_file() and (path / "game_analytics").is_dir()
)
sys.path.insert(0, str(REPO_ROOT / "src"))

from analytics_lab.analysis.hybrid_subscription_diagnostic import (  # noqa: E402
    bootstrap_intervals,
    engagement_summary,
    reconcile_published_inputs,
    revenue_summary,
)

DB_PATH = REPO_ROOT / "game_analytics/dev.duckdb"
REPORT_PATH = (
    REPO_ROOT / "reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json"
)
FIGURE_DIR = REPO_ROOT / "reports/hybrid_subscription/figures"
BOOTSTRAP_SEED = 42
BOOTSTRAP_DRAWS = 2_000
INPUT_RELATIONS = {
    "pairs": "main_hybrid_subscription.mart_hybrid_subscription__matched_incrementality",
    "engagement": "main_hybrid_subscription.mart_hybrid_subscription__engagement_lift_inputs",
    "cannibalization": "main_hybrid_subscription.mart_hybrid_subscription__cannibalization_inputs",
    "monthly_kpis": "main_hybrid_subscription.mart_hybrid_subscription__monthly_kpis",
    "cohorts": "main_hybrid_subscription.mart_hybrid_subscription__subscription_cohorts",
    "incidents": "main_hybrid_subscription.mart_hybrid_subscription__data_quality_incidents",
}
PAIRING_RULE = {
    "method": "greedy one-to-one nearest control without replacement",
    "exact_strata": ["prior_payer_status", "platform", "acquisition_channel"],
    "subscriber_order": [
        "prior_payer_status ASC",
        "platform ASC",
        "acquisition_channel ASC",
        "pre_session_count ASC",
        "player_id ASC",
    ],
    "control_order_within_stratum": [
        "abs(control.pre_session_count - subscriber.pre_session_count) ASC",
        "control.pre_session_count ASC",
        "control.player_id ASC",
    ],
    "reuse_controls": False,
    "source_model": "game_analytics/models/hybrid_subscription/intermediate/"
    "int_hybrid_subscription__matched_pairs.sql",
}
ELIGIBILITY_RULES = {
    "index": "earliest incrementality-eligible exposure in UTC",
    "subscriber": "first subscription start exists and is strictly after index",
    "control": "no observed subscription start",
    "maturity": "index - 28 days >= global observation start and index + 28 days "
    "<= global observation end; one complete row per player per period",
    "observation_bounds": "minimum/maximum governed session, transaction, and LiveOps timestamps",
    "pre_window": "[index - 28 days, index)",
    "post_window": "[index, index + 28 days)",
    "engagement_population": "all matched eligible subscriber/control pairs",
    "revenue_population": "matched pairs where both players are prior_payer",
}


def resolve_code_version(repo_root: Path) -> tuple[str, str]:
    """Label verified remote snapshots explicitly; real checkouts default to Git."""
    override = os.environ.get("ANALYTICS_SOURCE_COMMIT")
    if override:
        if len(override) != 40 or any(char not in "0123456789abcdef" for char in override):
            raise ValueError("ANALYTICS_SOURCE_COMMIT must be a full lowercase commit SHA")
        return override, "explicit remote snapshot override"
    version = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return version, "local git HEAD"


code_version, code_version_source = resolve_code_version(REPO_ROOT)
executed_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
package_versions = {
    "python": platform.python_version(),
    "pandas": pd.__version__,
    "duckdb": duckdb.__version__,
    "numpy": np.__version__,
    "matplotlib": matplotlib.__version__,
}
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
print(f"Source commit: {code_version}")

# %% [markdown]
# ## Context & Methods
#
# ### Key assumptions
#
# Governed SQL owns eligibility, earliest-exposure indexing, mature half-open
# 28-day UTC windows, canonical net cash revenue, and matching.
# Exact strata are payer history, platform, and acquisition channel. Subscribers
# are processed in ascending stratum, pre-session count, and player ID order.
# Each gets the unused same-stratum control ordered by absolute pre-session
# distance, control pre-session count, and control player ID (all ascending).
# Unmatched players do not enter pair estimates; their counts remain visible.
#
# Bootstrap resampling uses whole matched pairs with replacement, 2,000 draws,
# seed 42, and 2.5th/97.5th percentiles. Revenue intervals use prior-payer pairs.
# These conditional intervals do not establish exchangeability, parallel trends,
# causal identification, profitability, or lifetime value.

# %% [markdown]
# ## Data
#
# Only the six declared governed marts are queried. Pair rows must reconcile
# to both aggregate-control marts before any estimate, interval, or plot.
# Monthly and cohort context retain their own denominators and maturity flags.

# %%
if not DB_PATH.is_file():
    raise FileNotFoundError(f"Missing governed database: {DB_PATH}")
queries = {
    "pairs": f"select * from {INPUT_RELATIONS['pairs']} order by subscriber_sequence, pair_id",
    "engagement": f"select * from {INPUT_RELATIONS['engagement']} "
    "order by prior_payer_status, platform, acquisition_channel",
    "cannibalization": f"select * from {INPUT_RELATIONS['cannibalization']} "
    "order by prior_payer_status",
    "monthly_kpis": f"select * from {INPUT_RELATIONS['monthly_kpis']} order by metric_month",
    "cohorts": f"select * from {INPUT_RELATIONS['cohorts']} order by cohort_type, cohort_date",
    "incidents": f"select * from {INPUT_RELATIONS['incidents']} order by incident_code",
}
# Resolve source-backed dbt views relative to the project directory.
original_directory = Path.cwd()
os.chdir(DB_PATH.parent)
try:
    with duckdb.connect(str(DB_PATH), read_only=True) as connection:
        inputs = {name: connection.sql(query).df() for name, query in queries.items()}
finally:
    os.chdir(original_directory)
pairs = inputs["pairs"]
reconcile_published_inputs(pairs, inputs["engagement"], inputs["cannibalization"])

count_columns = [
    "eligible_subscriber_count",
    "eligible_control_count",
    "matched_pair_count",
    "unmatched_subscriber_count",
    "unmatched_control_count",
]
if pairs[count_columns].isna().any().any() or not pairs[count_columns].nunique().eq(1).all():
    raise ValueError("Matched population totals must be present and constant")
totals = pairs[count_columns].iloc[0]
if (totals < 0).any() or not totals.eq(totals.astype(int)).all():
    raise ValueError("Matched population totals must be nonnegative integers")
population = {column: int(totals[column]) for column in count_columns}
if any(
    pairs[column].duplicated().any() for column in ["subscriber_player_id", "control_player_id"]
):
    raise ValueError("One-to-one matching cannot reuse subscribers or controls")
if population["matched_pair_count"] != len(pairs):
    raise ValueError("Matched pair count differs from row count")
for arm in ["subscriber", "control"]:
    if population[f"eligible_{arm}_count"] != len(pairs) + population[f"unmatched_{arm}_count"]:
        raise ValueError(f"Eligible/matched/unmatched {arm} counts do not reconcile")
prior_payer_pairs = pairs.loc[pairs["subscriber_prior_payer_status"].eq("prior_payer")]
population["matched_prior_payer_pair_count"] = len(prior_payer_pairs)
display(pd.DataFrame([population]).T.rename(columns={0: "Players or pairs"}))
display(inputs["incidents"])
print("Population and both published aggregate controls reconcile before calculation.")

# %% [markdown]
# ## Results
#
# ### Matched 28-day estimates and uncertainty
#
# Positive values mean subscriber post-minus-pre changes exceed matched control
# changes. The API name "difference_in_differences" is arithmetic nomenclature,
# not a causal claim. Revenue means and intervals use only prior-payer pairs.

# %%
engagement = engagement_summary(pairs)
revenue = revenue_summary(pairs)
intervals = bootstrap_intervals(pairs, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED)
estimate_rows = []
for label, mean, bounds in [
    (
        "Sessions (all pairs)",
        engagement["engagement_difference_in_differences"],
        intervals["engagement_change_ci_95"],
    ),
    (
        "Standalone revenue, USD (prior-payer pairs)",
        revenue["standalone_store_difference_in_differences"],
        intervals["standalone_store_difference_in_differences_ci_95"],
    ),
    (
        "Total revenue, USD (prior-payer pairs)",
        revenue["total_revenue_difference_in_differences"],
        intervals["total_revenue_difference_in_differences_ci_95"],
    ),
]:
    estimate_rows.append(
        {
            "28-day matched observational difference": label,
            "Mean": mean,
            "95% lower": bounds[0],
            "95% upper": bounds[1],
        }
    )
display(pd.DataFrame(estimate_rows).round(3))

# %%
FIGURE_DIR.mkdir(parents=True, exist_ok=True)
figure, axis = plt.subplots(figsize=(10, 4.8))
axis.hist(
    pairs["session_count_difference_in_differences"],
    bins="auto",
    color="#3366A0",
    edgecolor="white",
)
axis.axvline(0, color="#333333", linewidth=1)
axis.set_title(f"Pair session differences | {len(pairs):,} matched pairs")
axis.set_xlabel("28-day matched observational difference in sessions (subscriber minus control)")
axis.set_ylabel("Pair count\n28-day matched\nobservational difference bins")
axis.grid(axis="y", alpha=0.2)
figure.tight_layout()
figure.savefig(FIGURE_DIR / "matched_pair_session_differences.png", dpi=150)
plt.show()
plt.close(figure)

# %%
components = ["standalone_store", "subscription", "total"]
figure, axes = plt.subplots(3, 1, figsize=(10, 11), sharex=True)
revenue_columns = [
    f"{component}_net_revenue_usd_difference_in_differences" for component in components
]
bins = np.histogram_bin_edges(prior_payer_pairs[revenue_columns].to_numpy().ravel(), bins="auto")
for axis, column, label in zip(
    axes, revenue_columns, ["Standalone store", "Subscription", "Total"], strict=True
):
    axis.hist(prior_payer_pairs[column], bins=bins, color="#3366A0", edgecolor="white")
    axis.axvline(0, color="#333333", linewidth=1)
    axis.set_title(f"{label} revenue | {len(prior_payer_pairs):,} matched prior-payer pairs")
    axis.set_xlabel("28-day matched observational difference in net revenue (USD)")
    axis.set_ylabel("Pair count\n28-day matched\nobservational difference bins")
    axis.grid(axis="y", alpha=0.2)
figure.tight_layout()
figure.savefig(FIGURE_DIR / "matched_pair_revenue_differences.png", dpi=150)
plt.show()
plt.close(figure)

# %% [markdown]
# ### Calendar-month and cohort context
#
# These descriptive metrics have different windows and denominators from the
# matched analysis. Full rows, maturity flags, and null rates are retained in JSON.

# %%
display(
    inputs["monthly_kpis"][
        [
            "metric_month",
            "is_month_complete",
            "mau",
            "total_net_revenue_usd",
            "arpmau",
        ]
    ]
)
display(
    inputs["cohorts"][
        [
            "cohort_type",
            "cohort_date",
            "is_conversion_mature",
            "is_d30_mature",
            "subscription_conversion_rate",
            "d30_subscriber_retention_rate",
        ]
    ].head(12)
)

# %% [markdown]
# ## Takeaways

# %%
observed_facts = [
    f"{population['eligible_subscriber_count']} eligible subscribers and "
    f"{population['eligible_control_count']} eligible controls yielded {len(pairs)} pairs; "
    f"{population['unmatched_subscriber_count']} subscribers and "
    f"{population['unmatched_control_count']} controls remained unmatched.",
    "The mean 28-day matched observational difference in sessions was "
    f"{engagement['engagement_difference_in_differences']:+.3f} per pair.",
    f"Among {len(prior_payer_pairs)} matched prior-payer pairs, the mean 28-day matched "
    "observational difference in standalone-store net revenue was "
    f"${revenue['standalone_store_difference_in_differences']:+.3f}, subscription net "
    f"revenue ${revenue['subscription_difference_in_differences']:+.3f}, and total net "
    f"revenue ${revenue['total_revenue_difference_in_differences']:+.3f} per pair.",
]
inferences = [
    "Store displacement and total net revenue answer different questions; neither "
    "component accounting nor matching identifies the effect of subscription.",
    "The observed pattern may motivate a randomized pre-exposure intent-to-treat test; "
    "it does not predict rollout outcomes for unmatched players.",
]
limitations = [
    "All inputs are deterministic synthetic lab data, not evidence about a real product.",
    "Subscriber status is self-selected and defined by a post-index subscription start.",
    "Matching does not establish exchangeability, parallel trends, or causality.",
    "Matching is greedy and order-dependent; residual baseline imbalance and unmeasured "
    "confounding can remain within exact strata.",
    "Global timestamp bounds define maturity, not proof of individual telemetry completeness; "
    "eligible-exposure filtering can introduce selection.",
    "The 28-day window does not establish profitability or lifetime value; costs, long-term "
    "renewal outcomes, and lifetime cash flows are not estimated.",
    "Pair-bootstrap intervals condition on selected pairs; they quantify resampling variation, "
    "not confounding bias, rematching uncertainty, or causal effects.",
    "Calendar-month KPIs and conversion/D30 cohorts use separate denominators and maturity "
    "rules and cannot substitute for matched 28-day differences.",
]
display(
    Markdown(
        "### Observed facts\n\n"
        + "\n".join(f"- {item}" for item in observed_facts)
        + "\n\n### Inferences\n\n"
        + "\n".join(f"- {item}" for item in inferences)
        + "\n\n### Limitations\n\n"
        + "\n".join(f"- {item}" for item in limitations)
    )
)

# %%
execution_provenance_path = REPO_ROOT / "execution_provenance.json"
execution_provenance = (
    json.loads(execution_provenance_path.read_text())
    if execution_provenance_path.is_file()
    else {"mode": "existing local governed DuckDB artifact"}
)
results = {
    "metadata": {
        "input_relations": list(INPUT_RELATIONS.values()),
        "queries": queries,
        "input_row_counts": {name: len(frame) for name, frame in inputs.items()},
        "filters": ELIGIBILITY_RULES,
        "pairing_rule": PAIRING_RULE,
        "code_version": code_version,
        "code_version_source": code_version_source,
        "executed_at_utc": executed_at_utc,
        "package_versions": package_versions,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_method": "whole matched-pair resampling with replacement; percentile 95%; "
        "all pairs for engagement, prior-payer pairs for revenue",
        "execution_provenance": execution_provenance,
        "database_sha256": hashlib.sha256(DB_PATH.read_bytes()).hexdigest(),
    },
    "population": population,
    "control_totals": {
        "reconciliation_status": "passed before calculation",
        "engagement": json.loads(
            inputs["engagement"].to_json(orient="records", double_precision=15)
        ),
        "cannibalization": json.loads(
            inputs["cannibalization"].to_json(orient="records", double_precision=15)
        ),
    },
    "results": {"engagement": engagement, "revenue": revenue, "bootstrap_intervals": intervals},
    "context": {
        name: json.loads(
            inputs[name].to_json(orient="records", date_format="iso", double_precision=15)
        )
        for name in ["monthly_kpis", "cohorts"]
    },
    "data_quality_incidents": json.loads(
        inputs["incidents"].to_json(orient="records", date_format="iso")
    ),
    "observed_facts": observed_facts,
    "inferences": inferences,
    "limitations": limitations,
}
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORT_PATH.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8")
print(f"Wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
