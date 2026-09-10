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
# # D7 retention diagnostic
#
# This reproducible diagnostic separates the observed D7-retention movement into
# acquisition-mix and within-channel components. It also quantifies Android
# completed-session sensitivity and progression-friction associations. All inputs come
# from the governed diagnostic mart; no raw, staging, or intermediate relation is queried.

# %% [markdown]
# ## TL;DR
#
# Execute all cells to populate the observed values. The analysis is descriptive: neither
# the season update nor its configuration timing is randomized, so the results do not
# establish causality.

# %%
from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import Markdown, display


def find_repo_root() -> Path:
    """Find the repository without depending on the notebook process directory."""
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "game_analytics"
        ).is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root")


REPO_ROOT = find_repo_root()
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from analytics_lab.analysis.live_strategy_retention import (
    INPUT_RELATION,
    bootstrap_difference_ci,
    d7_contribution_table,
    load_diagnostic_inputs,
    standardized_retention,
)

DB_PATH = REPO_ROOT / "game_analytics" / "dev.duckdb"
REPORT_PATH = REPO_ROOT / "reports" / "live_strategy" / "d7_retention_diagnostic_results.json"
FIGURE_PATH = REPO_ROOT / "reports" / "live_strategy" / "figures" / "d7_retention_by_period.png"
BOOTSTRAP_SEED = 42
BOOTSTRAP_DRAWS = 2_000
FILTERS = {
    "periods": ["pre_update", "post_update"],
    "retention_signals": ["robust_activity", "completed_session"],
    "maturity_rule": "eligible_d7_players > 0 in governed cohort mart",
}
CONTAINED_INCIDENT_CODES = [
    "duplicate_android_client_events",
    "missing_android_session_ends",
    "purchase_refund_status_lag",
    "events_before_install",
    "invalid_membership_interval",
    "ambiguous_intraday_configuration_join",
]

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
print(f"Versions: {package_versions}")

# %% [markdown]
# ## Context & methods
#
# ### Key assumptions
#
# - Robust activity is the governed primary D7 signal.
# - Completed sessions are a sensitivity signal because missing Android session ends can
#   suppress them.
# - Pre-update acquisition-channel shares are the standardization weights.
# - Cohort rows are resampled within period/channel strata for the uncertainty interval.
# - Configuration timing and the acquisition-mix shift are observational confounders.

# %% [markdown]
# ## Data
#
# The loader opens DuckDB read-only and runs one bounded query against
# `main_live_strategy.mart_live_strategy__d7_diagnostic_inputs`.

# %%
diagnostic = load_diagnostic_inputs(DB_PATH)
if diagnostic.empty:
    raise ValueError("Governed diagnostic mart returned no rows")

required_periods = set(FILTERS["periods"])
required_signals = set(FILTERS["retention_signals"])
if set(diagnostic["period"]) != required_periods:
    raise ValueError("Diagnostic input does not contain exactly the governed periods")
if set(diagnostic["retention_signal"]) != required_signals:
    raise ValueError("Diagnostic input does not contain both governed retention signals")
if (diagnostic["eligible_players"] <= 0).any():
    raise ValueError("Diagnostic mart contains a nonpositive eligible cohort row")

signal_key = [
    "install_date_utc",
    "period",
    "platform",
    "country_code",
    "acquisition_channel",
    "config_version_id",
]
signal_counts = diagnostic.groupby(signal_key, dropna=False)["retention_signal"].nunique()
if not signal_counts.eq(2).all():
    raise ValueError("Robust and completed-session signals do not share the same cohort keys")

display(diagnostic.head(10))
print(f"Cohort-signal rows: {len(diagnostic):,}")
print(
    "Install range: "
    f"{pd.to_datetime(diagnostic['install_date_utc']).min().date()} to "
    f"{pd.to_datetime(diagnostic['install_date_utc']).max().date()}"
)
print("Containment check: governed rows are mature and signal keys reconcile.")
print("Known upstream incident context (documented, not independently queried here):")
for incident_code in CONTAINED_INCIDENT_CODES:
    print(f"- {incident_code}")

# %% [markdown]
# ## Results

# %%
overall = (
    diagnostic.groupby(["period", "retention_signal"], as_index=False)
    .agg(
        eligible_players=("eligible_players", "sum"),
        retained_players=("retained_players", "sum"),
    )
    .assign(
        retention_rate=lambda frame: frame["retained_players"]
        / frame["eligible_players"]
    )
)
display(overall)

robust_overall = overall.loc[overall["retention_signal"].eq("robust_activity")].set_index(
    "period"
)
pre_rate = float(robust_overall.loc["pre_update", "retention_rate"])
post_rate = float(robust_overall.loc["post_update", "retention_rate"])

# %%
segment_trends = (
    diagnostic.loc[diagnostic["retention_signal"].eq("robust_activity")]
    .groupby(["period", "platform", "acquisition_channel"], as_index=False)
    .agg(
        eligible_players=("eligible_players", "sum"),
        retained_players=("retained_players", "sum"),
    )
    .assign(
        retention_rate=lambda frame: frame["retained_players"]
        / frame["eligible_players"]
    )
)
display(segment_trends)

plot_frame = overall.pivot(
    index="period", columns="retention_signal", values="retention_rate"
).reindex(["pre_update", "post_update"])
axis = plot_frame.plot.bar(figsize=(8, 4), ylim=(0, max(0.3, plot_frame.max().max() * 1.2)))
axis.set_title("D7 retention by period and governed signal")
axis.set_xlabel("Period")
axis.set_ylabel("Retention rate")
axis.legend(title="Signal")
plt.tight_layout()
FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(FIGURE_PATH, dpi=150)
plt.show()
plt.close()

