"""The results rules (design section 21.4), one at a time."""

import json
from pathlib import Path

import pytest
from results_helpers import (
    TWO_ARMS,
    Row,
    at,
    build_data,
    crowd,
    evaluate_results,
    results_spec,
)

from referee.data import load_export
from referee.methods import homogeneity_test, srm_test, two_proportion_difference, welch_difference
from referee.results import ResultsContext
from referee.review import review_results
from referee.rules import RESULTS_RULES

FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _rule(rule_id: str):
    return next(rule for rule in RESULTS_RULES if rule.id == rule_id)


@pytest.fixture(scope="module")
def export():
    return load_export(FIXTURE, "hybrid_offer_page")


# --- RES-001: sample ratio mismatch ---------------------------------------------------------

RES_001 = _rule("RES-001")


def test_res_001_is_a_blocker_citing_the_sample_ratio_literature() -> None:
    assert RES_001.severity == "blocker"
    assert any("Sample Ratio Mismatch" in reference for reference in RES_001.references)
    assert "0.001" in RES_001.fires_when


def test_res_001_is_quiet_when_the_arms_are_the_registered_size(raw_spec) -> None:
    rows = [*crowd("control", 100), *crowd("variant_b", 100), *crowd("variant_c", 100)]

    assert evaluate_results(RES_001, results_spec(raw_spec), rows) is None


@pytest.mark.parametrize(
    ("control", "variant", "flagged"),
    [(552, 448, False), (553, 447, True), (500, 500, False), (448, 552, False), (447, 553, True)],
)
def test_res_001_fires_when_p_is_below_one_in_a_thousand_and_not_at_it(
    raw_spec, control: int, variant: int, flagged: bool
) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    rows = [*crowd("control", control), *crowd("variant_b", variant)]

    finding = evaluate_results(RES_001, spec, rows)

    assert srm_test([control, variant], [0.5, 0.5]).flagged is flagged
    assert (finding is not None) is flagged


def test_res_001_reports_the_counts_the_test_and_the_week_by_week_check(raw_spec) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    rows = [
        *crowd("control", 300, prefix="c0"),
        *crowd("variant_b", 200, prefix="v0"),
        *crowd("control", 100, prefix="c3", assigned_at=at(22), exposed_at=at(22, 1)),
        *crowd("variant_b", 100, prefix="v3", assigned_at=at(22), exposed_at=at(22, 1)),
    ]

    finding = evaluate_results(RES_001, spec, rows)

    assert finding is not None
    evidence = finding.evidence
    total = srm_test([400, 300], [0.5, 0.5])
    assert evidence["assigned"] == {"control": 400, "variant_b": 300}
    assert evidence["allocation"] == {"control": 0.5, "variant_b": 0.5}
    assert evidence["expected"] == {"control": 350.0, "variant_b": 350.0}
    assert evidence["chi_square"] == round(total.chi_square, 4) == 14.2857
    assert evidence["degrees_of_freedom"] == 1 and evidence["alpha"] == 0.001
    assert evidence["p_value"] == total.p_value
    # Weeks 0 and 3 hold players; weeks 1 and 2 hold nobody and are not listed.
    assert [w["week"] for w in evidence["by_week"]] == [0, 3]
    assert evidence["by_week"][0] == {
        "week": 0,
        "assigned": {"control": 300, "variant_b": 200},
        "p_value": srm_test([300, 200], [0.5, 0.5]).p_value,
    }
    assert evidence["by_week"][1]["p_value"] == 1.0  # 100 against 100


def test_res_001_evidence_can_be_written_as_json(raw_spec) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    finding = evaluate_results(RES_001, spec, [*crowd("control", 600), *crowd("variant_b", 400)])

    assert finding is not None
    assert json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_001_counts_every_assigned_player_not_only_the_analysed(raw_spec) -> None:
    # Equal arms as assigned, but half of variant_b was never exposed: the check is on
    # assignment, so a loss at exposure cannot hide a mismatch, or make one.
    rows = [
        *crowd("control", 100),
        *crowd("variant_b", 50),
        *crowd("variant_b", 50, prefix="never", exposed_at=None),
    ]
    spec = results_spec(raw_spec, arms=TWO_ARMS)

    assert evaluate_results(RES_001, spec, rows) is None


def test_res_001_counts_late_exposed_players_too(raw_spec) -> None:
    late = {"exposed_at": at(0, 5), "purchases": 1, "first_purchase_at": at(0, 1)}
    rows = [
        *crowd("control", 100),
        *crowd("variant_b", 40),
        *crowd("variant_b", 60, prefix="late", **late),
    ]

    assert evaluate_results(RES_001, results_spec(raw_spec, arms=TWO_ARMS), rows) is None


