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
from referee.methods import (
    homogeneity_test,
    srm_test,
    two_proportion_difference,
)
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
        "method": "chi_square",
    }
    assert evidence["by_week"][1]["p_value"] == 1.0  # 100 against 100
    assert evidence["method"] == "chi_square"


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


# --- RES-002: fewer players than the registered sample size ---------------------------------

RES_002 = _rule("RES-002")
SMALL = {"design__mde_relative": 1.5}  # a large effect, so the registered n is small (222 a arm)


def _required(raw_spec, **changes) -> dict[str, int]:
    """The registered n per arm of a two-arm spec with `changes`, found the way the rule does."""
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL, **changes)
    context = ResultsContext.of(spec, build_data(crowd("control", 1) + crowd("variant_b", 1)))
    return {arm: context.required_n(arm) for arm in ("control", "variant_b")}


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


@pytest.mark.parametrize(
    ("week_p", "fires"), [(0.0005, False), (0.00049999, True)], ids=["exactly-at", "just-below"]
)
def test_res_011_needs_p_strictly_below_the_weekly_level(
    raw_spec, monkeypatch, week_p: float, fires: bool
) -> None:
    """No real counts give a p of exactly 0.0005, so the test supplies the p values."""
    from referee.methods import SrmResult

    def stub(observed, allocation, *, alpha=0.001, exact_below=None):
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


def _late_rows(control_late: int, variant_late: int, *, exposed: int = 5000) -> list:
    """Two arms of `exposed` players, each with the given number of late-exposed ones."""
    return [
        *crowd("control", exposed - control_late, prefix="c"),
        *crowd("control", control_late, prefix="cl", **LATE),
        *crowd("variant_b", exposed - variant_late, prefix="v"),
        *crowd("variant_b", variant_late, prefix="vl", **LATE),
    ]


def _res_012(raw_spec, rows, **changes):
    return evaluate_results(RES_012, results_spec(raw_spec, arms=TWO_ARMS, **changes), rows)


@pytest.mark.parametrize(
    ("variant_late", "severity"),
    [(269, "warning"), (270, "blocker")],
    ids=["p-0.0011", "p-0.00094"],
)
def test_res_012_becomes_a_blocker_when_the_late_share_differs_between_arms(
    raw_spec, variant_late: int, severity: str
) -> None:
    finding = _res_012(raw_spec, _late_rows(200, variant_late))

    assert finding is not None and finding.severity == severity
    expected = homogeneity_test([200, variant_late], [5000, 5000])
    assert expected.method == "chi_square"  # every expected count is far above 100
    assert finding.evidence["homogeneity"] == {
        "chi_square": round(expected.chi_square, 4),
        "degrees_of_freedom": 1,
        "p_value": expected.p_value,
        "alpha": 0.001,
        "method": "chi_square",
        "smallest_expected": round(expected.smallest_expected, 2),
    }


@pytest.mark.parametrize(
    ("p_value", "severity"), [(0.001, "warning"), (0.00099999, "blocker")], ids=["at", "below"]
)
def test_res_012_needs_p_strictly_below_a_thousandth_to_block(
    raw_spec, monkeypatch, p_value: float, severity: str
) -> None:
    from referee.methods import HomogeneityResult

    def stub(successes, totals, *, exact_below=None):
        return HomogeneityResult(
            successes=tuple(successes),
            totals=tuple(totals),
            chi_square=1.0,
            degrees_of_freedom=1,
            p_value=p_value,
            smallest_expected=1000.0,
        )

    monkeypatch.setattr("referee.rules.results.homogeneity_test", stub)

    assert _res_012(raw_spec, _late_rows(200, 200)).severity == severity


def test_res_012_with_one_arm_exposed_has_nothing_to_compare(raw_spec) -> None:
    rows = [*crowd("control", 30, **LATE), *crowd("control", 30, prefix="c2")]
    rows += crowd("variant_b", 10, exposed_at=None)  # assigned, never exposed

    finding = _res_012(raw_spec, rows)

    assert finding is not None and finding.severity == "warning"
    assert finding.evidence["homogeneity"] == {
        "error": "need a success count and a size for each of at least two groups"
    }
    assert finding.evidence["late_share_of_exposed"] == {"control": 0.5, "variant_b": None}


