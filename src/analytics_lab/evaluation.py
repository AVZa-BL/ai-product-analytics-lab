from pathlib import Path

import yaml

REQUIRED_CASE_FIELDS = {
    "id",
    "category",
    "question",
    "expected_metric",
    "expected_population",
    "expected_value",
    "tolerance",
    "requires_refusal",
    "approved_relations",
}


def load_cases(path: Path) -> list[dict[str, object]]:
    cases = yaml.safe_load(path.read_text())["questions"]
    for case in cases:
        missing = REQUIRED_CASE_FIELDS - set(case)
        if missing:
            raise ValueError(
                f"case {case.get('id', '<unknown>')} missing {sorted(missing)}"
            )
    return cases


def score_answer(
    case: dict[str, object], answer: dict[str, object]
) -> dict[str, object]:
    refusal_score = int(bool(answer["refused"]) == bool(case["requires_refusal"]))
    metric_score = int(answer["metric"] == case["expected_metric"])
    population_score = int(answer["population"] == case["expected_population"])
    approved = set(case["approved_relations"])
    provenance_score = int(set(answer["relations"]) <= approved)
    if case["expected_value"] is None:
        numeric_score = int(answer["value"] is None)
    else:
        numeric_score = int(
            answer["value"] is not None
            and abs(float(answer["value"]) - float(case["expected_value"]))
            <= float(case["tolerance"])
        )
    uncertainty_score = int(bool(answer["uncertainty"]) or bool(answer["refused"]))
    scores = {
        "metric_score": metric_score,
        "population_score": population_score,
        "numeric_score": numeric_score,
        "uncertainty_score": uncertainty_score,
        "refusal_score": refusal_score,
        "provenance_score": provenance_score,
        "latency_ms": answer["latency_ms"],
        "cost_usd": answer["cost_usd"],
    }
    scores["passed"] = all(
        scores[name] == 1
        for name in (
            "metric_score",
            "population_score",
            "numeric_score",
            "uncertainty_score",
            "refusal_score",
            "provenance_score",
        )
    )
    return scores