def test_res_001_tests_against_the_registered_allocation_not_against_equal_arms(raw_spec) -> None:
    arms = [
        {"name": "control", "allocation": 0.7, "is_control": True},
        {"name": "variant_b", "allocation": 0.3},
    ]
    spec = results_spec(raw_spec, arms=arms)

    assert (
        evaluate_results(RES_001, spec, [*crowd("control", 700), *crowd("variant_b", 300)]) is None
    )
    finding = evaluate_results(RES_001, spec, [*crowd("control", 300), *crowd("variant_b", 700)])
    assert finding is not None and finding.evidence["allocation"] == {
        "control": 0.7,
        "variant_b": 0.3,
    }


def test_res_001_pairs_each_arm_with_its_own_allocation_whatever_the_order_of_the_arms(
    raw_spec,
) -> None:
    arms = [
        {"name": "variant_b", "allocation": 0.3},
        {"name": "control", "allocation": 0.7, "is_control": True},
    ]
    spec = results_spec(raw_spec, arms=arms)

    assert (
        evaluate_results(RES_001, spec, [*crowd("control", 700), *crowd("variant_b", 300)]) is None
    )
    finding = evaluate_results(RES_001, spec, [*crowd("control", 300), *crowd("variant_b", 700)])
    assert finding is not None and list(finding.evidence["assigned"]) == ["variant_b", "control"]


def test_res_001_sees_an_arm_that_vanished(raw_spec) -> None:
    rows = [*crowd("control", 100), *crowd("variant_b", 100)]  # variant_c has nobody

    finding = evaluate_results(RES_001, results_spec(raw_spec), rows)

    assert finding is not None
    assert finding.evidence["assigned"] == {"control": 100, "variant_b": 100, "variant_c": 0}


def test_res_001_leaves_out_players_assigned_before_the_registered_start(raw_spec) -> None:
    early = crowd("control", 300, prefix="early", assigned_at=at(-5), exposed_at=at(-5, 1))
    rows = [*early, *crowd("control", 100), *crowd("variant_b", 100)]
    spec_without = results_spec(raw_spec, arms=TWO_ARMS)
    spec_with = results_spec(raw_spec, arms=TWO_ARMS, design__start_utc="2026-04-11T00:00:00Z")

    assert evaluate_results(RES_001, spec_without, rows) is not None
    assert evaluate_results(RES_001, spec_with, rows) is None


# --- On the committed export of the lab's 5,000-player experiment ---------------------------


def test_res_001_finds_the_planted_mismatch_in_the_committed_export(raw_spec, export) -> None:
    context = ResultsContext.of(results_spec(raw_spec), export)

    finding = RES_001.evaluate(context)

    assert finding is not None
    evidence = finding.evidence
    assert evidence["assigned"] == {"control": 997, "variant_b": 1046, "variant_c": 781}
    assert evidence["expected"] == {arm: 941.33 for arm in evidence["assigned"]}
    assert evidence["chi_square"] == 42.2387 and evidence["degrees_of_freedom"] == 2
    assert evidence["p_value"] == pytest.approx(6.7e-10, rel=0.01, abs=0)
    weeks = {w["week"]: w for w in evidence["by_week"]}
    assert sorted(weeks) == [0, 1, 2]
    assert weeks[0]["assigned"] == {"control": 327, "variant_b": 357, "variant_c": 322}
    assert weeks[1]["assigned"] == {"control": 343, "variant_b": 356, "variant_c": 252}
    assert weeks[2]["assigned"] == {"control": 327, "variant_b": 333, "variant_c": 207}
    assert weeks[0]["p_value"] == pytest.approx(0.34, abs=0.005)
    assert weeks[1]["p_value"] == pytest.approx(4.0e-5, rel=0.01, abs=0)
    assert weeks[2]["p_value"] == pytest.approx(2.6e-8, rel=0.02, abs=0)


def test_a_results_review_of_the_committed_export_is_invalid_because_of_res_001(
    raw_spec, export
) -> None:
    review = review_results(results_spec(raw_spec), export)

    assert review.verdict == "invalid"
    assert "RES-001" in review.blocking_rule_ids
    assert review.rules_run == tuple(sorted(rule.id for rule in RESULTS_RULES))


# --- RES-002: fewer players than the registered sample size ---------------------------------

RES_002 = _rule("RES-002")
SMALL = {"design__mde_relative": 1.5}  # a large effect, so the registered n is small (222 a arm)


