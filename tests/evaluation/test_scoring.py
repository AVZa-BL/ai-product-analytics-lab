from analytics_lab.evaluation import score_answer


def test_numeric_answer_passes_only_with_governed_semantics_and_provenance() -> None:
    case = {
        "id": "q01",
        "expected_metric": "d7_retention",
        "expected_population": "android_installs",
        "expected_value": 0.31,
        "tolerance": 0.005,
        "requires_refusal": False,
        "approved_relations": ["mart_retention"],
    }
    answer = {
        "id": "q01",
        "metric": "d7_retention",
        "population": "android_installs",
        "value": 0.312,
        "refused": False,
        "relations": ["mart_retention"],
        "uncertainty": "95% interval reported",
        "latency_ms": 850,
        "cost_usd": 0.01,
    }
    result = score_answer(case, answer)
    assert result["passed"] is True
    assert result["numeric_score"] == 1


def test_unanswerable_case_requires_refusal() -> None:
    case = {
        "id": "q02",
        "expected_metric": None,
        "expected_population": None,
        "expected_value": None,
        "tolerance": None,
        "requires_refusal": True,
        "approved_relations": [],
    }
    answer = {
        "id": "q02",
        "metric": None,
        "population": None,
        "value": None,
        "refused": False,
        "relations": [],
        "uncertainty": "",
        "latency_ms": 200,
        "cost_usd": 0.0,
    }
    assert score_answer(case, answer)["passed"] is False