def test_res_012_when_every_exposed_player_is_late_there_is_nothing_to_compare(raw_spec) -> None:
    rows = [*crowd("control", 10, **LATE), *crowd("variant_b", 10, prefix="v", **LATE)]

    finding = _res_012(raw_spec, rows)

    assert finding is not None and finding.severity == "warning"
    assert finding.evidence["homogeneity"] == {
        "error": "every unit has the same outcome, so no group can differ from another"
    }


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


def test_res_012_says_why_when_an_estimate_is_impossible_and_still_fires(raw_spec) -> None:
    finding = _res_012(raw_spec, [Row("c", "control", **LATE), Row("v", "variant_b", **LATE)])

    assert finding is not None
    by_arm = finding.evidence["estimate"]["by_arm"]["variant_b"]
    assert "every unit has the same outcome" in by_arm["with_late_exposed"]["error"]
    assert by_arm["without_late_exposed"]["n_treatment"] == 0
    assert "error" in by_arm["without_late_exposed"]


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


# --- RES-013: an arm's configuration changed during the test -----------------------------------

RES_013 = _rule("RES-013")


def _on_version(arm: str, count: int, version: int, *, week: int, prefix: str, **fields):
    """Players of `arm` first exposed in `week` on `version` (and assigned on it too)."""
    given = {
        "assigned_version": version,
        "exposure_version": version,
        "assigned_at": at(7 * week),
        "exposed_at": at(7 * week, 1),
        **fields,
    }
    return crowd(arm, count, prefix=prefix, **given)


def _res_013(raw_spec, rows, **changes):
    return evaluate_results(RES_013, results_spec(raw_spec, arms=TWO_ARMS, **changes), rows)


def test_res_013_reports_the_versions_by_week_of_first_exposure(raw_spec) -> None:
    rows = [
        *_on_version("control", 30, 1, week=0, prefix="c"),
        *_on_version("variant_b", 30, 1, week=0, prefix="v0"),
        *_on_version("variant_b", 20, 1, week=1, prefix="v1a"),
        *_on_version("variant_b", 10, 2, week=1, prefix="v1b"),
        *_on_version("variant_b", 30, 2, week=2, prefix="v2"),
    ]

    finding = _res_013(raw_spec, rows)

    assert finding is not None
    assert list(finding.evidence["arms"]) == ["variant_b"]  # control never changed
    arm = finding.evidence["arms"]["variant_b"]
    assert arm["versions"] == [{"version": 1, "players": 50}, {"version": 2, "players": 40}]
    assert arm["by_week"] == [
        {"week": 0, "versions": [{"version": 1, "players": 30}]},
        {"week": 1, "versions": [{"version": 1, "players": 20}, {"version": 2, "players": 10}]},
        {"week": 2, "versions": [{"version": 2, "players": 30}]},
    ]
    assert arm["mixed_weeks"] == [1]
    assert finding.evidence["metric"] == "purchased_7d"


def test_res_013_describes_the_difference_between_versions_within_a_mixed_week(raw_spec) -> None:
    buyer = {"purchases": 1, "first_purchase_at": at(8)}
    rows = [
        *_on_version("control", 20, 1, week=0, prefix="c"),
        *_on_version("variant_b", 40, 1, week=0, prefix="v0"),
        *_on_version("variant_b", 36, 1, week=1, prefix="a"),
        *_on_version("variant_b", 4, 1, week=1, prefix="ab", **buyer),  # 4 of 40 bought
        *_on_version("variant_b", 30, 2, week=1, prefix="b"),
        *_on_version("variant_b", 10, 2, week=1, prefix="bb", **buyer),  # 10 of 40 bought
    ]

    finding = _res_013(raw_spec, rows)
    expected = two_proportion_difference(10, 40, 4, 40)

    assert finding is not None
    (within,) = finding.evidence["arms"]["variant_b"]["within_week"]
    assert within == {
        "week": 1,
        "later_version": 2,
        "earlier_version": 1,
        "n_later": 40,
        "n_earlier": 40,
        "difference": round(expected.difference, 6),
        "ci_low": round(expected.ci_low, 6),
        "ci_high": round(expected.ci_high, 6),
        "confidence": 0.95,
    }
    assert within["difference"] == 0.15  # later minus earlier