def _required(raw_spec, **changes) -> dict[str, int]:
    """The registered n per arm of a two-arm spec with `changes`, found the way the rule does."""
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL, **changes)
    context = ResultsContext.of(spec, build_data(crowd("control", 1) + crowd("variant_b", 1)))
    return {arm: context.required_n(arm) for arm in ("control", "variant_b")}


def test_res_002_is_a_blocker_about_the_registered_size() -> None:
    assert RES_002.severity == "blocker"
    assert "fewer players than" in RES_002.fires_when and "power plan" in RES_002.fires_when


def test_res_002_is_quiet_when_every_arm_has_exactly_its_registered_size(raw_spec) -> None:
    required = _required(raw_spec)
    rows = [*crowd("control", required["control"]), *crowd("variant_b", required["variant_b"])]
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL)

    assert required == {"control": 222, "variant_b": 222}
    assert evaluate_results(RES_002, spec, rows) is None


def test_res_002_fires_for_one_player_short_and_names_the_arm(raw_spec) -> None:
    required = _required(raw_spec)
    rows = [*crowd("control", required["control"]), *crowd("variant_b", required["variant_b"] - 1)]
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL)

    finding = evaluate_results(RES_002, spec, rows)

    assert finding is not None
    assert finding.evidence == {
        "required": {"control": 222, "variant_b": 222},
        "analysed": {"control": 222, "variant_b": 221},
        "assigned": {"control": 222, "variant_b": 221},
        "short_arms": ["variant_b"],
        "missing": {"variant_b": 1},
    }


def test_res_002_counts_the_analysed_players_not_the_assigned(raw_spec) -> None:
    required = _required(raw_spec)
    late = {"exposed_at": at(0, 5), "purchases": 1, "first_purchase_at": at(0, 1)}
    rows = [
        *crowd("control", required["control"]),
        *crowd("variant_b", required["variant_b"] - 10),
        *crowd("variant_b", 5, prefix="never", exposed_at=None),
        *crowd("variant_b", 5, prefix="late", **late),
    ]
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL)

    finding = evaluate_results(RES_002, spec, rows)

    assert finding is not None
    assert finding.evidence["assigned"]["variant_b"] == 222  # enough were assigned...
    assert finding.evidence["analysed"]["variant_b"] == 212  # ...but 10 left the analysis
    assert finding.evidence["missing"] == {"variant_b": 10}


def test_res_002_finds_each_arms_requirement_by_name(raw_spec) -> None:
    arms = [
        {"name": "variant_b", "allocation": 0.3},
        {"name": "control", "allocation": 0.7, "is_control": True},
    ]
    spec = results_spec(raw_spec, arms=arms, **SMALL)
    required = {"control": 344, "variant_b": 148}
    enough = [*crowd("control", required["control"]), *crowd("variant_b", required["variant_b"])]
    swapped = [*crowd("control", required["variant_b"]), *crowd("variant_b", required["control"])]

    assert evaluate_results(RES_002, spec, enough) is None
    finding = evaluate_results(RES_002, spec, swapped)
    assert finding is not None and finding.evidence["short_arms"] == ["control"]
    assert finding.evidence["required"] == {"variant_b": 148, "control": 344}


def test_res_002_reports_an_arm_nobody_is_in(raw_spec) -> None:
    spec = results_spec(raw_spec, **SMALL)
    rows = [*crowd("control", 300), *crowd("variant_b", 300)]  # variant_c has nobody

    finding = evaluate_results(RES_002, spec, rows)

    assert finding is not None
    assert finding.evidence["short_arms"] == ["variant_c"]
    assert finding.evidence["analysed"]["variant_c"] == 0


def test_res_002_says_so_when_the_design_cannot_be_sized(raw_spec) -> None:
    spec = results_spec(
        raw_spec,
        arms=TWO_ARMS,
        primary_metric={"name": "purchased_7d", "kind": "binary", "baseline": 0.9},
        design__mde_relative=0.2,
    )

    finding = evaluate_results(RES_002, spec, [*crowd("control", 50), *crowd("variant_b", 50)])

    assert finding is not None
    assert finding.evidence["unattainable"] is True and finding.evidence["reason"]
    assert finding.evidence["analysed"] == {"control": 50, "variant_b": 50}


def test_res_002_evidence_can_be_written_as_json(raw_spec) -> None:
    finding = evaluate_results(
        RES_002,
        results_spec(raw_spec, arms=TWO_ARMS, **SMALL),
        [*crowd("control", 5), *crowd("variant_b", 5)],
    )

    assert finding is not None and json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_002_on_the_committed_export_every_arm_is_far_short(raw_spec, export) -> None:
    context = ResultsContext.of(results_spec(raw_spec), export)

    finding = RES_002.evaluate(context)

    assert finding is not None
    assert finding.evidence["analysed"] == {"control": 926, "variant_b": 969, "variant_c": 731}
    assert finding.evidence["short_arms"] == ["control", "variant_b", "variant_c"]
    assert finding.evidence["missing"] == {
        arm: context.required_n(arm) - n for arm, n in finding.evidence["analysed"].items()
    }


