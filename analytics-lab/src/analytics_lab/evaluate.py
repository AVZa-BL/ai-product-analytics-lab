import argparse
import json
from pathlib import Path

from analytics_lab.evaluation import load_cases, score_answer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    answers = {
        item["id"]: item
        for item in json.loads(args.answers.read_text())["answers"]
    }
    results = [
        {"id": case["id"], **score_answer(case, answers[case["id"]])}
        for case in load_cases(args.questions)
    ]
    payload = {
        "scenario": args.scenario,
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
