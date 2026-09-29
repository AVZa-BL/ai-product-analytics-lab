import pandas as pd
import pytest

from analytics_lab.analysis.live_strategy_retention import (
    d7_contribution_table,
    fingerprint_inputs,
    standardized_retention,
)


def _fingerprint_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": ["pre_update", "pre_update", "post_update", "post_update"],
            "retention_signal": ["robust_activity"] * 4,
            "acquisition_channel": ["organic", "paid_social", "organic", "paid_social"],
            "eligible_players": [80, 20, 20, 80],
            "retained_players": [48, 8, 10, 24],
        }
    )


def test_input_fingerprint_is_stable_across_calls() -> None:
    frame = _fingerprint_frame()
    assert fingerprint_inputs(frame) == fingerprint_inputs(frame.copy())


def test_input_fingerprint_ignores_row_order() -> None:
    """Row order is a property of the query, not of the data it returned."""
    frame = _fingerprint_frame()
    shuffled = frame.iloc[[3, 1, 2, 0]].reset_index(drop=True)
    assert fingerprint_inputs(shuffled)["sha256"] == fingerprint_inputs(frame)["sha256"]


def test_input_fingerprint_changes_when_a_single_value_changes() -> None:
    """One player moving must change the digest.

    A published run once differed from a rebuild by exactly one eligible player, and
    nothing in the artifact could show it: provenance recorded the commit and the
    library versions but never the data. This is the assertion that would have caught
    it on the first re-run rather than the fourth.
    """
    frame = _fingerprint_frame()
    moved = frame.copy()
    moved.loc[0, "eligible_players"] = 81

    assert fingerprint_inputs(moved)["sha256"] != fingerprint_inputs(frame)["sha256"]
    assert fingerprint_inputs(moved)["row_count"] == fingerprint_inputs(frame)["row_count"]


def test_input_fingerprint_refuses_an_empty_frame() -> None:
    with pytest.raises(ValueError, match="cannot fingerprint an empty diagnostic frame"):
        fingerprint_inputs(pd.DataFrame(columns=["period"]))


def test_standardization_holds_pre_mix_constant() -> None:
    frame = pd.DataFrame(
        {
            "period": ["pre_update", "pre_update", "post_update", "post_update"],
            "retention_signal": ["robust_activity"] * 4,
            "acquisition_channel": [
                "organic",
                "paid_social",
                "organic",
                "paid_social",
            ],
            "eligible_players": [80, 20, 20, 80],
            "retained_players": [48, 8, 10, 24],
        }
    )

    assert standardized_retention(frame, "robust_activity", "pre_update") == 0.46


def test_contribution_table_accounts_for_observed_change() -> None:
    frame = pd.DataFrame(
        {
            "period": ["pre_update", "pre_update", "post_update", "post_update"],
            "retention_signal": ["robust_activity"] * 4,
            "acquisition_channel": [
                "organic",
                "paid_social",
                "organic",
                "paid_social",
            ],
            "eligible_players": [80, 20, 20, 80],
            "retained_players": [48, 8, 10, 24],
        }
    )

    contributions = d7_contribution_table(frame)

    assert round(contributions.contribution.sum(), 10) == round(
        contributions.loc[
            contributions.component.eq("observed_change"), "value"
        ].iloc[0],
        10,
    )
