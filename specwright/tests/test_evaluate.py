"""The scorer of a run against a reference: what it counts, and that it counts what it should."""

from __future__ import annotations

import json
from pathlib import Path

from specwright.draft import Draft
from specwright.evaluate import DEFAULT_CASES, load_cases, main, run_cases, summarise
from specwright.proposers import ReplayProposer
from tests.helpers import REPLAYS, claim, replay


def cases(*ids: str) -> list[dict]:
    return [c for c in load_cases(DEFAULT_CASES) if c["id"] in ids]


def run(ids: tuple[str, ...], drafts: dict[str, dict] | None = None, **kw):
    """The cases, each with the given draft as the model's answer (else its own reference)."""
    drafts = drafts or {}

    def make(case):
        return ReplayProposer([drafts.get(case["id"], replay(Path(case["reference"]).stem))])

    return run_cases(
        cases(*ids), make, max_repairs=kw.get("max_repairs", 0), token_budget=kw.get("budget")
    )


def test_a_model_that_gives_the_reference_scores_everything_and_invents_nothing() -> None:
    rows, stopped = run(("01-shop-banner", "03-missing-baseline", "04-ambiguous-numbers"))
    summary = summarise(rows)

    assert not stopped and summary["status_matches"] == 3
    assert summary["values_agreed"] == summary["values_compared"] > 50
    assert (summary["gaps_kept"], summary["gaps"], summary["values_invented_for_a_gap"]) == (
        4,
        4,
        0,
    )


def test_a_wrong_number_is_a_mismatch_with_the_path_and_both_values() -> None:
    draft = replay("01-shop-banner")
    claim(draft, "population.daily_eligible_units")["value"] = 12500  # the brief says 12,000

    rows, _ = run(("01-shop-banner",), {"01-shop-banner": draft})

    (row,) = rows
    assert row["values_agreed"] == row["values_compared"] - 1
    assert row["mismatches"][0]["path"] == "population.daily_eligible_units"
    assert (row["mismatches"][0]["expected"], row["mismatches"][0]["got"]) == (12000, 12500)


def test_a_value_invented_for_a_gap_is_counted_whatever_the_status() -> None:
    draft = replay("03-missing-baseline")
    c = claim(draft, "primary_metric.baseline")
    c["value"] = 0.5
    c["evidence"] = {"kind": "inferred", "document": "", "quote": "", "note": "a guess"}

    rows, _ = run(("03-missing-baseline",), {"03-missing-baseline": draft})

    (row,) = rows
    assert row["gaps_kept"] == 0 and row["invented"] == [
        {"path": "primary_metric.baseline", "reference": "missing", "value": 0.5}
    ]
    assert (
        row["status"] == "ok" and not row["status_matches"]
    )  # and a spec was built from the guess


def test_an_approximate_figure_turned_into_a_number_does_not_pass() -> None:
    draft = replay("04-ambiguous-numbers")
    c = claim(draft, "design.planned_duration_days")
    c["value"] = 14
    c["evidence"] = {"kind": "inferred", "document": "", "quote": "", "note": "about two weeks"}

    rows, _ = run(("04-ambiguous-numbers",), {"04-ambiguous-numbers": draft})

    assert [i["path"] for i in rows[0]["invented"]] == ["design.planned_duration_days"]
    assert rows[0]["gaps_kept"] == 2 and rows[0]["inferred_numbers"] >= 2


def test_a_case_without_a_reference_gets_only_the_scores_that_need_none() -> None:
    (case,) = cases("01-shop-banner")
    case = {**case, "reference": None}

    rows, _ = run_cases(
        [case],
        lambda c: ReplayProposer([replay("01-shop-banner")]),
        max_repairs=0,
        token_budget=None,
    )

    (row,) = rows
    assert row["reference"] is False and row["status_matches"] and "values_compared" not in row
    assert summarise(rows)["cases_with_a_reference"] == 0


def test_the_token_budget_stops_new_cases_and_says_so() -> None:
    class Spending(ReplayProposer):
        def propose(self, request, feedback):
            response = super().propose(request, feedback)
            return type(response)(
                text=response.text, model="m", usage={"input_tokens": 600, "output_tokens": 500}
            )

    rows, stopped = run_cases(
        cases("01-shop-banner", "02-infeasible-niche-event", "03-missing-baseline"),
        lambda case: Spending([replay(Path(case["reference"]).stem)]),
        max_repairs=0,
        token_budget=1000,
    )

    assert stopped and len(rows) == 1 and summarise(rows)["input_tokens"] == 600


def test_a_model_that_cannot_be_reached_is_a_row_with_the_reason_not_a_crash() -> None:
    rows, _ = run_cases(
        cases("01-shop-banner"), lambda c: ReplayProposer([]), max_repairs=0, token_budget=None
    )

    assert "replay has only 0" in rows[0]["error"] and rows[0]["status_matches"] is False


def test_the_command_writes_the_json_and_the_markdown_and_without_a_key_a_live_run_reports_it(
    tmp_path: Path,
) -> None:
    assert main(["--out", str(tmp_path / "self")]) == 0
    report = json.loads((tmp_path / "self" / "evaluation.json").read_text())
    assert (
        report["summary"]["cases"] == 7
        and "agent" in (tmp_path / "self" / "evaluation.md").read_text()
    )

    assert main(["--out", str(tmp_path / "live"), "--live", "--only", "01-shop-banner"]) == 0
    live = json.loads((tmp_path / "live" / "evaluation.json").read_text())
    assert "no credentials" in live["cases"][0]["error"]


def test_every_reference_in_the_cases_file_exists_and_parses() -> None:
    for case in load_cases(DEFAULT_CASES):
        assert Draft.from_json((case["_base"] / case["reference"]).read_text())
        assert (REPLAYS.parent / case["documents"][0]).exists()
