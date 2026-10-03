"""A synthetic three-arm offer-page experiment for the hybrid subscription scenario.

The experiment exists to give a results reviewer something to find. It plants five problems
at documented sizes (`PlantedParameters`) and records the plan in `ground_truth`, so a reviewer
can be judged on finding exactly those and nothing else:

* a sample-ratio mismatch in arm C, caused by a bucketing bug on one platform that starts
  partway through the test and loses mostly players who rarely return, which tilts arm C's
  comparison upward by a small amount (among players assigned after the bug starts, 0.1 to
  0.6 sessions across eight seeds at 5,000 players; less when averaged over all assigned
  players; too small to see on its own); it is the mismatch, not the size of the bias, that
  invalidates the arm
* exposures logged after the player's first purchase, for part of the purchasers
* heavy-tailed revenue per player
* a novelty lift in arm B in the first week that reverses by the third
* a mid-test configuration change in arm B, visible as `arm_config_version`

Three tables are produced, one row per assigned player in assignments and outcomes, and one per
exposure event in exposures. Nothing here touches the scenario's existing tables: the
experiment draws from its own random stream, so those tables are byte-identical with or
without it. Only players who never subscribe are eligible, so subscription is not an outcome.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analytics_lab.generation.base import GenerationConfig

EXPERIMENT_ID = "hybrid_offer_page"
ARMS = ("control", "variant_b", "variant_c")
TABLE_NAMES = ("experiment_assignments", "experiment_exposures", "experiment_outcomes")

# Mixed into the seed so the experiment's random numbers are independent of the scenario's.
_STREAM_TAG = 0x45585052
_DAY = pd.to_timedelta(1, unit="D")
_SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class PlantedParameters:
    """Every size and timing the experiment plants. Change one here and the data follows."""

    bucketing_salt: str = "hybrid_offer_page_v1"

    # When: the window opens this many days after the subscription launch and assignments
    # arrive evenly over it; outcomes cover the seven days after each assignment.
    start_days_after_launch: int = 10
    duration_days: int = 21
    outcome_days: int = 7
    min_scenario_days: int = 90

    # Sample-ratio mismatch: from `srm_onset_day`, a bucketing bug on one platform loses arm
    # C's assignments, mostly those of players with few sessions (below the median).
    srm_platform: str = "android"
    srm_arm: str = "variant_c"
    srm_onset_day: int = 8
    srm_drop_probability_low_activity: float = 0.90
    srm_drop_probability_high_activity: float = 0.40

    # Novelty: by the week a player was assigned (0, 1, 2), arm B's purchase rate is
    # multiplied and its sessions shifted. Positive early, negative by the third week.
    novelty_arm: str = "variant_b"
    novelty_purchase_multiplier: tuple[float, ...] = (1.45, 1.05, 0.80)
    novelty_sessions_lift: tuple[float, ...] = (1.5, 0.3, -0.6)

    # Configuration change: arm B moves from version 1 to 2 on this day, and version 2 adds a
    # small further lift. Arm C and control never change.
    config_change_arm: str = "variant_b"
    config_change_day: int = 12
    v2_purchase_multiplier: float = 1.10
    v2_sessions_lift: float = 0.3

    # Exposure after purchase: this share of players who purchase are first exposed only
    # after their first purchase (the exposure fires from a post-purchase screen).
    late_exposure_share_of_purchasers: float = 0.35

    # Outcomes, per player per seven days. `engagement` scales sessions and purchases.
    baseline_sessions_7d: float = 4.0
    baseline_purchases_7d: float = 0.20
    engagement_sigma: float = 0.5
    purchase_amount_median_usd: float = 2.5
    purchase_amount_sigma: float = 1.7

    arms: tuple[str, ...] = field(default=ARMS)


PLANTED = PlantedParameters()


@dataclass(frozen=True)
class ExperimentSimulation:
    """The three tables, plus the truth a real platform would not log."""

    tables: dict[str, pd.DataFrame]
    dropped_player_ids: tuple[str, ...]
    late_exposure_player_ids: tuple[str, ...]
    latent: pd.DataFrame  # engagement, sessions and purchases of every eligible player


def experiment_window(
    launch_at: pd.Timestamp, planted: PlantedParameters = PLANTED
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """When assignments start and stop arriving."""
    start = launch_at + planted.start_days_after_launch * _DAY
    return start, start + planted.duration_days * _DAY


def ground_truth(
    launch_at: pd.Timestamp, planted: PlantedParameters = PLANTED
) -> dict[str, object]:
    """The plan, as plain data: what was planted, when, and how large."""
    start, end = experiment_window(launch_at, planted)
    overall_drop = 0.5 * (
        planted.srm_drop_probability_low_activity + planted.srm_drop_probability_high_activity
    )
    return {
        "experiment_id": EXPERIMENT_ID,
        "arms": list(planted.arms),
        "allocation": "hash bucketing, one third each",
        "bucketing_salt": planted.bucketing_salt,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "outcome_days": planted.outcome_days,
        "eligible": "players who never subscribe in the scenario",
        "sample_ratio_mismatch": {
            "arm": planted.srm_arm,
            "platform": planted.srm_platform,
            "onset_utc": (start + planted.srm_onset_day * _DAY).isoformat(),
            "drop_probability_low_activity": planted.srm_drop_probability_low_activity,
            "drop_probability_high_activity": planted.srm_drop_probability_high_activity,
            "expected_overall_drop_in_affected_cell": overall_drop,
            "effect": "arm C is tilted slightly upward: players with few sessions are lost",
        },
        "exposure_after_purchase": {
            "share_of_purchasers": planted.late_exposure_share_of_purchasers
        },
        "heavy_tailed_revenue": {
            "purchase_amount_median_usd": planted.purchase_amount_median_usd,
            "lognormal_sigma": planted.purchase_amount_sigma,
        },
        "novelty": {
            "arm": planted.novelty_arm,
            "purchase_multiplier_by_week": list(planted.novelty_purchase_multiplier),
            "sessions_lift_by_week": list(planted.novelty_sessions_lift),
        },
        "config_change": {
            "arm": planted.config_change_arm,
            "at_utc": (start + planted.config_change_day * _DAY).isoformat(),
            "from_version": 1,
            "to_version": 2,
            "v2_purchase_multiplier": planted.v2_purchase_multiplier,
            "v2_sessions_lift": planted.v2_sessions_lift,
        },
        "true_effect": {"variant_c": "none"},
    }


def _ids(prefix: str, count: int) -> list[str]:
    return [f"{prefix}_{index:07d}" for index in range(1, count + 1)]


def _bucket(salt: str, player_id: str, arms: int) -> int:
    digest = hashlib.sha256(f"{salt}:{player_id}".encode()).hexdigest()
    return int(digest[:8], 16) % arms


def simulate_experiment(
    config: GenerationConfig,
    players: pd.DataFrame,
    subscriber_ids: set[str] | frozenset[str],
    launch_at: pd.Timestamp,
    run_id: str,
    planted: PlantedParameters = PLANTED,
) -> ExperimentSimulation:
    """Generate the experiment for the players of one scenario run."""
    if config.days < planted.min_scenario_days:
        raise ValueError(
            f"the experiment needs a scenario of at least {planted.min_scenario_days} days, "
            f"got {config.days}"
        )

    window_start, _ = experiment_window(launch_at, planted)
    eligible = (
        players.loc[~players.player_id.isin(subscriber_ids), ["player_id", "platform"]]
        .sort_values("player_id")
        .reset_index(drop=True)
    )
    count = len(eligible)
    player_ids = eligible.player_id.to_numpy()
    platform = eligible.platform.to_numpy()

    # Every random quantity is drawn for every eligible player, in a fixed order, and only then
    # are dropped players removed, so changing one planted size cannot shift another's draws.
    rng = np.random.default_rng(np.random.SeedSequence([config.seed, _STREAM_TAG]))
    engagement = rng.lognormal(0.0, planted.engagement_sigma, count)
    offset_seconds = rng.integers(0, planted.duration_days * _SECONDS_PER_DAY, count)
    drop_draw = rng.random(count)
    late_draw = rng.random(count)
    first_exposure_minutes = rng.lognormal(np.log(4.0), 1.0, count)
    extra_exposures = rng.choice([0, 1, 2], count, p=[0.7, 0.2, 0.1])
    repeat_gap_seconds = rng.uniform(3_600, 72 * 3_600, (count, 2))

    arm_names = np.asarray(planted.arms)
    arm = arm_names[[_bucket(planted.bucketing_salt, p, len(arm_names)) for p in player_ids]]
    assigned_at = window_start + pd.to_timedelta(offset_seconds, unit="s")

    # Outcomes: by assignment week, with arm B's novelty and configuration version.
    week = offset_seconds // (7 * _SECONDS_PER_DAY)
    change_at = window_start + planted.config_change_day * _DAY
    on_change_arm = arm == planted.config_change_arm
    version_at_assignment = np.where(on_change_arm & (assigned_at >= change_at), 2, 1)
    purchase_multiplier = np.ones(count)
    sessions_lift = np.zeros(count)
    is_novelty = arm == planted.novelty_arm
    purchase_multiplier[is_novelty] = np.asarray(planted.novelty_purchase_multiplier)[
        week[is_novelty]
    ]
    sessions_lift[is_novelty] = np.asarray(planted.novelty_sessions_lift)[week[is_novelty]]
    is_v2 = version_at_assignment == 2
    purchase_multiplier[is_v2] *= planted.v2_purchase_multiplier
    sessions_lift[is_v2] += planted.v2_sessions_lift

    sessions = rng.poisson(
        np.maximum(0.1, planted.baseline_sessions_7d * engagement + sessions_lift)
    )
    purchases = rng.poisson(planted.baseline_purchases_7d * engagement * purchase_multiplier)

    # The assignment is logged on the player's next app open after the buggy release, so a
    # player who rarely returns (few sessions) is usually lost. The players who remain are
    # slightly more active than those lost, which tilts arm C upward.
    onset = window_start + planted.srm_onset_day * _DAY
    affected = (
        (arm == planted.srm_arm) & (platform == planted.srm_platform) & (assigned_at >= onset)
    )
    drop_probability = np.where(
        sessions < np.median(sessions),
        planted.srm_drop_probability_low_activity,
        planted.srm_drop_probability_high_activity,
    )
    dropped = affected & (drop_draw < drop_probability)

    # Purchases: heavy-tailed amounts, and the time of each, of which only the first is logged.
    owner = np.repeat(np.arange(count), purchases)
    amounts = np.maximum(
        0.99,
        np.round(
            rng.lognormal(
                np.log(planted.purchase_amount_median_usd),
                planted.purchase_amount_sigma,
                len(owner),
            ),
            2,
        ),
    )
    purchase_fraction = rng.random(len(owner))
    revenue = np.bincount(owner, weights=amounts, minlength=count)
    first_fraction = (
        pd.Series(purchase_fraction).groupby(owner).min().reindex(range(count)).to_numpy()
    )
    bought = purchases > 0
    first_purchase_seconds = np.where(
        bought, np.floor(np.nan_to_num(first_fraction) * planted.outcome_days * _SECONDS_PER_DAY), 0
    )
    first_purchase_at = (assigned_at + pd.to_timedelta(first_purchase_seconds, unit="s")).where(
        bought
    )

    # Exposures: normally minutes after assignment; for part of the purchasers, only after the
    # first purchase. Repeat exposures follow hours to days later.
    late = (purchases > 0) & (late_draw < planted.late_exposure_share_of_purchasers)
    normal_first = assigned_at + pd.to_timedelta(np.round(first_exposure_minutes * 60), unit="s")
    late_first = first_purchase_at + pd.to_timedelta(
        np.round(3_600 + first_exposure_minutes * 60), unit="s"
    )
    first_exposure = pd.DatetimeIndex(np.where(late, late_first, normal_first), tz="UTC")

    logged = ~dropped
    kept = np.flatnonzero(logged)

    assignments = pd.DataFrame(
        {
            "experiment_id": EXPERIMENT_ID,
            "player_id": player_ids[kept],
            "arm": arm[kept],
            "assigned_at_utc": assigned_at[kept],
            "arm_config_version": version_at_assignment[kept],
        }
    ).sort_values(["assigned_at_utc", "player_id"], kind="stable")
    assignments.insert(0, "assignment_id", _ids("assignment", len(assignments)))

    repeats = 1 + extra_exposures[kept]
    exposure_owner = np.repeat(kept, repeats)
    rank = np.arange(len(exposure_owner)) - np.repeat(np.cumsum(repeats) - repeats, repeats)
    gap_seconds = np.where(
        rank > 0, repeat_gap_seconds[exposure_owner, np.maximum(rank - 1, 0)], 0.0
    )
    exposed_at = first_exposure[exposure_owner] + pd.to_timedelta(np.round(gap_seconds), unit="s")
    exposed_arm = arm[exposure_owner]
    exposures = pd.DataFrame(
        {
            "experiment_id": EXPERIMENT_ID,
            "player_id": player_ids[exposure_owner],
            "arm": exposed_arm,
            "exposed_at_utc": exposed_at,
            "arm_config_version": np.where(
                (exposed_arm == planted.config_change_arm) & (exposed_at >= change_at), 2, 1
            ),
            "exposure_surface": "offer_page",
        }
    ).sort_values(["exposed_at_utc", "player_id"], kind="stable")
    exposures.insert(0, "exposure_id", _ids("exposure", len(exposures)))

    outcomes = pd.DataFrame(
        {
            "experiment_id": EXPERIMENT_ID,
            "player_id": player_ids[kept],
            "window_start_utc": assigned_at[kept],
            "window_end_utc": assigned_at[kept] + planted.outcome_days * _DAY,
            "sessions_7d": sessions[kept],
            "purchases_7d": purchases[kept],
            "revenue_usd_7d": np.round(revenue[kept], 2),
            "first_purchase_at_utc": first_purchase_at[kept],
        }
    ).sort_values("player_id", kind="stable")

    tables = {
        "experiment_assignments": assignments,
        "experiment_exposures": exposures,
        "experiment_outcomes": outcomes,
    }
    for name, frame in tables.items():
        frame["scenario_run_id"] = run_id
        tables[name] = frame.reset_index(drop=True)
    return ExperimentSimulation(
        tables=tables,
        dropped_player_ids=tuple(player_ids[dropped]),
        late_exposure_player_ids=tuple(player_ids[logged & late]),
        latent=pd.DataFrame(
            {"engagement": engagement, "sessions_7d": sessions, "purchases_7d": purchases},
            index=pd.Index(player_ids, name="player_id"),
        ),
    )


def generate_experiment_tables(
    config: GenerationConfig,
    players: pd.DataFrame,
    subscriber_ids: set[str] | frozenset[str],
    launch_at: pd.Timestamp,
    run_id: str,
    planted: PlantedParameters = PLANTED,
) -> dict[str, pd.DataFrame]:
    """The three experiment tables, without the hidden truth."""
    return simulate_experiment(config, players, subscriber_ids, launch_at, run_id, planted).tables
