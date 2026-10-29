"""The monitor: `review-results --mode monitor` on an experiment still running (design 27)."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from results_helpers import T0, build_data, crowd, results_spec
from rule_helpers import write_yaml

from referee.cli import main
from referee.monitor import monitor_report
from referee.results import ResultsContext
from referee.review import review_context
from referee.rules import RESULTS_RULES

LAB_EXPORT = Path(__file__).parent / "data" / "hybrid_offer_page_5000"
SESSIONS_GUARDRAIL = {
    "name": "sessions_7d",
    "kind": "continuous",
    "baseline": 4.5,
    "baseline_std": 3.0,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.10,
}


def monitor(raw_spec: dict, rows: list, *, exported_at=None, **changes) -> dict:
    data = build_data(rows, exported_at=exported_at)
    spec = results_spec(raw_spec, **changes)
    return monitor_report(spec, data, file_hashes={}, as_of_source="command line")


BOUGHT = {"purchases": 1, "first_purchase_at": T0 + timedelta(hours=9)}


def three_arms(control: int = 100, b: int = 100, c: int = 100, **fields) -> list:
    """Arms of the given sizes, a fifth of each having bought (so that the binary primary metric
    varies and every comparison has an estimate)."""
    rows = []
    for arm, count in (("control", control), ("variant_b", b), ("variant_c", c)):
        buyers = count // 5
        rows += crowd(arm, count - buyers, prefix=f"{arm}_n", **fields)
        rows += crowd(arm, buyers, prefix=f"{arm}_y", **{**BOUGHT, **fields})
    return rows


def test_an_unfinished_experiment_is_on_track_not_invalid(raw_spec: dict) -> None:
    rows = three_arms()

    report = monitor(raw_spec, rows)

    # the same data in a results review is invalid, for RES-002 and RES-003 alone
    review = review_context(ResultsContext.of(results_spec(raw_spec), build_data(rows)))
    assert (review.verdict, review.blocking_rule_ids) == ("invalid", ("RES-002", "RES-003"))
    assert (report["status"], report["reasons"]) == ("on_track", [])
    assert report["progress"]["blocking_in_a_review"] == ["RES-002", "RES-003"]
    assert report["progress"]["players"]["control"]["missing"] > 0
    assert not report["progress"]["days"]["min_duration_reached"]


def test_a_sample_ratio_mismatch_is_a_stop_for_cause(raw_spec: dict) -> None:
    report = monitor(raw_spec, three_arms(c=40))

    assert report["status"] == "stop_for_cause"
    assert {"rule_id": "RES-001", "status": "stop_for_cause"}.items() <= report["reasons"][
        0
    ].items()
    assert report["primary_metric"]["unreadable_because"] == ["RES-001"]


def test_a_guardrail_breach_at_an_interim_look_is_attention_never_a_stop(raw_spec: dict) -> None:
    rows = [
        *crowd("control", 50, prefix="c4", sessions=4),
        *crowd("control", 50, prefix="c6", sessions=6),
        *crowd("variant_b", 50, prefix="b1", sessions=1),
        *crowd("variant_b", 50, prefix="b3", sessions=3),
        *crowd("variant_c", 100, prefix="c5", sessions=5),
    ]
    changes = {"guardrails": [SESSIONS_GUARDRAIL]}

    report = monitor(raw_spec, rows, **changes)

    # in a results review the same breach is a blocker
    context = ResultsContext.of(results_spec(raw_spec, **changes), build_data(rows))
    res_004 = next(rule for rule in RESULTS_RULES if rule.id == "RES-004").evaluate(context)
    assert res_004 is not None and res_004.severity == "blocker"
    by_arm = {row["arm"]: row for row in report["guardrails"]}
    assert (by_arm["variant_b"]["tier"], by_arm["variant_b"]["status"]) == ("shown", "attention")
    assert by_arm["variant_c"]["status"] == "within"
    assert by_arm["variant_b"]["harm"]["low"] > SESSIONS_GUARDRAIL["tolerance_relative"]
    assert report["status"] == "attention"


@pytest.mark.parametrize(
    ("name", "kind", "code"),
    [
        ("retention_d7", "binary", "column_missing"),
        ("sessions_7d", "ratio", "kind_unsupported"),
        ("sessions_7d", "binary", "kind_mismatch"),
    ],
)
def test_a_declared_metric_that_cannot_be_read_is_in_the_ledger_not_skipped(
    raw_spec: dict, name: str, kind: str, code: str
) -> None:
    guardrail = {**SESSIONS_GUARDRAIL, "name": name, "kind": kind}
    if kind == "binary":
        guardrail |= {"baseline": 0.3, "baseline_std": None}

    report = monitor(raw_spec, three_arms(), guardrails=[guardrail])

    assert [(e["role"], e["name"], e["evaluated"]) for e in report["ledger"]] == [
        ("primary", "purchased_7d", True),
        ("guardrail", name, False),
    ]
    assert report["ledger"][1]["reason"] == code
    assert report["guardrails"] == []
    assert report["status"] == "attention"
    assert any(r["rule_id"] == "ledger" for r in report["reasons"])


def test_the_primary_metric_shows_an_interval_and_no_p_value(raw_spec: dict) -> None:
    report = monitor(raw_spec, three_arms())
    primary = report["primary_metric"]

    assert "p_value" not in json.dumps(primary) and "adjusted" not in json.dumps(primary)
    assert {"difference", "ci_low", "ci_high"} <= primary["arms"][0].keys()
    assert "no p value" in primary["label"]
    sequential = monitor(raw_spec, three_arms(), procedure__stopping_rule="sequential")
    assert "sequential stopping rule" in sequential["primary_metric"]["label"]


def test_when_every_outcome_window_is_still_open_the_metrics_say_so(raw_spec: dict) -> None:
    report = monitor(raw_spec, three_arms(), exported_at=T0 + timedelta(days=2))

    assert report["ledger"][0]["reason"] == "window_not_matured"
    assert report["progress"]["players"]["control"]["closed_window"] == 0
    assert report["status"] == "attention"


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def lab_spec(tmp_path: Path, **changes) -> str:
    import yaml

    raw = yaml.safe_load(
        Path(__file__).parents[1].joinpath("examples/offer-page-results.yaml").read_text()
    )
    for key, value in changes.items():
        raw[key] = value
    return str(write_yaml(tmp_path, raw))


COMMON = ("--experiment-id", "hybrid_offer_page", "--as-of", "2026-06-30T00:00:00Z")


def test_the_command_stops_on_the_planted_mismatch_of_the_lab_export(capsys, tmp_path) -> None:
    spec = lab_spec(tmp_path)

    code, out, _ = run(
        capsys,
        "review-results",
        spec,
        str(LAB_EXPORT),
        *COMMON,
        "--mode",
        "monitor",
        "--format",
        "json",
    )

    report = json.loads(out)
    assert (code, report["status"], report["kind"]) == (1, "stop_for_cause", "monitor")
    assert "RES-001" in [r["rule_id"] for r in report["reasons"]]
    assert set(report["rules_run"]) == {
        "RES-001",
        "RES-002",
        "RES-003",
        "RES-004",
        "RES-011",
        "RES-012",
        "RES-013",
    }
    text_code, text, _ = run(
        capsys, "review-results", spec, str(LAB_EXPORT), *COMMON, "--mode", "monitor"
    )
    assert text_code == 1 and "Status: STOP_FOR_CAUSE" in text and "Not run: RES-007" in text


def test_the_command_refuses_a_memo_and_an_unreadable_primary_metric(capsys, tmp_path) -> None:
    spec = lab_spec(tmp_path)
    code, out, err = run(
        capsys,
        "review-results",
        spec,
        str(LAB_EXPORT),
        *COMMON,
        "--mode",
        "monitor",
        "--format",
        "memo",
    )
    assert (code, out) == (2, "") and "review format" in err

    primary = {"name": "retention_d7", "kind": "binary", "baseline": 0.3}
    bad = lab_spec(tmp_path, primary_metric=primary)
    code, out, err = run(
        capsys, "review-results", bad, str(LAB_EXPORT), *COMMON, "--mode", "monitor"
    )
    assert (code, out) == (2, "") and "retention_d7" in err and "column_missing" in err