# --- RES-003: ran for less than the registered minimum duration ----------------------------

RES_003 = _rule("RES-003")


def _span(raw_spec, days: float, *, minimum: int = 14, extra: list | None = None):
    """A two-arm export whose assignments run from the start to `days` later."""
    rows = [
        *crowd("control", 5, prefix="first"),
        *crowd("variant_b", 5, prefix="last", assigned_at=at(days), exposed_at=at(days, 1)),
        *(extra or []),
    ]
    spec = results_spec(
        raw_spec,
        arms=TWO_ARMS,
        design__min_duration_days=minimum,
        design__planned_duration_days=max(minimum, 30),
    )
    return evaluate_results(RES_003, spec, rows)


def test_res_003_is_a_blocker_about_the_minimum_duration() -> None:
    assert RES_003.severity == "blocker" and "design.min_duration_days" in RES_003.fires_when


@pytest.mark.parametrize(
    ("days", "fires"),
    [(14.0, False), (13.5, False), (13.0, True), (13.0001, False), (20.0, False), (0.0, True)],
    ids=["exactly-14", "13.5-rounds-up", "13", "just-over-13", "20", "one-day-of-assignment"],
)
def test_res_003_rounds_the_observed_days_up_and_compares_with_the_minimum(
    raw_spec, days: float, fires: bool
) -> None:
    assert (_span(raw_spec, days) is not None) is fires


def test_res_003_reports_what_was_observed(raw_spec) -> None:
    finding = _span(raw_spec, 9.25, minimum=14)

    assert finding is not None
    assert finding.evidence == {
        "observed_days": 10,
        "min_duration_days": 14,
        "planned_duration_days": 30,
        "first_assignment": "2026-04-11T00:00:00+00:00",
        "last_assignment": "2026-04-20T06:00:00+00:00",
        "ignored_before_start": [],
    }
    assert json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_003_measures_from_the_first_assignment_after_the_registered_start(raw_spec) -> None:
    early = crowd("control", 2, prefix="early", assigned_at=at(-20), exposed_at=at(-20, 1))
    rows = [
        *early,
        *crowd("control", 5, prefix="first", assigned_at=at(0), exposed_at=at(0, 1)),
        *crowd("variant_b", 5, prefix="last", assigned_at=at(9), exposed_at=at(9, 1)),
    ]
    base = {"arms": TWO_ARMS, "design__min_duration_days": 14, "design__planned_duration_days": 30}

    without_start = evaluate_results(RES_003, results_spec(raw_spec, **base), rows)
    with_start = evaluate_results(
        RES_003, results_spec(raw_spec, design__start_utc="2026-04-10T00:00:00Z", **base), rows
    )

    assert without_start is None  # 29 days from the early rows
    assert with_start is not None
    assert with_start.evidence["observed_days"] == 9
    assert with_start.evidence["ignored_before_start"] == ["early_0000", "early_0001"]


def test_res_003_on_the_committed_export_the_run_lasted_21_days(raw_spec, export) -> None:
    quiet = ResultsContext.of(results_spec(raw_spec, design__planned_duration_days=30), export)
    long_minimum = results_spec(
        raw_spec, design__planned_duration_days=30, design__min_duration_days=22
    )

    assert RES_003.evaluate(quiet) is None  # min_duration_days of the shared spec is 14
    finding = RES_003.evaluate(ResultsContext.of(long_minimum, export))
    assert finding is not None
    assert finding.evidence["observed_days"] == 21
    assert finding.evidence["last_assignment"] == "2026-05-01T23:37:55+00:00"


# --- RES-011: the sample ratio drifts although the total passes -------------------------------

RES_011 = _rule("RES-011")


def _weeks(counts: list[tuple[int, int]], *, gaps: tuple[int, ...] = ()) -> list:
    """Two arms, one (control, variant_b) pair per week; the weeks in `gaps` hold nobody."""
    rows = []
    kept = [week for week in range(len(counts) + len(gaps)) if week not in gaps]
    for week, (control, variant) in zip(kept, counts, strict=True):
        start = {"assigned_at": at(7 * week), "exposed_at": at(7 * week, 1)}
        rows += crowd("control", control, prefix=f"c{week}", **start)
        rows += crowd("variant_b", variant, prefix=f"v{week}", **start)
    return rows


