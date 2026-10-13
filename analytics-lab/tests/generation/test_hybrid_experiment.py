"""The synthetic offer-page experiment: its tables, and each problem planted in it.

Statistical claims are checked at a reference scale of 5,000 players, where the planted
problems are large enough to detect. At the CI scale of 1,000 they are present but too small
to test, which the structural checks below confirm.
"""

import dataclasses
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
    TABLE_NAMES,
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


def test_it_produces_exactly_the_three_documented_tables(small: ExperimentSimulation) -> None:
    assert tuple(small.tables) == TABLE_NAMES
    assert all(frame["scenario_run_id"].eq("run_1").all() for frame in small.tables.values())
    assert all(frame["experiment_id"].eq(EXPERIMENT_ID).all() for frame in small.tables.values())


def test_the_columns_are_the_documented_ones(small: ExperimentSimulation) -> None:
    assert list(small.tables["experiment_assignments"].columns) == [
        "assignment_id",
        "experiment_id",
        "player_id",
        "arm",
        "assigned_at_utc",
        "arm_config_version",
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
        "scenario_run_id",
    ]


def test_ids_are_unique_and_every_player_is_assigned_once(small: ExperimentSimulation) -> None:
    a, e, o = assigned(small), small.tables["experiment_exposures"], outcomes(small)

    assert a.assignment_id.is_unique and e.exposure_id.is_unique
    assert a.player_id.is_unique and o.player_id.is_unique
    assert set(a.player_id) == set(o.player_id)
    assert set(e.player_id) == set(a.player_id)
    assert set(a.arm) <= set(ARMS) and set(e.arm) <= set(ARMS)


def test_each_exposure_carries_the_arm_the_player_was_assigned(
    small: ExperimentSimulation,
) -> None:
    arm_of = assigned(small).set_index("player_id").arm
    e = small.tables["experiment_exposures"]

    assert (e.player_id.map(arm_of) == e.arm).all()


def test_timestamps_are_utc_and_the_tables_are_sorted_by_time(
    small: ExperimentSimulation,
) -> None:
    a, e = assigned(small), small.tables["experiment_exposures"]

    assert str(a.assigned_at_utc.dt.tz) == "UTC" and str(e.exposed_at_utc.dt.tz) == "UTC"
    assert a.assigned_at_utc.is_monotonic_increasing
    assert e.exposed_at_utc.is_monotonic_increasing
    assert outcomes(small).player_id.is_monotonic_increasing


# --- Determinism and independence ------------------------------------------------------


def test_the_same_inputs_give_identical_tables_and_another_seed_gives_others() -> None:
    first, second, other = simulate(config(200)), simulate(config(200)), simulate(config(200, 7))

    for name in TABLE_NAMES:
        pd.testing.assert_frame_equal(first.tables[name], second.tables[name], check_exact=True)
    assert not first.tables["experiment_assignments"].equals(other.tables["experiment_assignments"])


def test_the_experiment_does_not_read_or_move_numpys_global_state() -> None:
    cfg = config(200)
    np.random.seed(123)
    before = np.random.get_state()[1].copy()

    simulate(cfg)

    assert (np.random.get_state()[1] == before).all()


def test_changing_the_planted_loss_leaves_every_other_draw_unchanged() -> None:
    """Players who are logged in both runs have identical outcomes and exposures."""
    cfg = config(1_000)
    default = simulate(cfg)
    no_loss = simulate(
        cfg,
        dataclasses.replace(
            PLANTED,
            srm_drop_probability_low_activity=0.0,
            srm_drop_probability_high_activity=0.0,
        ),
    )

    kept = set(assigned(default).player_id)
    for name in ("experiment_outcomes", "experiment_exposures"):
        full = no_loss.tables[name]
        same = default.tables[name].drop(columns="exposure_id", errors="ignore")
        full = full[full.player_id.isin(kept)].drop(columns="exposure_id", errors="ignore")
        pd.testing.assert_frame_equal(
            same.sort_values(list(same.columns)).reset_index(drop=True),
            full.sort_values(list(full.columns)).reset_index(drop=True),
            check_exact=True,
        )