def test_res_013_on_the_committed_export_variant_b_changes_in_its_second_week(
    raw_spec, export
) -> None:
    spec = results_spec(raw_spec, primary_metric=SESSIONS)

    finding = RES_013.evaluate(ResultsContext.of(spec, export))

    assert finding is not None and finding.severity == "warning"
    assert list(finding.evidence["arms"]) == ["variant_b"]  # the only arm that changed
    arm = finding.evidence["arms"]["variant_b"]
    assert arm["versions"] == [{"version": 1, "players": 540}, {"version": 2, "players": 429}]
    assert arm["by_week"] == [
        {"week": 0, "versions": [{"version": 1, "players": 313}]},
        {"week": 1, "versions": [{"version": 1, "players": 227}, {"version": 2, "players": 104}]},
        {"week": 2, "versions": [{"version": 2, "players": 325}]},
    ]
    assert arm["mixed_weeks"] == [1]
    # The 11 variant_b players first exposed on another version than they were assigned to
    # were all exposed after buying, so none of them is in the effect analysis.
    assert arm["assigned_differs"] == 0
    (within,) = arm["within_week"]
    assert (within["n_later"], within["n_earlier"]) == (104, 227)
    assert within["difference"] == pytest.approx(0.449848, abs=1e-6)
    assert within["ci_low"] < 0 < within["ci_high"]  # sessions: the versions cannot be told apart
    assert finding.evidence["version_from"] == {"exposure": 2626, "assignment": 0}


def test_a_results_review_of_the_committed_export_lists_every_data_fit_rule_that_fires(
    raw_spec, export
) -> None:
    review = review_results(results_spec(raw_spec), export)

    assert review.verdict == "invalid"
    assert review.blocking_rule_ids == ("RES-001", "RES-002")
    assert [f.rule_id for f in review.findings if f.severity == "warning"] == ["RES-012", "RES-013"]
    assert review.rules_run == ("RES-001", "RES-002", "RES-003", "RES-011", "RES-012", "RES-013")


# --- After the independent review of 4b-1 ---------------------------------------------------------

LATE = {"exposed_at": at(0, 5), "purchases": 1, "first_purchase_at": at(0, 1)}
BUYER = {"purchases": 1, "first_purchase_at": at(0, 9)}
RES_002, RES_003, RES_011, RES_012, RES_013 = (
    _rule(rule_id) for rule_id in ("RES-002", "RES-003", "RES-011", "RES-012", "RES-013")
)


def _versioned(arm: str, count: int, version: int, week: int, prefix: str, **fields: object):
    return crowd(
        arm,
        count,
        prefix=prefix,
        assigned_version=version,
        exposure_version=version,
        assigned_at=at(7 * week),
        exposed_at=at(7 * week, 1),
        **fields,
    )


# Players who were never exposed are in the sample-ratio rules ----------------------------------


def test_res_011_labels_the_allocation_by_arm_when_arms_are_not_alphabetical(raw_spec) -> None:
    arms = [
        {"name": "variant_b", "allocation": 0.3},
        {"name": "control", "allocation": 0.7, "is_control": True},
    ]
    spec = results_spec(raw_spec, arms=arms)
    rows: list[Row] = []
    for week, (control, variant) in enumerate([(1010, 290), (810, 490)]):
        start = {"assigned_at": at(7 * week), "exposed_at": at(7 * week, 1)}
        rows += crowd("control", control, prefix=f"c{week}", **start)
        rows += crowd("variant_b", variant, prefix=f"v{week}", **start)

    assert evaluate_results(RES_001, spec, rows) is None
    finding = evaluate_results(RES_011, spec, rows)

    assert finding.evidence["allocation"] == {"variant_b": 0.3, "control": 0.7}


