import copy
import json
from pathlib import Path

import pytest

from analytics_lab.evaluation import load_cases, score_answer

QUESTIONS = Path("docs/ai-audit/hybrid_subscription_questions.yaml")
ANSWERS = Path("scripts/evaluation/hybrid_subscription_answers.json")
DEFINITION_IDS = {
    "hybrid_definition_mau",
    "hybrid_definition_active_subscribers",
    "hybrid_definition_subscription_conversion",
    "hybrid_definition_subscriber_churn",
    "hybrid_definition_d30_subscriber_retention",
    "hybrid_definition_arpmau",
    "hybrid_definition_incremental_net_revenue",
    "hybrid_definition_discount_utilization",
    "hybrid_definition_engagement_lift",
    "hybrid_definition_liveops_participation",
}
CONTRACT_FIELDS = {
    "grain",
    "numerator",
    "denominator",
    "exclusions",
    "source_model",
    "maturity",
    "interpretation_boundary",
}
APPROVED_RELATIONS = {
    "fct_hybrid_subscription__subscriber_daily",
    "fct_hybrid_subscription__subscription_entitlements",
    "fct_hybrid_subscription__store_transactions",
    "fct_hybrid_subscription__marketing_exposures",
    "fct_hybrid_subscription__currency_grants",
    "mart_hybrid_subscription__daily_kpis",
    "mart_hybrid_subscription__monthly_kpis",
    "mart_hybrid_subscription__subscription_cohorts",
    "mart_hybrid_subscription__matched_incrementality",
    "mart_hybrid_subscription__engagement_lift_inputs",
    "mart_hybrid_subscription__cannibalization_inputs",
    "mart_hybrid_subscription__data_quality_incidents",
    "mart_hybrid_subscription__match_population_summary",
}


def _artifacts():
    return load_cases(QUESTIONS), json.loads(ANSWERS.read_text())["answers"]


def test_cases_and_answers_have_complete_governance_and_pass_evaluator() -> None:
    cases, answers = _artifacts()
    by_id = {answer["id"]: answer for answer in answers}
    assert len(by_id) == len(answers) == len(cases)
    assert set(by_id) == {case["id"] for case in cases}
    for case in cases:
        answer = by_id[case["id"]]
        assert case["class"] == case["category"]
        assert case["refusal_requirement"] is case["requires_refusal"]
        assert case["latency"] > 0 and case["cost"] >= 0
        assert score_answer(case, answer)["passed"], case["id"]
        assert answer["uncertainty"]
        if case["requires_refusal"]:
            assert case["expected_result"] == "refuse"
            assert case["expected_metric"] is case["expected_population"] is None
            assert case["expected_value"] is None
            assert case["approved_relations"] == answer["relations"] == []
        else:
            assert answer["relations"]
            assert case["expected_population"]
            assert set(case["approved_relations"]) <= APPROVED_RELATIONS
        if case["id"] in DEFINITION_IDS:
            assert CONTRACT_FIELDS <= case["definition"].keys()
            assert all(case["definition"][field] for field in CONTRACT_FIELDS)
            assert answer["definition"] == case["definition"]


@pytest.mark.parametrize(
    "case_id,mutation",
    [
        ("hybrid_total_revenue_did", "value"),
    ],
)
def test_evaluator_rejects_wrong_numeric_provenance_or_refusal(case_id, mutation) -> None:
    cases, answers = _artifacts()
    case = next(c for c in cases if c["id"] == case_id)
    answer = copy.deepcopy(next(a for a in answers if a["id"] == case_id))
    if mutation == "value":
        answer["value"] = 999
    elif mutation == "relations":
        answer["relations"] = ["raw.store_transactions"]
    else:
        answer["refused"] = False
    assert not score_answer(case, answer)["passed"]