def test_every_eligible_player_is_either_assigned_or_lost(
    reference: dict,
) -> None:
    sim = reference["sim"]
    eligible = set(reference["players"].index) - reference["subscribers"]

    assert set(sim.latent.index) == eligible
    assert set(assigned(sim).player_id) | set(sim.dropped_player_ids) == eligible
    assert not set(assigned(sim).player_id) & set(sim.dropped_player_ids)
    assert not set(assigned(sim).player_id) & reference["subscribers"]


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


def test_the_window_opens_after_every_subscription_has_started(reference: dict) -> None:
    """Eligible players never subscribe, but the window also follows the launch jitter."""
    start, _ = experiment_window(reference["launch"])

    assert start > reference["launch"] + 5 * DAY


# --- Bucketing -------------------------------------------------------------------------


def test_arms_follow_the_documented_hash_rule(reference: dict) -> None:
    """Recomputed here independently of the generator."""
    a = assigned(reference["sim"])
    salt = ground_truth(reference["launch"])["bucketing_salt"]

    def expected(player_id: str) -> str:
        return ARMS[int(hashlib.sha256(f"{salt}:{player_id}".encode()).hexdigest()[:8], 16) % 3]

    assert (a.player_id.map(expected) == a.arm).all()


def test_a_different_salt_reassigns_the_players() -> None:
    cfg = config(1_000)
    other = simulate(cfg, dataclasses.replace(PLANTED, bucketing_salt="another_salt"))
    default = simulate(cfg)

    both = assigned(default).merge(assigned(other), on="player_id")
    assert 0.25 < (both.arm_x == both.arm_y).mean() < 0.42  # about one third agree by chance


# --- Planted problem 1: sample-ratio mismatch ------------------------------------------


def test_arm_c_has_a_sample_ratio_mismatch_at_the_reference_scale(reference: dict) -> None:
    counts = assigned(reference["sim"]).arm.value_counts().reindex(ARMS)

    assert stats.chisquare(counts).pvalue < 1e-6
    assert counts["variant_c"] < 0.85 * counts[["control", "variant_b"]].mean()


def test_the_other_platform_and_the_early_days_split_fairly(reference: dict) -> None:
    sim, players, launch = reference["sim"], reference["players"], reference["launch"]
    a = assigned(sim)
    onset = experiment_window(launch)[0] + PLANTED.srm_onset_day * DAY
    platform = a.player_id.map(players.platform)

    ios = a[platform == "ios"].arm.value_counts().reindex(ARMS)
    early_android = a[(platform == "android") & (a.assigned_at_utc < onset)].arm
    assert stats.chisquare(ios).pvalue > 0.01
    assert stats.chisquare(early_android.value_counts().reindex(ARMS)).pvalue > 0.01


def test_every_lost_player_is_in_the_affected_cell(reference: dict) -> None:
    sim, players = reference["sim"], reference["players"]
    lost = list(sim.dropped_player_ids)

    # Recompute each lost player's cell from the hash rule, not from the tables.
    salt = PLANTED.bucketing_salt
    arms = [ARMS[int(hashlib.sha256(f"{salt}:{p}".encode()).hexdigest()[:8], 16) % 3] for p in lost]
    assert lost and set(arms) == {"variant_c"}
    assert set(players.loc[lost].platform) == {"android"}


