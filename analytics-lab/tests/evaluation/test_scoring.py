from analytics_lab.evaluation import score_answer


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
