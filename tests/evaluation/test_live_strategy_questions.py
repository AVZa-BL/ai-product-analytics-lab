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
    "d7_retention",
    "arpdau",
    "payer_conversion",
    "session_frequency",
    "median_session_duration",
    "event_participation",
    "alliance_adoption",
    "progression_velocity",
}

APPROVED_RELATIONS = {
    "mart_live_strategy__daily_kpis",
    "mart_live_strategy__retention_cohorts",
    "mart_live_strategy__d7_diagnostic_inputs",
}


def test_live_strategy_question_set_is_governed_and_adversarial() -> None:
    cases = yaml.safe_load(
        Path("docs/ai-audit/live_strategy_questions.yaml").read_text()
    )["questions"]

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


def test_live_strategy_answers_cover_every_case() -> None:
    cases = yaml.safe_load(
        Path("docs/ai-audit/live_strategy_questions.yaml").read_text()
    )["questions"]
    answers = yaml.safe_load(
        Path("scripts/evaluation/live_strategy_answers.json").read_text()
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
