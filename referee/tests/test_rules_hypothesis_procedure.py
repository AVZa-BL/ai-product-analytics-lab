"""HYP and PRO rules, each fired and not fired (design section 8, amendment 2 section 17.3)."""

import pytest
from rule_helpers import evaluate

from referee import rules
from referee.review import review_design
from referee.rules import HYPOTHESIS_RULES, PROCEDURE_RULES, references
from referee.rules import hypothesis as hyp
from referee.rules import procedure as pro
from referee.spec import ExperimentSpec


def test_the_baseline_used_by_these_tests_triggers_nothing(clean_raw_spec: dict) -> None:
    for rule in rules.ALL_RULES:
        assert evaluate(rule, clean_raw_spec) is None, rule.id


# --- HYP-001 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alternative",
    [
        "The offer page variant does not change 7-day subscription conversion.",
        "THE OFFER PAGE VARIANT DOES NOT CHANGE 7-DAY SUBSCRIPTION CONVERSION.",
        "  The offer page   variant does not\tchange 7-day subscription conversion.\n",
    ],
    ids=["verbatim", "upper case", "spacing"],
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


def test_hyp_001_stays_quiet_when_the_statements_differ(clean_raw_spec: dict) -> None:
    assert evaluate(hyp.HYP_001, clean_raw_spec) is None


def test_hyp_001_stays_quiet_for_a_difference_of_one_word(clean_raw_spec: dict) -> None:
    changed = "The offer page variant does not change 7-day subscription retention."

    assert evaluate(hyp.HYP_001, clean_raw_spec, hypothesis__alternative=changed) is None


# --- HYP-002 ---------------------------------------------------------------------------


def test_hyp_002_fires_when_the_primary_metric_has_no_governed_reference(
    clean_raw_spec: dict,
) -> None:
    finding = evaluate(hyp.HYP_002, clean_raw_spec, primary_metric__governed_reference=None)

    assert finding is not None
    assert finding.evidence == {"metric": "subscription_conversion_7d", "governed_reference": None}


def test_hyp_002_stays_quiet_when_a_reference_is_given(clean_raw_spec: dict) -> None:
    assert evaluate(hyp.HYP_002, clean_raw_spec) is None


# --- HYP-003 ---------------------------------------------------------------------------


def test_hyp_003_fires_when_the_analysis_unit_differs(clean_raw_spec: dict) -> None:
    finding = evaluate(hyp.HYP_003, clean_raw_spec, population__analysis_unit="session")

    assert finding is not None
    assert finding.evidence == {"randomization_unit": "player", "analysis_unit": "session"}


def test_hyp_003_stays_quiet_when_the_units_match(clean_raw_spec: dict) -> None:
    assert evaluate(hyp.HYP_003, clean_raw_spec) is None


# --- HYP-004 ---------------------------------------------------------------------------


def test_hyp_004_fires_for_a_one_sided_test(clean_raw_spec: dict) -> None:
    finding = evaluate(hyp.HYP_004, clean_raw_spec, design__sided="one_sided")

    assert finding is not None
    assert finding.evidence == {"sided": "one_sided", "direction": "increase"}


def test_hyp_004_stays_quiet_for_a_two_sided_test(clean_raw_spec: dict) -> None:
    assert evaluate(hyp.HYP_004, clean_raw_spec) is None


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


@pytest.mark.parametrize("kind", ["binary", "continuous"])
def test_hyp_005_stays_quiet_for_other_metric_kinds(clean_raw_spec: dict, kind: str) -> None:
    std = None if kind == "binary" else 0.4

    assert (
        evaluate(
            hyp.HYP_005, clean_raw_spec, primary_metric__kind=kind, primary_metric__baseline_std=std
        )
        is None
    )


def test_hyp_005_ignores_a_ratio_guardrail(clean_raw_spec: dict) -> None:
    """The rule is about the primary metric; a guardrail's kind is not its business."""
    clean_raw_spec["guardrails"][0].update(kind="ratio", baseline_std=0.1)

    assert evaluate(hyp.HYP_005, clean_raw_spec) is None


# --- PRO-001 ---------------------------------------------------------------------------