def _drift(raw_spec, counts, **kw):
    return evaluate_results(RES_011, results_spec(raw_spec, arms=TWO_ARMS), _weeks(counts, **kw))


def test_res_011_is_a_warning_about_a_drift_the_total_hides() -> None:
    assert RES_011.severity == "warning"
    assert "RES-001 does not fire" in RES_011.fires_when


def test_res_011_fires_when_two_opposite_weeks_cancel_in_the_total(raw_spec) -> None:
    counts = [(700, 300), (300, 700)]  # 1,000 against 1,000 in all

    finding = _drift(raw_spec, counts)
    total_check = evaluate_results(RES_001, results_spec(raw_spec, arms=TWO_ARMS), _weeks(counts))

    assert total_check is None  # the total passes
    assert finding is not None
    assert finding.evidence["failing_weeks"] == [0, 1]
    assert finding.evidence["weeks_tested"] == 2 and finding.evidence["alpha_per_week"] == 0.0005
    assert finding.evidence["total"]["assigned"] == {"control": 1000, "variant_b": 1000}
    assert finding.evidence["total"]["p_value"] == 1.0
    assert finding.evidence["by_week"][0]["assigned"] == {"control": 700, "variant_b": 300}
    assert [w["flagged"] for w in finding.evidence["by_week"]] == [True, True]


def test_res_011_is_quiet_when_every_week_is_balanced(raw_spec) -> None:
    assert _drift(raw_spec, [(500, 500)] * 4) is None


def test_res_011_leaves_a_failing_total_to_res_001(raw_spec) -> None:
    counts = [(700, 300), (700, 300)]  # every week and the total fail

    assert _drift(raw_spec, counts) is None
    assert evaluate_results(RES_001, results_spec(raw_spec, arms=TWO_ARMS), _weeks(counts))


@pytest.mark.parametrize(
    ("week_split", "fires"),
    [((555, 445), False), ((556, 444), True)],
    ids=["p-0.000504", "p-0.000397"],
)
def test_res_011_tests_each_week_at_a_thousandth_over_two_weeks(
    raw_spec, week_split: tuple[int, int], fires: bool
) -> None:
    control, variant = week_split
    finding = _drift(raw_spec, [(control, variant), (variant, control)])

    assert (finding is not None) is fires


@pytest.mark.parametrize(
    ("week_split", "fires"),
    [((557, 443), False), ((558, 442), True)],
    ids=["p-0.000312", "p-0.000244"],
)
def test_res_011_tests_each_week_at_a_thousandth_over_four_weeks(
    raw_spec, week_split: tuple[int, int], fires: bool
) -> None:
    control, variant = week_split
    finding = _drift(raw_spec, [(control, variant), (variant, control), (500, 500), (500, 500)])

    assert (finding is not None) is fires
    if finding is not None:
        assert finding.evidence["alpha_per_week"] == 0.00025
        assert finding.evidence["failing_weeks"] == [0, 1]  # the mirror week fails the same way


def test_res_011_divides_by_the_weeks_that_hold_players_not_by_the_calendar(raw_spec) -> None:
    # Weeks 0 and 3 hold players and weeks 1 and 2 hold nobody: two weeks are tested, and a
    # split with p = 0.000397 fails at 0.0005 although it would pass at 0.001 over four weeks.
    finding = _drift(raw_spec, [(556, 444), (444, 556)], gaps=(1, 2))

    assert finding is not None
    assert finding.evidence["weeks_tested"] == 2
    assert [w["week"] for w in finding.evidence["by_week"]] == [0, 3]


def test_res_011_marks_which_weeks_failed(raw_spec) -> None:
    finding = _drift(raw_spec, [(700, 300), (300, 700), (500, 500)])

    assert finding is not None
    assert finding.evidence["failing_weeks"] == [0, 1]
    assert [w["flagged"] for w in finding.evidence["by_week"]] == [True, True, False]


def test_res_011_ignores_a_single_week_since_it_is_the_total(raw_spec) -> None:
    assert _drift(raw_spec, [(560, 440)]) is None  # the total fails: RES-001's case
    assert _drift(raw_spec, [(500, 500)]) is None


def test_res_011_evidence_can_be_written_as_json(raw_spec) -> None:
    finding = _drift(raw_spec, [(700, 300), (300, 700)])

    assert finding is not None and json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_011_leaves_out_players_assigned_before_the_registered_start(raw_spec) -> None:
    early = crowd("control", 400, prefix="early", assigned_at=at(-40), exposed_at=at(-40, 1))
    rows = [*early, *_weeks([(500, 500), (500, 500)])]
    spec = results_spec(raw_spec, arms=TWO_ARMS, design__start_utc="2026-04-11T00:00:00Z")

    assert evaluate_results(RES_011, spec, rows) is None


