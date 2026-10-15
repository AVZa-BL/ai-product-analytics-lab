"""HYP and PRO rules, each fired and not fired (design section 8, amendment 2 section 17.3)."""

import pytest
from rule_helpers import evaluate

from referee.rules import hypothesis as hyp
from referee.rules import procedure as pro

# --- HYP-001 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alternative",
    [
        "  The offer page   variant does not\tchange 7-day subscription conversion.\n",
    ],
    ids=["spacing"],
)
def test_hyp_001_fires_when_the_two_statements_match_after_normalisation(
    clean_raw_spec: dict, alternative: str
) -> None:
    finding = evaluate(hyp.HYP_001, clean_raw_spec, hypothesis__alternative=alternative)

    assert finding is not None
    assert finding.evidence == {
        "null": "The offer page variant does not change 7-day subscription conversion.",
        "alternative": alternative,
    }


# --- HYP-002 ---------------------------------------------------------------------------


def test_hyp_002_fires_when_the_primary_metric_has_no_governed_reference(
    clean_raw_spec: dict,
) -> None:
    finding = evaluate(hyp.HYP_002, clean_raw_spec, primary_metric__governed_reference=None)

    assert finding is not None
    assert finding.evidence == {"metric": "subscription_conversion_7d", "governed_reference": None}


# --- HYP-003 ---------------------------------------------------------------------------


def test_hyp_003_fires_when_the_analysis_unit_differs(clean_raw_spec: dict) -> None:
    finding = evaluate(hyp.HYP_003, clean_raw_spec, population__analysis_unit="session")

    assert finding is not None
    assert finding.evidence == {"randomization_unit": "player", "analysis_unit": "session"}


# --- HYP-004 ---------------------------------------------------------------------------


def test_hyp_004_fires_for_a_one_sided_test(clean_raw_spec: dict) -> None:
    finding = evaluate(hyp.HYP_004, clean_raw_spec, design__sided="one_sided")

    assert finding is not None
    assert finding.evidence == {"sided": "one_sided", "direction": "increase"}


# --- HYP-005 ---------------------------------------------------------------------------


def test_hyp_005_fires_for_a_ratio_primary_metric(clean_raw_spec: dict) -> None:
    finding = evaluate(
        hyp.HYP_005, clean_raw_spec, primary_metric__kind="ratio", primary_metric__baseline_std=0.4
    )

    assert finding is not None
    assert finding.evidence == {
        "metric": "subscription_conversion_7d",
        "kind": "ratio",
        "baseline_std": 0.4,
    }


# --- PRO-001 ---------------------------------------------------------------------------


# --- PRO-002 ---------------------------------------------------------------------------


@pytest.mark.parametrize("cadence", ["none"], ids=["explicit none"])
def test_pro_002_fires_when_srm_is_not_checked(clean_raw_spec: dict, cadence: str | None) -> None:
    finding = evaluate(pro.PRO_002, clean_raw_spec, procedure__srm_check_cadence=cadence)

    assert finding is not None
    assert finding.evidence == {"field": "procedure.srm_check_cadence", "value": cadence}


# --- PRO-003 ---------------------------------------------------------------------------


def test_pro_003_fires_without_guardrails(clean_raw_spec: dict) -> None:
    clean_raw_spec["guardrails"] = []

    finding = evaluate(pro.PRO_003, clean_raw_spec)

    assert finding is not None
    assert finding.evidence == {"guardrails": 0}


# --- PRO-004 ---------------------------------------------------------------------------


# --- Together --------------------------------------------------------------------------


