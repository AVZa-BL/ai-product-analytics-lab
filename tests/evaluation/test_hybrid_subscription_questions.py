from pathlib import Path

import yaml

REQUIRED = {
    "id",
    "category",
    "class",
    "question",
    "expected_metric",
    "expected_population",
    "expected_result",
    "expected_value",
    "tolerance",
    "refusal_requirement",
    "requires_refusal",
    "approved_relations",
    "latency",
    "cost",
}

ALLOWED_METRICS = {
    "paired_player_count",
    "session_frequency",
    "standalone_store_net_revenue_per_player",
    "subscription_net_revenue_per_player",
    "total_net_revenue_per_player",
    "subscription_grant_reconciliation_rate",
    "incrementality_eligible_exposure_rate",
}

APPROVED_RELATIONS = {
    "fct_hybrid_subscription__player_behavior_28d",
    "fct_hybrid_subscription__marketing_exposures",
    "fct_hybrid_subscription__currency_grants",
    "mart_hybrid_subscription__engagement_lift_inputs",
    "mart_hybrid_subscription__cannibalization_inputs",
    "mart_hybrid_subscription__daily_kpis",
    "mart_hybrid_subscription__data_quality_incidents",
}


def _load_cases() -> list[dict[str, object]]:
    return yaml.safe_load(
        Path("docs/ai-audit/hybrid_subscription_questions.yaml").read_text()
    )["questions"]


def test_hybrid_subscription_question_set_enforces_governance() -> None:
    cases = _load_cases()

    assert len(cases) >= 12
    assert {case["category"] for case in cases} >= {
        "standard",
        "difficult",
        "ambiguous",
        "unanswerable",
        "adversarial",
    }
    assert len({case["id"] for case in cases}) == len(cases)

    for case in cases:
        assert REQUIRED <= set(case)
        assert case["class"] == case["category"]
        assert case["refusal_requirement"] is case["requires_refusal"]
        assert case["latency"] > 0
        assert case["cost"] >= 0

        if case["requires_refusal"]:
            assert case["expected_metric"] is None
            assert case["expected_population"] is None
            assert case["expected_result"] == "refuse"
            assert case["expected_value"] is None
            assert case["tolerance"] == 0
            assert case["approved_relations"] == []
        else:
            assert case["expected_metric"] in ALLOWED_METRICS
            assert case["expected_population"]
            assert case["approved_relations"]
            assert set(case["approved_relations"]) <= APPROVED_RELATIONS
            if isinstance(case["expected_result"], (int, float)):
                assert case["expected_result"] == case["expected_value"]


def test_hybrid_subscription_answers_cover_every_case() -> None:
    cases = _load_cases()
    answers = yaml.safe_load(
        Path("scripts/evaluation/hybrid_subscription_answers.json").read_text()
    )["answers"]

    cases_by_id = {case["id"]: case for case in cases}
    answers_by_id = {answer["id"]: answer for answer in answers}
    assert set(answers_by_id) == set(cases_by_id)

    for case_id, case in cases_by_id.items():
        answer = answers_by_id[case_id]
        assert answer["refused"] is case["requires_refusal"]
        assert answer["metric"] == case["expected_metric"]
        assert answer["population"] == case["expected_population"]
        assert answer["value"] == case["expected_value"]
        assert set(answer["relations"]) <= set(case["approved_relations"])
        assert answer["uncertainty"]

        if case["requires_refusal"]:
            assert answer["relations"] == []
        else:
            assert answer["relations"]


def test_hybrid_subscription_cases_cover_decision_risks() -> None:
    cases = _load_cases()
    by_id = {case["id"]: case for case in cases}

    assert by_id["hybrid_total_revenue_did"]["expected_value"] == -14.668333333333333
    assert by_id["hybrid_store_revenue_did"]["expected_value"] == -24.658333333333335
    assert by_id["hybrid_subscription_revenue_did"]["expected_value"] == 9.99
    assert by_id["hybrid_lifetime_value_forecast"]["requires_refusal"] is True
    assert by_id["hybrid_raw_transaction_request"]["requires_refusal"] is True
    assert by_id["hybrid_hide_duplicate_webhooks"]["requires_refusal"] is True
    assert by_id["hybrid_causal_engagement_claim"]["requires_refusal"] is True