def test_res_011_is_silent_on_the_committed_export_because_res_001_fires_there(
    raw_spec, export
) -> None:
    context = ResultsContext.of(results_spec(raw_spec), export)

    assert RES_001.evaluate(context) is not None
    assert RES_011.evaluate(context) is None


@pytest.mark.parametrize(
    ("week_p", "fires"), [(0.0005, False), (0.00049999, True)], ids=["exactly-at", "just-below"]
)
def test_res_011_needs_p_strictly_below_the_weekly_level(
    raw_spec, monkeypatch, week_p: float, fires: bool
) -> None:
    """No real counts give a p of exactly 0.0005, so the test supplies the p values."""
    from referee.methods import SrmResult

    def stub(observed, allocation, *, alpha=0.001):
        p_value = 1.0 if tuple(observed) == (1000, 1000) else week_p
        return SrmResult(
            observed=tuple(observed),
            expected=(0.0, 0.0),
            chi_square=0.0,
            degrees_of_freedom=1,
            p_value=p_value,
            flagged=p_value < alpha,
        )

    monkeypatch.setattr("referee.rules.results.srm_test", stub)

    finding = _drift(raw_spec, [(700, 300), (300, 700)])

    assert (finding is not None) is fires


# --- RES-012: players first exposed after their first purchase ----------------------------------

RES_012 = _rule("RES-012")
LATE = {"exposed_at": at(0, 5), "purchases": 1, "first_purchase_at": at(0, 1)}
SESSIONS = {
    "name": "sessions_7d",
    "kind": "continuous",
    "baseline": 4.5,
    "baseline_std": 3.0,
}


def _late_rows(control_late: int, variant_late: int, *, exposed: int = 500) -> list:
    """Two arms of `exposed` players, each with the given number of late-exposed ones."""
    return [
        *crowd("control", exposed - control_late, prefix="c"),
        *crowd("control", control_late, prefix="cl", **LATE),
        *crowd("variant_b", exposed - variant_late, prefix="v"),
        *crowd("variant_b", variant_late, prefix="vl", **LATE),
    ]


def _res_012(raw_spec, rows, **changes):
    return evaluate_results(RES_012, results_spec(raw_spec, arms=TWO_ARMS, **changes), rows)


def test_res_012_is_a_warning_that_can_become_a_blocker() -> None:
    assert RES_012.severity == "warning"
    assert RES_012.escalation is not None and RES_012.escalation.to == "blocker"
    assert "after their first purchase" in RES_012.fires_when


def test_res_012_is_quiet_when_nobody_was_exposed_late(raw_spec) -> None:
    rows = [
        *crowd("control", 50),
        *crowd("variant_b", 50, purchases=1, first_purchase_at=at(0, 9)),  # bought after exposure
    ]

    assert _res_012(raw_spec, rows) is None


@pytest.mark.parametrize(
    ("exposed_hours", "fires"),
    [(1.0, False), (1.0001, True), (0.5, False)],
    ids=["at-the-instant", "just-after", "before"],
)
def test_res_012_one_player_exposed_after_buying_is_enough(
    raw_spec, exposed_hours: float, fires: bool
) -> None:
    late = {"purchases": 1, "first_purchase_at": at(0, 1), "exposed_at": at(0, exposed_hours)}
    rows = [
        *crowd("control", 20),
        *crowd("variant_b", 19),
        *crowd("variant_b", 1, prefix="x", **late),
    ]

    assert (_res_012(raw_spec, rows) is not None) is fires


def test_res_012_reports_counts_and_shares(raw_spec) -> None:
    on_time_buyer = {"purchases": 1, "first_purchase_at": at(0, 9)}
    rows = [
        *crowd("control", 70, prefix="c"),
        *crowd("control", 20, prefix="cb", **on_time_buyer),
        *crowd("control", 10, prefix="cl", **LATE),
        *crowd("variant_b", 70, prefix="v"),
        *crowd("variant_b", 30, prefix="vb", **on_time_buyer),
        *crowd("variant_b", 20, prefix="never", exposed_at=None),  # not exposed: cannot be late
    ]

    evidence = _res_012(raw_spec, rows).evidence

    assert evidence["late"] == {"control": 10, "variant_b": 0}
    assert evidence["exposed"] == {"control": 100, "variant_b": 100}  # the 20 unexposed are out
    assert evidence["late_share_of_exposed"] == {"control": 0.1, "variant_b": 0.0}
    assert evidence["late_total"] == 10
    assert evidence["share_of_assigned"] == round(10 / 220, 4) == 0.0455
    assert evidence["share_of_purchasers"] == round(10 / 60, 4) == 0.1667  # 20 + 10 + 30 bought


