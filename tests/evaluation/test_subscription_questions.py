from pathlib import Path

import yaml

REQUIRED = {
    "question",
    "expected_metric",
    "expected_population",
    "expected_result",
    "tolerance",
    "refusal_requirement",
    "latency",
    "cost",
}


def test_subscription_question_set_covers_required_question_classes() -> None:
    questions = yaml.safe_load(
        Path("scripts/evaluation/subscription_questions.yaml").read_text()
    )["questions"]
    assert {question["class"] for question in questions} == {
        "standard",
        "difficult",
        "ambiguous",
        "unanswerable",
        "adversarial",
    }
    assert all(REQUIRED <= set(question) for question in questions)
    assert all(
        question["expected_metric"]
        in {
            "signup_to_trial_rate",
            "trial_to_paid_conversion",
            "mrr",
            "cac",
            "refusal",
        }
        for question in questions
    )
