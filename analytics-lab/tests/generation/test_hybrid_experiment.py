"""The synthetic offer-page experiment: its tables, and each problem planted in it.

Statistical claims are checked at a reference scale of 5,000 players, where the planted
problems are large enough to detect. At the CI scale of 1,000 they are present but too small
to test, which the structural checks below confirm.
"""

import functools
import hashlib
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.hybrid_experiment import (
    ARMS,
    EXPERIMENT_ID,
    PLANTED,
    ExperimentSimulation,
    experiment_window,
    ground_truth,
    simulate_experiment,
)
from analytics_lab.generation.hybrid_subscription import generate

DAY = pd.to_timedelta(1, unit="D")


def config(scale: int, seed: int = 42, days: int = 180) -> GenerationConfig:
    return GenerationConfig(
        scenario="hybrid_subscription",
        seed=seed,
        start_date=date(2026, 1, 1),
        days=days,
        scale=scale,
        output_dir=Path("data/raw"),
    )


@functools.cache
def scenario_tables(cfg: GenerationConfig) -> dict[str, pd.DataFrame]:
    """The scenario's own tables. Cached: the generator is slow and deterministic."""
    return generate(cfg)


@functools.cache
def inputs(cfg: GenerationConfig) -> tuple[pd.DataFrame, frozenset[str], pd.Timestamp]:
    """Players, subscribers and launch time, as the scenario generator derives them.

    Cached: the scenario generator is slow and deterministic, and the experiment only reads it.
    """
    tables = scenario_tables(cfg)
    started = tables["subscription_events"].query("event_type == 'started'")
    launch = pd.Timestamp(cfg.start_date, tz="UTC") + max(1, cfg.days // 2) * DAY
    return tables["players"], frozenset(started.player_id), launch


def simulate(cfg: GenerationConfig, planted=PLANTED) -> ExperimentSimulation:
    players, subscribers, launch = inputs(cfg)
    return simulate_experiment(cfg, players, subscribers, launch, "run_1", planted)


@pytest.fixture(scope="module")
def reference() -> dict:
    """Seed 42, 5,000 players: the scale the statistical checks are written for."""
    cfg = config(5_000)
    players, subscribers, launch = inputs(cfg)
    return {
        "cfg": cfg,
        "players": players.set_index("player_id"),
        "subscribers": subscribers,
        "launch": launch,
        "sim": simulate_experiment(cfg, players, subscribers, launch, "run_1"),
    }


@pytest.fixture(scope="module")
def small() -> ExperimentSimulation:
    return simulate(config(1_000))


def assigned(sim: ExperimentSimulation) -> pd.DataFrame:
    return sim.tables["experiment_assignments"]


def outcomes(sim: ExperimentSimulation) -> pd.DataFrame:
    return sim.tables["experiment_outcomes"]


# --- Tables and contract ---------------------------------------------------------------


def test_the_columns_are_the_documented_ones(small: ExperimentSimulation) -> None:
    assert list(small.tables["experiment_assignments"].columns) == [
        "assignment_id",
        "experiment_id",
        "player_id",
        "arm",
        "assigned_at_utc",
        "arm_config_version",
        "first_seen_at_utc",
        "scenario_run_id",
    ]
    assert list(small.tables["experiment_exposures"].columns) == [
        "exposure_id",
        "experiment_id",
        "player_id",
        "arm",
        "exposed_at_utc",
        "arm_config_version",
        "exposure_surface",
        "scenario_run_id",
    ]
    assert list(small.tables["experiment_outcomes"].columns) == [
        "experiment_id",
        "player_id",
        "window_start_utc",
        "window_end_utc",
        "sessions_7d",
        "purchases_7d",
        "revenue_usd_7d",
        "first_purchase_at_utc",
        "sessions_pre_7d",
        "revenue_usd_pre_7d",
        "scenario_run_id",
    ]


def test_the_pre_period_measures_follow_the_players_engagement_and_not_the_arm(
    reference: dict,
) -> None:
    """What a covariate adjustment (CUPED) relies on: the pre-period is correlated with the
    outcome through the player's engagement (by the generator's own model, not tuned), is
    unaffected by the arm, and does not change the older columns."""
    frame = outcomes(reference["sim"]).merge(assigned(reference["sim"])[["player_id", "arm"]])

    # sessions: Poisson counts around 4 x engagement, engagement lognormal with sigma 0.5, so the
    # correlation is Var(4 E) / (Var(4 E) + E[4 E]) = 0.56 in theory; revenue is dominated by the
    # heavy-tailed amounts, so its pre-period carries almost nothing
    assert 0.52 < frame.sessions_7d.corr(frame.sessions_pre_7d) < 0.62
    assert abs(frame.revenue_usd_7d.corr(frame.revenue_usd_pre_7d)) < 0.05
    for column in ("sessions_pre_7d", "revenue_usd_pre_7d"):
        groups = [frame.loc[frame.arm == arm, column] for arm in ARMS]
        assert stats.f_oneway(*groups).pvalue > 0.01, column  # balanced across arms
    assert ground_truth(reference["launch"])["pre_period"]["columns"] == [
        "sessions_pre_7d",
        "revenue_usd_pre_7d",
    ]


def test_each_assignment_says_when_its_player_was_first_seen(reference: dict) -> None:
    frame = assigned(reference["sim"]).set_index("player_id")

    first_seen = reference["players"].acquired_at_utc.loc[frame.index]

    assert (frame.first_seen_at_utc == first_seen).all()


# --- Determinism and independence ------------------------------------------------------


def test_a_scenario_too_short_for_the_experiment_is_refused() -> None:
    cfg = config(200, days=PLANTED.min_scenario_days - 1)
    players, subscribers, launch = inputs(config(200))

    with pytest.raises(ValueError, match="at least 90 days, got 89"):
        simulate_experiment(cfg, players, subscribers, launch, "run_1")


# --- Timing ----------------------------------------------------------------------------


def test_assignments_fall_in_the_window_and_everything_ends_before_the_scenario_does(
    reference: dict,
) -> None:
    sim, launch, cfg = reference["sim"], reference["launch"], reference["cfg"]
    start, end = experiment_window(launch)
    scenario_end = pd.Timestamp(cfg.start_date, tz="UTC") + cfg.days * DAY

    assert start == launch + 10 * DAY and end == start + 21 * DAY
    assert assigned(sim).assigned_at_utc.between(start, end, inclusive="left").all()
    assert (outcomes(sim).window_end_utc - outcomes(sim).window_start_utc == 7 * DAY).all()
    assert sim.tables["experiment_exposures"].exposed_at_utc.max() < scenario_end


# --- Bucketing -------------------------------------------------------------------------


def test_arms_follow_the_documented_hash_rule(reference: dict) -> None:
    """Recomputed here independently of the generator."""
    a = assigned(reference["sim"])
    salt = ground_truth(reference["launch"])["bucketing_salt"]

    def expected(player_id: str) -> str:
        return ARMS[int(hashlib.sha256(f"{salt}:{player_id}".encode()).hexdigest()[:8], 16) % 3]

    assert (a.player_id.map(expected) == a.arm).all()


# --- Planted problem 1: sample-ratio mismatch ------------------------------------------


# --- Planted problem 2: exposure after purchase ----------------------------------------


def first_exposure_vs_purchase(sim: ExperimentSimulation) -> pd.DataFrame:
    first = sim.tables["experiment_exposures"].groupby("player_id").exposed_at_utc.min()
    table = outcomes(sim).set_index("player_id")
    return pd.DataFrame({"first_exposure": first, "first_purchase": table.first_purchase_at_utc})


def test_late_exposure_players_are_first_exposed_after_their_first_purchase(
    reference: dict,
) -> None:
    sim = reference["sim"]
    both = first_exposure_vs_purchase(sim)
    late = list(sim.late_exposure_player_ids)
    others = both.drop(index=late)

    assert late
    assert (both.loc[late].first_exposure > both.loc[late].first_purchase).all()
    # Everyone else is first exposed before buying (or never buys).
    assert (others.first_purchase.isna() | (others.first_exposure < others.first_purchase)).all()


# --- Planted problem 3: heavy-tailed revenue -------------------------------------------


# --- Planted problem 4: novelty that reverses ------------------------------------------


# --- Planted problem 5: configuration change -------------------------------------------


def test_arm_b_moves_to_version_two_at_the_change_time_and_no_other_arm_does(
    reference: dict,
) -> None:
    sim, launch = reference["sim"], reference["launch"]
    change_at = experiment_window(launch)[0] + PLANTED.config_change_day * DAY
    a, e = assigned(sim), sim.tables["experiment_exposures"]

    expected_a = np.where((a.arm == "variant_b") & (a.assigned_at_utc >= change_at), 2, 1)
    expected_e = np.where((e.arm == "variant_b") & (e.exposed_at_utc >= change_at), 2, 1)
    assert (a.arm_config_version == expected_a).all()
    assert (e.arm_config_version == expected_e).all()
    assert set(a[a.arm != "variant_b"].arm_config_version) == {1}
    assert set(a[a.arm == "variant_b"].arm_config_version) == {1, 2}


def test_the_change_is_visible_in_the_ground_truth(reference: dict) -> None:
    truth = ground_truth(reference["launch"])["config_change"]
    start, _ = experiment_window(reference["launch"])

    assert truth["arm"] == "variant_b" and (truth["from_version"], truth["to_version"]) == (1, 2)
    assert truth["at_utc"] == (start + 12 * DAY).isoformat()


# --- Exposures --------------------------------------------------------------------------


def test_ids_are_numbered_from_one_in_time_order(small: ExperimentSimulation) -> None:
    assert assigned(small).assignment_id.iloc[0] == "assignment_0000001"
    assert small.tables["experiment_exposures"].exposure_id.iloc[0] == "exposure_0000001"
    assert assigned(small).assignment_id.is_monotonic_increasing


def test_some_players_are_exposed_more_than_once_and_repeats_come_later(
    reference: dict,
) -> None:
    e = reference["sim"].tables["experiment_exposures"]
    per_player = e.groupby("player_id").size()
    ordered = e.sort_values("exposed_at_utc").groupby("player_id").exposed_at_utc
    spread = (ordered.max() - ordered.min())[per_player > 1]

    assert set(per_player) == {1, 2, 3}
    assert (per_player > 1).mean() == pytest.approx(0.30, abs=0.03)
    assert (spread >= pd.to_timedelta(1, unit="h")).all()
    assert (spread <= pd.to_timedelta(144, unit="h")).all()


def test_a_player_not_exposed_late_is_first_exposed_within_hours_of_assignment(
    reference: dict,
) -> None:
    sim = reference["sim"]
    first = sim.tables["experiment_exposures"].groupby("player_id").exposed_at_utc.min()
    when = assigned(sim).set_index("player_id").assigned_at_utc
    normal = first.drop(index=list(sim.late_exposure_player_ids))
    delay = normal - when.reindex(normal.index)

    assert (delay >= pd.to_timedelta(0, unit="s")).all()
    assert delay.max() < pd.to_timedelta(6, unit="h")
    assert delay.median() < pd.to_timedelta(10, unit="min")


# --- The plan drives the data ----------------------------------------------------------


def test_the_experiments_random_stream_is_not_the_scenarios(reference: dict) -> None:
    """If it were, the experiment's draws would repeat the scenario's own."""
    engagement = reference["sim"].latent.engagement.to_numpy()
    scenarios = np.random.default_rng(reference["cfg"].seed).lognormal(
        0.0, PLANTED.engagement_sigma, len(engagement)
    )

    assert not np.allclose(engagement, scenarios)
    assert abs(np.corrcoef(engagement, scenarios)[0, 1]) < 0.1


def test_buyers_with_several_purchases_have_an_earlier_first_purchase(reference: dict) -> None:
    """The logged time is the earliest purchase, so more purchases means an earlier first."""
    o = outcomes(reference["sim"])
    buyers = o[o.purchases_7d > 0]
    fraction = (buyers.first_purchase_at_utc - buyers.window_start_utc) / (
        buyers.window_end_utc - buyers.window_start_utc
    )

    assert (
        fraction[buyers.purchases_7d >= 2].mean() < fraction[buyers.purchases_7d == 1].mean() - 0.08
    )


def test_most_players_lost_to_the_bug_had_few_sessions(reference: dict) -> None:
    latent = reference["sim"].latent
    lost = latent.loc[list(reference["sim"].dropped_player_ids)]
    share_below_median = (lost.sessions_7d < latent.sessions_7d.median()).mean()

    # Planned: 0.90 / (0.90 + 0.40) = 69% of those lost had below-median sessions.
    assert share_below_median == pytest.approx(0.69, abs=0.08)


# --- The plan, as data -----------------------------------------------------------------


def test_the_ground_truth_describes_what_was_planted(reference: dict) -> None:
    truth = ground_truth(reference["launch"])
    start, end = experiment_window(reference["launch"])

    assert truth["experiment_id"] == EXPERIMENT_ID and truth["arms"] == list(ARMS)
    assert truth["window_start_utc"] == start.isoformat()
    assert truth["window_end_utc"] == end.isoformat()
    srm = truth["sample_ratio_mismatch"]
    assert (srm["arm"], srm["platform"]) == ("variant_c", "android")
    assert srm["expected_overall_drop_in_affected_cell"] == pytest.approx(0.65)
    assert truth["novelty"]["purchase_multiplier_by_week"] == [1.45, 1.05, 0.80]
    assert truth["exposure_after_purchase"]["share_of_purchasers"] == 0.35
    assert truth["heavy_tailed_revenue"]["lognormal_sigma"] == 1.7
    assert truth["true_effect"] == {"variant_c": "none"}


# --- The figures quoted in the documentation --------------------------------------------

EXPERIMENT_DOC = Path("docs/metrics/hybrid_subscription_experiment.md")


def outcome_figures(frame: pd.DataFrame, window_start: pd.Timestamp) -> dict:
    """The outcome figures the readout document quotes, for one population of players.

    Run on every assigned player (what the generator produces) and on the eligible players
    (what the marts cover), so that the document can show both without either going stale.
    """
    shares = {}
    for arm in ARMS:
        revenue = frame[frame.arm == arm].revenue_usd_7d.sort_values(ascending=False).to_numpy()
        shares[arm] = revenue[: (len(revenue) + 99) // 100].sum() / revenue.sum()

    week = 1 + (pd.to_datetime(frame.assigned_at_utc) - window_start).dt.days // 7
    by_week = frame.groupby([week.rename("week"), "arm"]).sessions_7d
    mean = by_week.mean().unstack()
    spread, size = by_week.std().unstack(), by_week.count().unstack()
    lift = (mean.variant_b - mean.control).loc[[1, 2, 3]]
    standard_error = np.sqrt(
        spread.variant_b**2 / size.variant_b + spread.control**2 / size.control
    ).loc[[1, 2, 3]]

    onset = window_start + PLANTED.srm_onset_day * DAY
    after = frame[pd.to_datetime(frame.assigned_at_utc) >= onset].groupby("arm").sessions_7d.mean()
    return {
        "shares": shares,
        "lift": lift,
        "standard_error": standard_error,
        "bias": after.variant_c - after.control,
    }


def test_the_experiment_document_quotes_figures_the_generator_still_produces(
    reference: dict, small: ExperimentSimulation
) -> None:
    """Every figure in the document's planted-problems table is recomputed here.

    That is done for both populations, all assigned players and eligible players. So are the
    CI-scale top-1% count and the correlation bound, and each must appear in the document
    verbatim. The standard error and the correlation bound are also checked as ranges.
    Statements about other seeds are not recomputed, and the document says so.

    Figures written down once and never re-checked went stale in an earlier description of
    this work, which is why this guard exists.
    """
    text = EXPERIMENT_DOC.read_text()
    sim = reference["sim"]
    assignments, outcome = assigned(sim), outcomes(sim)
    merged = assignments.merge(outcome, on="player_id")
    n = len(assignments)
    counts = assignments.arm.value_counts().reindex(ARMS)
    purchasers = int((outcome.purchases_7d > 0).sum())
    late = len(sim.late_exposure_player_ids)
    revenue = outcome.revenue_usd_7d.sort_values(ascending=False).to_numpy()
    top_share = revenue[: -(-len(revenue) // 100)].sum() / revenue.sum()

    # Every logged player is exposed, so "eligible" is "not first exposed after the first purchase".
    assert set(assignments.player_id) <= set(sim.tables["experiment_exposures"].player_id)
    window_start = experiment_window(reference["launch"])[0]
    everyone = outcome_figures(merged, window_start)
    eligible = outcome_figures(
        merged[~merged.player_id.isin(sim.late_exposure_player_ids)], window_start
    )

    small_assigned = assigned(small)
    small_late = len(small.late_exposure_player_ids)
    small_p = stats.chisquare(small_assigned.arm.value_counts().reindex(ARMS)).pvalue
    small_eligible = small_assigned.arm.value_counts().reindex(ARMS) - (
        small_assigned[small_assigned.player_id.isin(small.late_exposure_player_ids)]
        .arm.value_counts()
        .reindex(ARMS)
        .fillna(0)
    )
    top_counts = {(int(count) + 99) // 100 for count in small_eligible}
    assert len(top_counts) == 1, "the document says the CI-scale top 1% is the same for every arm"
    version_two = int(
        ((assignments.arm == "variant_b") & (assignments.arm_config_version == 2)).sum()
    )

    sessions = scenario_tables(reference["cfg"])["sessions"]
    pre = merged.merge(
        sessions.assign(started=pd.to_datetime(sessions.started_at_utc))[["player_id", "started"]],
        on="player_id",
    )
    assigned_at = pd.to_datetime(pre.assigned_at_utc)
    in_window = (pre.started >= assigned_at - 28 * DAY) & (pre.started < assigned_at)
    pre_sessions = in_window.groupby(pre.player_id).sum().reindex(merged.player_id).to_numpy()
    correlations = {
        column: abs(np.corrcoef(pre_sessions, merged[column])[0, 1])
        for column in ("sessions_7d", "purchases_7d", "revenue_usd_7d")
    }

    def signed(values: pd.Series) -> str:
        return ", ".join(f"{value:+.2f}" for value in values)

    words = {1: "one", 2: "two", 3: "three"}
    quoted = {
        "arm counts": " / ".join(f"{counts[arm]:,}" for arm in ARMS) + f" of {n:,}",
        "reference p": f"p = {stats.chisquare(counts).pvalue:.1e}",
        "CI scale p": f"(561 assigned players) p = {small_p:.3f}",
        "late exposure": f"{late} of {n:,} assigned players ({late / n:.1%})",
        "late share of purchasers": f"{late / purchasers:.1%} of the {purchasers} purchasers",
        "CI late exposure": (
            f"{small_late} of {len(small_assigned)} ({small_late / len(small_assigned):.1%})"
        ),
        "top 1% share, all assigned": f"hold {top_share:.1%} of revenue",
        "top 1% share, eligible per arm": (
            " / ".join(f"{eligible['shares'][arm]:.1%}" for arm in ARMS) + " of the arm's revenue"
        ),
        "kurtosis": f"excess kurtosis {stats.kurtosis(revenue):.0f}",
        "novelty, all assigned": (
            "variant_b` minus control sessions by assignment week: "
            + signed(everyone["lift"])
            + " over all assigned players"
        ),
        "novelty, eligible": signed(eligible["lift"]) + " over eligible players",
        "standard error": f"a standard error of about {everyone['standard_error'].mean():.2f}",
        "config version 2": (
            f"{version_two:,} of the {int(counts['variant_b']):,} `variant_b` players"
        ),
        "arm C bias": (
            f"is {everyone['bias']:+.2f} for seed 42 over all assigned players "
            f"and {eligible['bias']:+.2f} over eligible players"
        ),
        "CI top 1% count": f"it is {words[top_counts.pop()]} players per arm",
        "correlation bound": (
            f"absolute correlation below {math.ceil(max(correlations.values()) * 100) / 100:.2f}"
        ),
    }
    for label, figure in quoted.items():
        assert figure in text, f"{label}: the document should contain {figure!r}"

    assert len(small_assigned) == 561
    for figures in (everyone, eligible):
        assert ((figures["standard_error"] > 0.2) & (figures["standard_error"] < 0.3)).all()
        # "within one standard error of zero"
        assert abs(figures["lift"].iloc[2]) < figures["standard_error"].iloc[2]
    assert max(correlations.values()) < 0.03, correlations