def test_res_012_stays_a_warning_when_every_arm_has_the_same_late_share(raw_spec) -> None:
    finding = _res_012(raw_spec, _late_rows(20, 20))

    assert finding is not None and finding.severity == "warning"
    assert finding.evidence["homogeneity"]["p_value"] == 1.0


@pytest.mark.parametrize(
    ("variant_late", "severity"), [(45, "warning"), (46, "blocker")], ids=["p-0.00134", "p-0.00093"]
)
def test_res_012_becomes_a_blocker_when_the_late_share_differs_between_arms(
    raw_spec, variant_late: int, severity: str
) -> None:
    finding = _res_012(raw_spec, _late_rows(20, variant_late))

    assert finding is not None and finding.severity == severity
    expected = homogeneity_test([20, variant_late], [500, 500])
    assert finding.evidence["homogeneity"] == {
        "chi_square": round(expected.chi_square, 4),
        "degrees_of_freedom": 1,
        "p_value": expected.p_value,
        "alpha": 0.001,
    }


@pytest.mark.parametrize(
    ("p_value", "severity"), [(0.001, "warning"), (0.00099999, "blocker")], ids=["at", "below"]
)
def test_res_012_needs_p_strictly_below_a_thousandth_to_block(
    raw_spec, monkeypatch, p_value: float, severity: str
) -> None:
    from referee.methods import HomogeneityResult

    def stub(successes, totals):
        return HomogeneityResult(
            successes=tuple(successes),
            totals=tuple(totals),
            chi_square=1.0,
            degrees_of_freedom=1,
            p_value=p_value,
        )

    monkeypatch.setattr("referee.rules.results.homogeneity_test", stub)

    assert _res_012(raw_spec, _late_rows(20, 20)).severity == severity


def test_res_012_with_one_arm_exposed_has_nothing_to_compare(raw_spec) -> None:
    rows = [*crowd("control", 30, **LATE), *crowd("control", 30, prefix="c2")]
    rows += crowd("variant_b", 10, exposed_at=None)  # assigned, never exposed

    finding = _res_012(raw_spec, rows)

    assert finding is not None and finding.severity == "warning"
    assert finding.evidence["homogeneity"] is None
    assert finding.evidence["late_share_of_exposed"] == {"control": 0.5, "variant_b": None}


def test_res_012_compares_the_arms_that_were_exposed_and_leaves_out_one_nobody_saw(
    raw_spec,
) -> None:
    rows = [
        *crowd("control", 480, prefix="c"),
        *crowd("control", 20, prefix="cl", **LATE),
        *crowd("variant_b", 454, prefix="v"),
        *crowd("variant_b", 46, prefix="vl", **LATE),
        *crowd("variant_c", 100, prefix="never", exposed_at=None),  # assigned, never exposed
    ]

    finding = evaluate_results(RES_012, results_spec(raw_spec), rows)

    assert finding is not None and finding.severity == "blocker"
    assert finding.evidence["exposed"] == {"control": 500, "variant_b": 500, "variant_c": 0}
    assert finding.evidence["homogeneity"]["degrees_of_freedom"] == 1


def test_res_012_when_every_exposed_player_is_late_there_is_nothing_to_compare(raw_spec) -> None:
    rows = [*crowd("control", 10, **LATE), *crowd("variant_b", 10, prefix="v", **LATE)]

    finding = _res_012(raw_spec, rows)

    assert finding is not None and finding.evidence["homogeneity"] is None
    assert finding.severity == "warning"


def test_res_012_quotes_the_estimate_with_and_without_the_late_players(raw_spec) -> None:
    buyer = {"purchases": 1, "first_purchase_at": at(0, 9)}
    rows = [
        *crowd("control", 90, prefix="c"),
        *crowd("control", 10, prefix="cb", **buyer),  # 10 of 100 bought, none exposed late
        *crowd("variant_b", 80, prefix="v"),
        *crowd("variant_b", 20, prefix="vb", **buyer),  # 20 of 100 bought on time
        *crowd("variant_b", 20, prefix="vl", **LATE),  # and 20 more bought before being exposed
    ]

    estimate = _res_012(raw_spec, rows).evidence["estimate"]
    without = two_proportion_difference(20, 100, 10, 100)
    with_late = two_proportion_difference(40, 120, 10, 100)

    assert estimate["metric"] == "purchased_7d" and list(estimate["by_arm"]) == ["variant_b"]
    got = estimate["by_arm"]["variant_b"]
    assert got["without_late_exposed"] == {
        "n_treatment": 100,
        "n_control": 100,
        "difference": round(without.difference, 6),
        "ci_low": round(without.ci_low, 6),
        "ci_high": round(without.ci_high, 6),
        "confidence": 0.95,
    }
    assert got["with_late_exposed"]["n_treatment"] == 120
    assert got["with_late_exposed"]["difference"] == round(with_late.difference, 6)
    assert got["with_late_exposed"]["difference"] > got["without_late_exposed"]["difference"]