# RES-002 --------------------------------------------------------------------------------------


# RES-003 --------------------------------------------------------------------------------------


def test_res_003_counts_a_never_exposed_player_as_the_first_assignment(raw_spec) -> None:
    rows = [
        *crowd("control", 5, prefix="b", assigned_at=at(3), exposed_at=at(3, 1)),
        *crowd("variant_b", 5, prefix="c", assigned_at=at(17), exposed_at=at(17, 1)),
        Row("a_never", assigned_at=at(0), exposed_at=None),
    ]
    spec = results_spec(
        raw_spec,
        arms=TWO_ARMS,
        design__min_duration_days=17,
        design__planned_duration_days=30,
    )

    assert evaluate_results(RES_003, spec, rows) is None


# RES-012 --------------------------------------------------------------------------------------


# RES-013 --------------------------------------------------------------------------------------


def test_an_exposure_on_a_lower_version_than_the_assignment_counts_as_differing(raw_spec) -> None:
    rows = [
        *_versioned("control", 20, 1, 0, "c"),
        *_versioned("variant_b", 10, 2, 0, "a"),
        *crowd("variant_b", 6, prefix="low", assigned_version=3, exposure_version=2),
        *_versioned("variant_b", 5, 1, 0, "one"),
    ]
    spec = results_spec(raw_spec, arms=TWO_ARMS)

    arm = evaluate_results(RES_013, spec, rows).evidence["arms"]["variant_b"]

    assert arm["assigned_differs"] == 6


# --- Small counts: the exact tests (design section 21.4) -----------------------------------------


def _small_week(raw_spec, per_week: list[tuple[int, int]], allocation: tuple[float, float]):
    arms = [
        {"name": "control", "allocation": allocation[0], "is_control": True},
        {"name": "variant_b", "allocation": allocation[1]},
    ]
    rows: list[Row] = []
    for week, (control, variant) in enumerate(per_week):
        start = {"assigned_at": at(7 * week), "exposed_at": at(7 * week, 1)}
        rows += crowd("control", control, prefix=f"c{week}", **start)
        rows += crowd("variant_b", variant, prefix=f"v{week}", **start)
    return results_spec(raw_spec, arms=arms), rows


def test_res_011_still_finds_a_real_mismatch_in_a_small_trailing_week(raw_spec) -> None:
    spec, rows = _small_week(raw_spec, [(900, 100), (900, 100), (900, 100), (10, 20)], (0.9, 0.1))

    finding = evaluate_results(RES_011, spec, rows)

    assert finding.evidence["failing_weeks"] == [3]
    small = finding.evidence["by_week"][3]
    assert small["method"] == "exact" and small["flagged"] is True
    assert finding.evidence["by_week"][0]["method"] == "chi_square"
    assert finding.evidence["total"]["method"] == "chi_square"


def _late_exposure_rows(exposed: tuple[int, int], late: tuple[int, int]) -> list[Row]:
    return [
        *crowd("control", exposed[0] - late[0], prefix="c"),
        *crowd("control", late[0], prefix="cl", **LATE),
        *crowd("variant_b", exposed[1] - late[1], prefix="v"),
        *crowd("variant_b", late[1], prefix="vl", **LATE),
    ]


def test_the_committed_exports_late_exposure_is_tested_exactly_and_still_gives_p_0_72(
    raw_spec, export
) -> None:
    finding = RES_012.evaluate(ResultsContext.of(results_spec(raw_spec), export))

    homogeneity = finding.evidence["homogeneity"]
    assert finding.severity == "warning"
    assert homogeneity["method"] == "exact"  # variant_c expects 781 * 198 / 2824 = 54.8 late
    assert homogeneity["smallest_expected"] == pytest.approx(54.76, abs=0.005)
    assert homogeneity["p_value"] == pytest.approx(0.7215, abs=0.00005)
    assert homogeneity["chi_square"] == pytest.approx(0.6598, abs=0.00005)