def test_pro_001_fires_when_no_stopping_rule_is_declared(clean_raw_spec: dict) -> None:
    finding = evaluate(pro.PRO_001, clean_raw_spec, procedure__stopping_rule=None)

    assert finding is not None
    assert finding.severity == "blocker"
    assert finding.evidence == {"field": "procedure.stopping_rule", "value": None}


@pytest.mark.parametrize("rule", ["fixed_horizon", "sequential"])
def test_pro_001_stays_quiet_for_either_declared_rule(clean_raw_spec: dict, rule: str) -> None:
    assert evaluate(pro.PRO_001, clean_raw_spec, procedure__stopping_rule=rule) is None


# --- PRO-002 ---------------------------------------------------------------------------


@pytest.mark.parametrize("cadence", [None, "none"], ids=["absent", "explicit none"])
def test_pro_002_fires_when_srm_is_not_checked(clean_raw_spec: dict, cadence: str | None) -> None:
    finding = evaluate(pro.PRO_002, clean_raw_spec, procedure__srm_check_cadence=cadence)

    assert finding is not None
    assert finding.evidence == {"field": "procedure.srm_check_cadence", "value": cadence}


@pytest.mark.parametrize("cadence", ["daily", "weekly"])
def test_pro_002_stays_quiet_when_srm_is_checked(clean_raw_spec: dict, cadence: str) -> None:
    assert evaluate(pro.PRO_002, clean_raw_spec, procedure__srm_check_cadence=cadence) is None


# --- PRO-003 ---------------------------------------------------------------------------


def test_pro_003_fires_without_guardrails(clean_raw_spec: dict) -> None:
    clean_raw_spec["guardrails"] = []

    finding = evaluate(pro.PRO_003, clean_raw_spec)

    assert finding is not None
    assert finding.evidence == {"guardrails": 0}


def test_pro_003_stays_quiet_with_a_guardrail(clean_raw_spec: dict) -> None:
    assert evaluate(pro.PRO_003, clean_raw_spec) is None


# --- PRO-004 ---------------------------------------------------------------------------


def test_pro_004_fires_without_a_bucketing_salt(clean_raw_spec: dict) -> None:
    finding = evaluate(pro.PRO_004, clean_raw_spec, procedure__bucketing_salt=None)

    assert finding is not None
    assert finding.severity == "info"
    assert finding.evidence == {"field": "procedure.bucketing_salt", "value": None}


def test_pro_004_stays_quiet_with_a_salt(clean_raw_spec: dict) -> None:
    assert evaluate(pro.PRO_004, clean_raw_spec) is None


# --- Together --------------------------------------------------------------------------


def test_a_spec_that_breaks_every_hyp_and_pro_rule_gets_them_all_in_severity_order(
    clean_raw_spec: dict,
) -> None:
    del clean_raw_spec["procedure"]
    clean_raw_spec["hypothesis"]["alternative"] = clean_raw_spec["hypothesis"]["null"]
    clean_raw_spec["primary_metric"]["governed_reference"] = None
    clean_raw_spec["population"]["analysis_unit"] = "session"
    clean_raw_spec["design"]["sided"] = "one_sided"
    clean_raw_spec["primary_metric"].update(kind="ratio", baseline_std=0.4)
    clean_raw_spec["guardrails"] = []

    review = review_design(
        ExperimentSpec.from_dict(clean_raw_spec), rules=(*HYPOTHESIS_RULES, *PROCEDURE_RULES)
    )

    assert [f.rule_id for f in review.findings] == [
        "HYP-001",
        "PRO-001",
        "HYP-002",
        "HYP-003",
        "HYP-004",
        "HYP-005",
        "PRO-002",
        "PRO-003",
        "PRO-004",
    ]
    assert review.blocking_rule_ids == ("HYP-001", "PRO-001")
    assert review.recommendation == "revise"


def test_every_finding_cites_only_what_the_catalogue_has_checked(clean_raw_spec: dict) -> None:
    known = {v for k, v in vars(references).items() if k.isupper()}
    cited = {ref for rule in rules.ALL_RULES for ref in rule.references}

    assert cited <= known