# %%
standardized_post_rate = standardized_retention(
    diagnostic, "robust_activity", "pre_update"
)
contributions = d7_contribution_table(diagnostic)
display(contributions)

contribution_values = contributions.set_index("component")["value"]
observed_change = float(contribution_values["observed_change"])
mix_contribution = float(contribution_values["acquisition_mix"])
within_channel_change = float(contribution_values["within_channel_change"])
instrumentation_sensitivity = float(
    contribution_values["android_instrumentation_sensitivity"]
)

# %%
progression_rows = diagnostic.loc[
    diagnostic["retention_signal"].eq("robust_activity")
].copy()


def spearman_if_identifiable(left: pd.Series, right: pd.Series) -> float | None:
    complete = pd.concat([left, right], axis="columns").dropna()
    if len(complete) < 2 or complete.iloc[:, 0].nunique() < 2:
        return None
    value = complete.iloc[:, 0].corr(complete.iloc[:, 1], method="spearman")
    return None if pd.isna(value) else float(value)

progression_summary = {
    "upgrade_attempts_spearman": spearman_if_identifiable(
        progression_rows["median_upgrade_attempts"], progression_rows["retention_rate"]
    ),
    "progression_velocity_spearman": spearman_if_identifiable(
        progression_rows["median_progression_velocity"], progression_rows["retention_rate"]
    ),
}
display(pd.DataFrame([progression_summary]))

progression_notes = []
for measure, association in progression_summary.items():
    readable_measure = measure.removesuffix("_spearman").replace("_", " ")
    if association is None:
        progression_notes.append(
            f"The cohort-level {readable_measure} association is not identifiable "
            "because the published values lack sufficient variation."
        )
    else:
        progression_notes.append(
            f"The cohort-level Spearman association for {readable_measure} is "
            f"{association:+.3f}; this ecological association does not identify "
            "a player-level or causal effect."
        )

# %%
confidence_interval = bootstrap_difference_ci(
    diagnostic,
    seed=BOOTSTRAP_SEED,
    draws=BOOTSTRAP_DRAWS,
)
print(
    f"Observed robust D7 change: {observed_change:+.2%}; "
    f"stratified cohort-row bootstrap 95% CI "
    f"[{confidence_interval[0]:+.2%}, {confidence_interval[1]:+.2%}]"
)

# %% [markdown]
# ## Takeaways
#
# The following boundary is intentional: facts are direct governed outputs; inferences are
# associations; limitations identify what this design cannot establish.

# %%
observed_facts = [
    f"Robust D7 retention moved from {pre_rate:.2%} to {post_rate:.2%}.",
    f"The observed change was {observed_change:+.2%}.",
    f"Holding the pre-update channel mix fixed gives {standardized_post_rate:.2%} post-update.",
    f"The acquisition-mix component was {mix_contribution:+.2%}.",
    f"Android completed-session sensitivity was {instrumentation_sensitivity:+.2%}.",
]
inferences = [
    (
        "The within-channel residual is descriptive; it also contains uncontrolled shifts "
        "in platform, country, configuration version, and other cohort composition."
    ),
    "The mix shift contributes to the aggregate movement and should be controlled in decisions.",
    "The Android signal gap is measurement sensitivity, not evidence of lower player engagement.",
    *progression_notes,
]
limitations = [
    "The season update and configuration timing were not randomized.",
    "Acquisition mix changed across periods and remains an observational confounder.",
    "The bootstrap resamples aggregated cohort rows, not individual players.",
    (
        "Progression checks use cohort-level medians and are ecological associations; they "
        "cannot identify a treatment effect or player-level relationship."
    ),
    (
        "Incident codes are documented context inherited from governed upstream models; "
        "this notebook does not independently query the incident mart."
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
robust_rows = diagnostic.loc[diagnostic["retention_signal"].eq("robust_activity")]
results = {
    "metadata": {
        "input_relations": [INPUT_RELATION],
        "filters": FILTERS,
        "code_version": code_version,
        "executed_at_utc": executed_at_utc,
        "package_versions": package_versions,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "contained_incident_codes": CONTAINED_INCIDENT_CODES,
    },
    "population": {
        "install_date_min": str(pd.to_datetime(diagnostic["install_date_utc"]).min().date()),
        "install_date_max": str(pd.to_datetime(diagnostic["install_date_utc"]).max().date()),
        "pre_update_eligible_players": int(
            robust_rows.loc[robust_rows["period"].eq("pre_update"), "eligible_players"].sum()
        ),
        "post_update_eligible_players": int(
            robust_rows.loc[robust_rows["period"].eq("post_update"), "eligible_players"].sum()
        ),
    },
    "results": {
        "pre_update_d7_retention": pre_rate,
        "post_update_d7_retention": post_rate,
        "observed_d7_change": observed_change,
        "pre_mix_standardized_post_d7_retention": standardized_post_rate,
        "acquisition_mix_contribution": mix_contribution,
        "within_channel_association": within_channel_change,
        "android_instrumentation_sensitivity": instrumentation_sensitivity,
        "bootstrap_difference_ci_95": list(confidence_interval),
        "progression_friction_associations": progression_summary,
    },
    "observed_facts": observed_facts,
    "inferences": inferences,
    "limitations": limitations,
}

REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORT_PATH.write_text(
    json.dumps(results, indent=2, allow_nan=False) + "\n",
    encoding="utf-8",
)
print(f"Wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