def test_res_012_estimates_every_non_control_arm(raw_spec) -> None:
    rows = [
        *crowd("control", 50),
        *crowd("variant_b", 50),
        *crowd("variant_c", 49),
        *crowd("variant_c", 1, prefix="x", **LATE),
    ]

    estimate = evaluate_results(RES_012, results_spec(raw_spec), rows).evidence["estimate"]

    assert list(estimate["by_arm"]) == ["variant_b", "variant_c"]


def test_res_012_uses_welch_for_a_continuous_primary_metric(raw_spec) -> None:
    rows = []
    for i in range(30):
        rows.append(Row(f"c{i:02d}", "control", sessions=2 + i % 5))
        rows.append(Row(f"v{i:02d}", "variant_b", sessions=3 + i % 7))
    rows.append(Row("late", "variant_b", sessions=20, **LATE))

    estimate = _res_012(raw_spec, rows, primary_metric=SESSIONS).evidence["estimate"]
    control = [float(2 + i % 5) for i in range(30)]
    variant = [float(3 + i % 7) for i in range(30)]
    got = estimate["by_arm"]["variant_b"]

    assert estimate["metric"] == "sessions_7d"
    assert got["without_late_exposed"]["difference"] == round(
        welch_difference(variant, control).difference, 6
    )
    assert got["with_late_exposed"]["difference"] == round(
        welch_difference([*variant, 20.0], control).difference, 6
    )
    assert got["with_late_exposed"]["n_treatment"] == 31


def test_res_012_says_why_when_an_estimate_is_impossible_and_still_fires(raw_spec) -> None:
    finding = _res_012(raw_spec, [Row("c", "control", **LATE), Row("v", "variant_b", **LATE)])

    assert finding is not None
    by_arm = finding.evidence["estimate"]["by_arm"]["variant_b"]
    assert "every unit has the same outcome" in by_arm["with_late_exposed"]["error"]
    assert by_arm["without_late_exposed"]["n_treatment"] == 0
    assert "error" in by_arm["without_late_exposed"]


def test_res_012_evidence_can_be_written_as_json(raw_spec) -> None:
    finding = _res_012(raw_spec, _late_rows(20, 46))

    assert finding is not None and json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_012_on_the_committed_export_198_players_are_late_and_evenly_spread(
    raw_spec, export
) -> None:
    finding = RES_012.evaluate(ResultsContext.of(results_spec(raw_spec), export))

    assert finding is not None and finding.severity == "warning"
    evidence = finding.evidence
    assert evidence["late"] == {"control": 71, "variant_b": 77, "variant_c": 50}
    assert evidence["exposed"] == {"control": 997, "variant_b": 1046, "variant_c": 781}
    assert evidence["late_share_of_exposed"] == {
        "control": 0.0712,
        "variant_b": 0.0736,
        "variant_c": 0.064,
    }
    assert evidence["late_total"] == 198
    assert evidence["share_of_assigned"] == 0.0701 and evidence["share_of_purchasers"] == 0.3542
    assert evidence["homogeneity"]["p_value"] == pytest.approx(0.72, abs=0.005)


def test_res_012_on_the_committed_export_the_late_players_move_the_sessions_estimates(
    raw_spec, export
) -> None:
    spec = results_spec(raw_spec, primary_metric=SESSIONS)

    arms = RES_012.evaluate(ResultsContext.of(spec, export)).evidence["estimate"]["by_arm"]

    b = arms["variant_b"]
    assert (b["with_late_exposed"]["difference"], b["without_late_exposed"]["difference"]) == (
        0.681598,
        0.726217,
    )
    c = arms["variant_c"]
    assert c["with_late_exposed"]["ci_low"] < 0 < c["with_late_exposed"]["ci_high"]
    assert 0 < c["without_late_exposed"]["ci_low"]  # only without them does the interval clear zero
    assert (c["with_late_exposed"]["difference"], c["without_late_exposed"]["difference"]) == (
        0.29555,
        0.336484,
    )