def test_the_share_lost_in_the_affected_cell_matches_the_plan(reference: dict) -> None:
    sim, players, launch = reference["sim"], reference["players"], reference["launch"]
    onset = experiment_window(launch)[0] + PLANTED.srm_onset_day * DAY
    cell = sim.latent.copy()
    salt = PLANTED.bucketing_salt
    cell["arm"] = [
        ARMS[int(hashlib.sha256(f"{salt}:{p}".encode()).hexdigest()[:8], 16) % 3]
        for p in cell.index
    ]
    cell["platform"] = players.platform.reindex(cell.index)
    kept = assigned(sim).set_index("player_id").assigned_at_utc
    lost = pd.Series(sim.dropped_player_ids)
    in_cell = cell[(cell.arm == "variant_c") & (cell.platform == "android")]

    # A lost player's assignment time is not logged; the cell's loss rate over all post-onset
    # members is estimated from those kept before onset and the totals.
    kept_before = (kept.reindex(in_cell.index) < onset).sum()
    kept_after = (kept.reindex(in_cell.index) >= onset).sum()
    after_total = kept_after + len(lost)
    rate = len(lost) / after_total
    expected = ground_truth(reference["launch"])["sample_ratio_mismatch"][
        "expected_overall_drop_in_affected_cell"
    ]
    assert kept_before > 0
    assert rate == pytest.approx(expected, abs=0.08)


def test_the_players_who_were_lost_were_less_active_than_the_rest(reference: dict) -> None:
    latent = reference["sim"].latent
    lost = latent.loc[list(reference["sim"].dropped_player_ids)]

    assert lost.sessions_7d.mean() < 0.85 * latent.sessions_7d.mean()


def test_a_lost_player_appears_in_no_table(reference: dict) -> None:
    sim = reference["sim"]
    lost = set(sim.dropped_player_ids)

    for frame in sim.tables.values():
        assert not lost & set(frame.player_id)


def test_at_the_ci_scale_the_loss_is_present_but_too_small_to_test(
    small: ExperimentSimulation,
) -> None:
    assert len(small.dropped_player_ids) > 0
    assert len(assigned(small)) > 400


def test_without_the_planted_loss_the_split_is_fair() -> None:
    cfg = config(5_000)
    fair = simulate(
        cfg,
        dataclasses.replace(
            PLANTED,
            srm_drop_probability_low_activity=0.0,
            srm_drop_probability_high_activity=0.0,
        ),
    )

    counts = assigned(fair).arm.value_counts().reindex(ARMS)
    assert fair.dropped_player_ids == ()
    assert stats.chisquare(counts).pvalue > 0.001


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


def test_the_share_of_purchasers_exposed_late_matches_the_plan(reference: dict) -> None:
    sim = reference["sim"]
    purchasers = (outcomes(sim).purchases_7d > 0).sum()
    share = len(sim.late_exposure_player_ids) / purchasers

    assert share == pytest.approx(PLANTED.late_exposure_share_of_purchasers, abs=0.05)
    assert len(sim.late_exposure_player_ids) / len(assigned(sim)) == pytest.approx(0.077, abs=0.015)


def test_no_late_exposure_without_the_plan() -> None:
    sim = simulate(config(1_000), dataclasses.replace(PLANTED, late_exposure_share_of_purchasers=0))
    both = first_exposure_vs_purchase(sim)

    assert sim.late_exposure_player_ids == ()
    assert (both.first_purchase.isna() | (both.first_exposure < both.first_purchase)).all()


# --- Planted problem 3: heavy-tailed revenue -------------------------------------------


