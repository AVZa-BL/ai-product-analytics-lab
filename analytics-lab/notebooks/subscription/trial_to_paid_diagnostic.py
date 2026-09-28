# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.5
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Trial-to-paid conversion diagnostic
#
# ## tl;dr
#
# This reproducible diagnostic separates the observed mature-cohort conversion decline from acquisition mix, activation, payment failures, plan mix, and cohort-maturity effects. It is descriptive and does not claim that any product change caused the decline.
#

# %% [markdown]
# ## Context & Methods
#
# ### Key Assumptions
#
# - The designed decline begins on April 19, 2026 (day 108 of the 180-day seeded scenario).
# - Only mature trial cohorts are included.
# - A conversion is a paid start occurring between trial start and the configured number of days after scheduled trial end.
# - The standardized comparison holds the pre-decline acquisition-channel mix fixed.
# - Confidence intervals use a normal approximation to the binomial proportion and are descriptive.
#

# %%
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display

working_path = Path.cwd().resolve()
repo_root = next(
    path for path in [working_path, *working_path.parents]
    if (path / "game_analytics").is_dir() and (path / "pyproject.toml").exists()
)
db_path = repo_root / "game_analytics" / "dev.duckdb"
__import__("os").chdir(repo_root / "game_analytics")

source_models = [
    "mart_subscription__trial_conversion_diagnostic",
    "mart_subscription__kpis_daily",
    "fct_subscription__payments",
    "int_subscription__quality_audit",
    "int_subscription__trial_cohorts",
    "dim_subscription__users",
]
execution_date = datetime.now(timezone.utc).isoformat()
filters = {
    "mature_trials_only": True,
    "conversion_window_days": 3,
    "decline_start_date": "2026-04-19",
}
code_version = subprocess.check_output(
    ["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True
).strip()

connection = duckdb.connect(str(db_path), read_only=True)
print({
    "source_models": source_models,
    "execution_date": execution_date,
    "filters": filters,
    "code_version": code_version,
})


# %% [markdown]
# ## Data
#
# Load governed aggregate outputs, the scenario quality audit, and bounded trial-level fields required for conversion-window sensitivity.
#

# %%
diagnostic = connection.sql("""
    select *
    from main_subscription.mart_subscription__trial_conversion_diagnostic
    order by cohort_date, acquisition_channel, campaign_id, plan_id, activation_segment
""").df()

kpis = connection.sql("""
    select metric_date, trial_to_paid_numerator, trial_to_paid_denominator,
           trial_to_paid_rate, data_quality_status
    from main_subscription.mart_subscription__kpis_daily
    where trial_to_paid_denominator is not null
    order by metric_date
""").df()

quality = connection.sql("select * from main_subscription.int_subscription__quality_audit").df()

trial_detail = connection.sql("""
    select
        t.subscription_id,
        t.cohort_date,
        t.trial_start_at,
        t.scheduled_trial_end_at,
        t.paid_start_at,
        t.plan_id,
        t.maturity_cutoff_date,
        u.acquisition_channel,
        u.campaign_id,
        case
            when u.activation_at >= u.signup_at
             and u.activation_at <= t.scheduled_trial_end_at
            then 'activated_before_trial_end'
            else 'not_activated_before_trial_end'
        end as activation_segment,
        exists (
            select 1 from main_subscription.fct_subscription__payments p
            where p.subscription_id = t.subscription_id
              and p.is_failed
              and p.payment_at >= t.trial_start_at
              and p.payment_at <= t.scheduled_trial_end_at + interval '3 days'
        ) as has_payment_failure
    from main_subscription.int_subscription__trial_cohorts t
    join main_subscription.dim_subscription__users u using (user_id)
    where t.is_mature
    order by t.cohort_date, t.subscription_id
""").df()

maturity_cutoff_date = pd.to_datetime(trial_detail["maturity_cutoff_date"]).max().date()
decline_start_date = pd.Timestamp(filters["decline_start_date"])
trial_detail["period"] = np.where(
    pd.to_datetime(trial_detail["cohort_date"]) < decline_start_date,
    "Pre-decline",
    "Post-decline",
)
trial_detail["converted_3d"] = (
    trial_detail["paid_start_at"].notna()
    & (trial_detail["paid_start_at"] >= trial_detail["trial_start_at"])
    & (
        trial_detail["paid_start_at"]
        <= trial_detail["scheduled_trial_end_at"] + pd.Timedelta(days=3)
    )
)

print(f"Mature trials: {len(trial_detail):,}")
print(f"Latest maturity cutoff date: {maturity_cutoff_date}")
display(quality)


# %% [markdown]
# ## Results
#
# ### 1. Mature-cohort conversion and uncertainty
#

# %%
def summarize_rate(frame: pd.DataFrame, converted_col: str = "converted_3d") -> pd.DataFrame:
    result = (
        frame.groupby("period", observed=True)[converted_col]
        .agg(["sum", "count"])
        .rename(columns={"sum": "paid_conversions", "count": "eligible_trials"})
        .reset_index()
    )
    result["rate"] = result["paid_conversions"] / result["eligible_trials"]
    se = np.sqrt(result["rate"] * (1 - result["rate"]) / result["eligible_trials"])
    result["ci_low"] = (result["rate"] - 1.96 * se).clip(lower=0)
    result["ci_high"] = (result["rate"] + 1.96 * se).clip(upper=1)
    return result

period_order = ["Pre-decline", "Post-decline"]
overall = summarize_rate(trial_detail).set_index("period").loc[period_order].reset_index()
pre_rate, post_rate = overall["rate"].tolist()
decline_pp = (pre_rate - post_rate) * 100
display(overall.style.format({"rate": "{:.2%}", "ci_low": "{:.2%}", "ci_high": "{:.2%}"}))
print(f"Observed decline: {decline_pp:.2f} percentage points")

fig, ax = plt.subplots(figsize=(7.5, 4.5))
palette = ["#3973AC", "#D08A2E"]
errors = np.vstack([overall["rate"] - overall["ci_low"], overall["ci_high"] - overall["rate"]])
ax.bar(overall["period"], overall["rate"], color=palette, edgecolor="#263238", linewidth=0.8)
ax.errorbar(overall["period"], overall["rate"], yerr=errors, fmt="none", ecolor="#263238", capsize=5)
ax.set_title("Mature trial-to-paid conversion", loc="left", weight="bold")
ax.set_ylabel("Conversion rate")
ax.set_ylim(0, max(0.5, float(overall["ci_high"].max()) + 0.05))
ax.yaxis.set_major_formatter(lambda value, _position: f"{value:.0%}")
ax.grid(axis="y", color="#D9DEE3", linewidth=0.7)
ax.set_axisbelow(True)
plt.tight_layout()
plt.show()


# %% [markdown]
# ### 2. Channel-mix standardization and segment diagnostics
#

# %%
channel = (
    trial_detail.groupby(["period", "acquisition_channel"], observed=True)["converted_3d"]
    .agg(["sum", "count"])
    .rename(columns={"sum": "paid_conversions", "count": "eligible_trials"})
    .reset_index()
)
channel["rate"] = channel["paid_conversions"] / channel["eligible_trials"]

pre_channel = channel[channel["period"] == "Pre-decline"].set_index("acquisition_channel")
post_channel = channel[channel["period"] == "Post-decline"].set_index("acquisition_channel")
pre_weights = pre_channel["eligible_trials"] / pre_channel["eligible_trials"].sum()
standardized_post_rate = float(
    (pre_weights * post_channel["rate"].reindex(pre_weights.index)).sum()
)
mix_effect_pp = (post_rate - standardized_post_rate) * 100
within_channel_effect_pp = (standardized_post_rate - pre_rate) * 100

standardization = pd.DataFrame({
    "comparison": ["Observed pre", "Observed post", "Post at pre channel mix"],
    "rate": [pre_rate, post_rate, standardized_post_rate],
})
display(standardization.style.format({"rate": "{:.2%}"}))
print(f"Channel-mix contribution to post rate: {mix_effect_pp:+.2f} pp")
print(f"Within-channel / residual contribution: {within_channel_effect_pp:+.2f} pp")

def segment_view(column: str) -> pd.DataFrame:
    output = (
        trial_detail.groupby([column, "period"], dropna=False, observed=True)["converted_3d"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "paid_conversions", "count": "eligible_trials"})
        .reset_index()
    )
    output["trial_to_paid_rate"] = output["paid_conversions"] / output["eligible_trials"]
    return output.sort_values([column, "period"])

