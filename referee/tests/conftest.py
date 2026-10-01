"""Fixtures shared by the Referee test modules."""

import pytest


@pytest.fixture
def raw_spec() -> dict:
    """A valid spec as the plain dict a YAML file would load into. Fresh for every test."""
    return {
        "referee_spec_version": 1,
        "id": "hybrid_offer_page_2026_10",
        "title": "Subscription offer page variants",
        "owner": "analytics",
        "hypothesis": {
            "null": "The offer page variant does not change 7-day subscription conversion.",
            "alternative": "Variant B increases 7-day subscription conversion.",
            "direction": "increase",
        },
        "population": {
            "randomization_unit": "player",
            "analysis_unit": "player",
            "eligibility": "Players who open the offer page and are not subscribed at exposure.",
            "daily_eligible_units": 4200,
            "exposure_trigger": "offer_page_view",
        },
        "arms": [
            {"name": "control", "allocation": 0.5, "is_control": True},
            {"name": "variant_b", "allocation": 0.5},
        ],
        "primary_metric": {
            "name": "subscription_conversion_7d",
            "kind": "binary",
            "baseline": 0.032,
            "baseline_std": None,
            "governed_reference": "docs/metrics/hybrid_subscription.md",
        },
        "guardrails": [
            {
                "name": "refund_rate_14d",
                "kind": "binary",
                "baseline": 0.018,
                "harmful_direction": "increase",
                "tolerance_relative": 0.10,
            }
        ],
        "design": {
            "mde_relative": 0.05,
            "alpha": 0.05,
            "power": 0.80,
            "sided": "two_sided",
            "planned_duration_days": 14,
            "min_duration_days": 14,
        },
    }


@pytest.fixture
def clean_raw_spec(raw_spec: dict) -> dict:
    """`raw_spec` changed just enough that no design-review rule objects to it.

    The section 6 example is deliberately flawed (it is underpowered and declares nothing
    about how the test is run); this is the same experiment with enough traffic and every
    optional field declared.
    """
    raw_spec["population"].update(
        daily_eligible_units=100_000,
        exposure_timing="pre_treatment",
        interference="none_expected",
    )
    raw_spec["design"]["pre_period_covariate"] = "subscription_conversion_7d_pre_exposure"
    raw_spec["procedure"] = {
        "stopping_rule": "fixed_horizon",
        "srm_check_cadence": "daily",
        "bucketing_salt": "offer_page_2026_10",
    }
    return raw_spec