def test_revenue_per_player_is_heavy_tailed_at_the_reference_scale(reference: dict) -> None:
    revenue = outcomes(reference["sim"]).revenue_usd_7d
    ranked = revenue.sort_values(ascending=False)
    top_share = ranked.head(len(ranked) // 100).sum() / ranked.sum()

    assert top_share > 0.40  # the top one percent of players hold over 40% of revenue
    assert stats.kurtosis(revenue) > 100


def test_the_tail_is_lighter_when_the_plan_says_so() -> None:
    light = simulate(config(1_000), dataclasses.replace(PLANTED, purchase_amount_sigma=0.3))
    heavy = simulate(config(1_000))

    assert stats.kurtosis(outcomes(light).revenue_usd_7d) < stats.kurtosis(
        outcomes(heavy).revenue_usd_7d
    )


def test_outcome_columns_agree_with_each_other(small: ExperimentSimulation) -> None:
    o = outcomes(small)
    buyers = o.purchases_7d > 0

    assert ((o.revenue_usd_7d > 0) == buyers).all()
    assert (o.revenue_usd_7d[buyers] >= 0.99 * o.purchases_7d[buyers] - 1e-9).all()
    assert o.first_purchase_at_utc.notna().equals(buyers)
    in_window = (o.first_purchase_at_utc >= o.window_start_utc) & (
        o.first_purchase_at_utc <= o.window_end_utc
    )
    assert in_window[buyers].all()
    assert (o.sessions_7d >= 0).all() and o.revenue_usd_7d.round(2).equals(o.revenue_usd_7d)


# --- Planted problem 4: novelty that reverses ------------------------------------------


def lift_by_week(reference: dict, column: str) -> pd.Series:
    sim, launch = reference["sim"], reference["launch"]
    merged = assigned(sim).merge(outcomes(sim), on="player_id")
    week = (merged.assigned_at_utc - experiment_window(launch)[0]).dt.days // 7
    means = merged.groupby([week, "arm"])[column].mean().unstack("arm")
    return means["variant_b"] - means["control"]


def test_arm_b_has_a_first_week_lift_that_reverses_by_the_third(reference: dict) -> None:
    lift = lift_by_week(reference, "sessions_7d")

    assert list(lift.index) == [0, 1, 2]
    assert lift[0] > 1.0
    assert lift[0] > lift[1] > lift[2]
    assert lift[2] < 0.2


def test_arm_c_has_no_true_effect_but_looks_better_once_the_bug_starts(
    reference: dict,
) -> None:
    """True effect is zero: before the bug arm C matches control; after it, arm C is tilted up."""
    sim, launch = reference["sim"], reference["launch"]
    merged = assigned(sim).merge(outcomes(sim), on="player_id")
    onset = experiment_window(launch)[0] + PLANTED.srm_onset_day * DAY

    def gap(rows: pd.DataFrame) -> float:
        sessions = rows.groupby("arm").sessions_7d.mean()
        return sessions["variant_c"] - sessions["control"]

    before, after = (
        gap(merged[merged.assigned_at_utc < onset]),
        gap(merged[merged.assigned_at_utc >= onset]),
    )
    assert abs(before) < 0.5  # measured -0.00, standard error 0.24
    assert 0.2 < after < 1.2 and after > before  # measured +0.56, standard error 0.21


def test_novelty_follows_the_plan_for_purchases_too(reference: dict) -> None:
    lift = lift_by_week(reference, "purchases_7d")

    assert lift[0] > 0.05 and lift[2] < 0.02
    assert lift[0] - lift[2] > 0.08


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


def test_the_novelty_multipliers_and_the_version_effect_move_the_data() -> None:
    boosted = dataclasses.replace(
        PLANTED, novelty_purchase_multiplier=(4.0, 4.0, 4.0), v2_purchase_multiplier=2.0
    )
    sim = simulate(config(1_000), boosted)
    merged = assigned(sim).merge(outcomes(sim), on="player_id")
    rate = merged.groupby(["arm", "arm_config_version"]).purchases_7d.mean()

    assert rate["variant_b", 1] > 2.5 * rate["control", 1]
    assert rate["variant_b", 2] > 1.5 * rate["variant_b", 1]
    assert rate["variant_c", 1] == pytest.approx(rate["control", 1], rel=0.5)


def test_the_sessions_lifts_move_the_data() -> None:
    boosted = dataclasses.replace(
        PLANTED, novelty_sessions_lift=(5.0, 5.0, 5.0), v2_sessions_lift=3.0
    )
    sim = simulate(config(1_000), boosted)
    merged = assigned(sim).merge(outcomes(sim), on="player_id")
    mean = merged.groupby(["arm", "arm_config_version"]).sessions_7d.mean()

    assert mean["variant_b", 1] > mean["control", 1] + 3.5
    assert mean["variant_b", 2] > mean["variant_b", 1] + 1.5


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


def test_the_ground_truth_is_plain_json_data(reference: dict) -> None:
    import json

    truth = ground_truth(reference["launch"])

    assert json.loads(json.dumps(truth)) == truth


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