for dimension in ["acquisition_channel", "campaign_id", "activation_segment", "has_payment_failure", "plan_id"]:
    print(f"Diagnostic by {dimension}")
    display(segment_view(dimension).style.format({"trial_to_paid_rate": "{:.2%}"}))


# %% [markdown]
# ### 3. Conversion-window sensitivity and data-quality qualification
#

# %%
sensitivity_rows = []
for window_days in [2, 3, 7]:
    converted = (
        trial_detail["paid_start_at"].notna()
        & (trial_detail["paid_start_at"] >= trial_detail["trial_start_at"])
        & (
            trial_detail["paid_start_at"]
            <= trial_detail["scheduled_trial_end_at"] + pd.Timedelta(days=window_days)
        )
    )
    working = trial_detail.assign(converted_window=converted)
    result = summarize_rate(working, "converted_window").set_index("period")
    sensitivity_rows.append({
        "conversion_window_days": window_days,
        "pre_rate": result.loc["Pre-decline", "rate"],
        "post_rate": result.loc["Post-decline", "rate"],
        "decline_pp": (
            result.loc["Pre-decline", "rate"] - result.loc["Post-decline", "rate"]
        ) * 100,
    })

sensitivity = pd.DataFrame(sensitivity_rows)
display(sensitivity.style.format({"pre_rate": "{:.2%}", "post_rate": "{:.2%}", "decline_pp": "{:.2f}"}))

quality_counts = quality.iloc[0].to_dict()
print("Quality-audit counts:", quality_counts)
print("Payment failure incidence by period:")
display(
    trial_detail.groupby("period", observed=True)["has_payment_failure"]
    .agg(["sum", "count"])
    .assign(rate=lambda frame: frame["sum"] / frame["count"])
    .style.format({"rate": "{:.2%}"})
)


# %% [markdown]
# ## Takeaways
#
# - The notebook quantifies the mature-cohort decline and its binomial uncertainty directly from governed dbt outputs.
# - Holding the pre-decline channel mix fixed isolates the small composition component from the larger within-channel/residual component.
# - Payment failures, activation status, plan, campaign, and conversion-window sensitivity are shown as diagnostics, not causal estimates.
# - The five intentional data-quality conditions remain visible beside the findings. The corresponding incident record defines their containment.
# - This is synthetic observational evidence. It supports a reversible experiment and measurement repair, not a causal claim.
#
