"""What the results rules look at: the export joined to its spec (design sections 21.3, 21.8)."""

from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from results_helpers import ARMS, T0, Row, at, build_data, results_spec

from referee.data import load_export
from referee.methods import two_proportion_difference, welch_difference
from referee.results import (
    METRICS,
    PlayerRecord,
    ResultsContext,
    ResultsError,
    effect_estimate,
)

FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _context(raw_spec: dict, rows: list[Row], **changes: object) -> ResultsContext:
    return ResultsContext.of(results_spec(raw_spec, **changes), build_data(rows))


def _refusal(raw_spec: dict, rows: list[Row], **changes: object) -> tuple[str, ...]:
    with pytest.raises(ResultsError) as caught:
        _context(raw_spec, rows, **changes)
    return caught.value.problems


# --- One record per player ---------------------------------------------------------------


def test_each_assigned_player_is_joined_to_the_first_exposure_and_the_outcome(raw_spec) -> None:
    rows = [
        Row(
            "p1",
            "variant_b",
            assigned_at=at(1),
            exposed_at=at(1, 2),
            assigned_version=1,
            exposure_version=2,
            sessions=5,
            purchases=2,
            revenue=9.5,
            first_purchase_at=at(2),
            window_end=at(8),
        ),
        Row("p2", "control"),
    ]

    p1, p2 = _context(raw_spec, rows).players

    assert p1 == PlayerRecord(
        player_id="p1",
        arm="variant_b",
        assigned_at=at(1),
        assigned_version=1,
        first_exposed_at=at(1, 2),
        first_exposure_version=2,
        sessions_7d=5,
        purchases_7d=2,
        revenue_usd_7d=9.5,
        first_purchase_at=at(2),
        window_end=at(8),
    )
    assert (p2.player_id, p2.window_end) == ("p2", T0 + timedelta(days=7))


def test_the_first_of_a_players_exposures_is_the_one_that_counts(raw_spec) -> None:
    row = Row(
        "p1",
        exposed_at=at(0, 5),
        exposure_version=2,
        extra_exposures=((at(0, 1), 1), (at(0, 9), 2)),
    )

    (record,) = _context(raw_spec, [row]).players

    assert (record.first_exposed_at, record.first_exposure_version) == (at(0, 1), 1)


def test_a_player_who_was_never_exposed_is_assigned_but_not_analysed(raw_spec) -> None:
    context = _context(raw_spec, [Row("p1"), Row("p2", exposed_at=None)])

    never = [p for p in context.players if not p.exposed]

    assert [p.player_id for p in never] == ["p2"]
    assert never[0].first_exposure_version is None and not never[0].late_exposed
    assert [p.player_id for p in context.analysed] == ["p1"]


@pytest.mark.parametrize(
    ("exposed_hours", "late"),
    [(47.99, False), (48.0, False), (48.01, True), (0.0, False)],
    ids=["before", "at-the-instant", "after", "at-assignment"],
)
def test_a_player_is_late_only_when_first_exposed_strictly_after_the_first_purchase(
    raw_spec, exposed_hours: float, late: bool
) -> None:
    row = Row(
        "p1",
        exposed_at=at(0, exposed_hours),
        purchases=1,
        first_purchase_at=at(2),
    )

    (record,) = _context(raw_spec, [row]).players

    assert record.late_exposed is late


def test_a_player_who_never_bought_cannot_be_late(raw_spec) -> None:
    (record,) = _context(raw_spec, [Row("p1", exposed_at=at(5))]).players

    assert not record.late_exposed


def test_the_analysed_players_are_those_exposed_and_not_late_with_every_arm_counted(
    raw_spec,
) -> None:
    rows = [
        Row("a1", "control"),
        Row("a2", "control", exposed_at=None),
        Row("a3", "control", purchases=1, first_purchase_at=at(0, 1), exposed_at=at(0, 2)),
        Row("b1", "variant_b"),
    ]

    context = _context(raw_spec, rows)

    assert context.count_by_arm(context.players) == {"control": 3, "variant_b": 1, "variant_c": 0}
    assert context.count_by_arm(context.analysed) == {"control": 1, "variant_b": 1, "variant_c": 0}
    assert list(context.count_by_arm([])) == list(ARMS)  # the spec's order, all zeros


def test_players_come_back_in_player_order_whatever_the_order_they_were_built_in(raw_spec) -> None:
    rows = [Row("p3"), Row("p1"), Row("p2")]

    assert [p.player_id for p in _context(raw_spec, rows).players] == ["p1", "p2", "p3"]


# --- The origin of the weeks -------------------------------------------------------------


def test_weeks_count_from_the_first_assignment_when_no_start_is_registered(raw_spec) -> None:
    rows = [Row("p1", assigned_at=at(2), exposed_at=at(2, 1)), Row("p2", assigned_at=at(9))]

    context = _context(raw_spec, rows)

    assert context.origin == at(2)
    assert [context.week_of(p.assigned_at) for p in context.players] == [0, 1]
    assert context.ignored_before_start == ()


@pytest.mark.parametrize(
    ("days", "week"),
    [(6.999, 0), (7.0, 1), (13.999, 1), (14.0, 2), (-0.001, -1)],
)
def test_a_week_is_seven_days_from_the_origin(raw_spec, days: float, week: int) -> None:
    context = _context(raw_spec, [Row("p1")])

    assert context.week_of(at(days)) == week


def test_assignments_before_the_registered_start_are_left_out_and_listed(raw_spec) -> None:
    rows = [
        Row("early", assigned_at=at(-3)),
        Row("p1", assigned_at=at(0)),
        Row("p2", assigned_at=at(8)),
    ]

    context = _context(raw_spec, rows, design__start_utc="2026-04-11T00:00:00Z")

    assert context.origin == T0
    assert [p.player_id for p in context.players] == ["p1", "p2"]
    assert context.ignored_before_start == ("early",)
    assert context.count_by_arm(context.players)["control"] == 2
    assert [context.week_of(p.assigned_at) for p in context.players] == [0, 1]


def test_a_start_before_the_first_assignment_is_the_origin(raw_spec) -> None:
    context = _context(
        raw_spec, [Row("p1", assigned_at=at(3))], design__start_utc="2026-04-10T00:00:00Z"
    )

    assert context.origin == at(-1) and context.week_of(at(3)) == 0
    assert context.ignored_before_start == ()


def test_a_player_assigned_exactly_at_the_start_is_kept(raw_spec) -> None:
    context = _context(
        raw_spec, [Row("p1", assigned_at=T0)], design__start_utc="2026-04-11T00:00:00Z"
    )

    assert [p.player_id for p in context.players] == ["p1"]


# --- What cannot be reviewed against the spec ---------------------------------------------


def test_an_export_with_nobody_after_the_start_is_refused(raw_spec) -> None:
    problems = _refusal(
        raw_spec, [Row("p1", assigned_at=at(-3))], design__start_utc="2026-04-11T00:00:00Z"
    )

    assert problems == ("no player was assigned at or after design.start_utc",)


def test_an_arm_the_spec_does_not_list_is_refused(raw_spec) -> None:
    problems = _refusal(raw_spec, [Row("p1"), Row("p2", "variant_z")])

    assert len(problems) == 1 and "arms the spec does not list: ['variant_z']" in problems[0]


@pytest.mark.parametrize(
    ("name", "kind", "fragment"),
    [
        ("subscription_conversion_7d", "binary", "is not a metric the export holds"),
        ("sessions_7d", "binary", "is binary in the spec but continuous in the export"),
        ("purchased_7d", "continuous", "is continuous in the spec but binary in the export"),
        ("revenue_usd_7d", "ratio", "is ratio in the spec but continuous in the export"),
    ],
)
def test_a_primary_metric_the_export_cannot_give_is_refused_with_the_registry(
    raw_spec, name: str, kind: str, fragment: str
) -> None:
    baseline = {"baseline": 0.05} if kind == "binary" else {"baseline": 4.0, "baseline_std": 2.0}

    problems = _refusal(
        raw_spec,
        [Row("p1")],
        primary_metric={"name": name, "kind": kind, **baseline},
    )

    assert len(problems) == 1 and problems[0].startswith("primary_metric.")
    assert fragment in problems[0]
    if "registry" in fragment or "not a metric" in fragment:
        assert "sessions_7d, purchases_7d, revenue_usd_7d, purchased_7d" in problems[0]


def test_a_guardrail_the_export_does_not_hold_is_refused_by_position(raw_spec) -> None:
    good = {
        "name": "sessions_7d",
        "kind": "continuous",
        "baseline": 4.0,
        "baseline_std": 2.0,
        "harmful_direction": "decrease",
        "tolerance_relative": 0.05,
    }
    bad = dict(good, name="refund_rate_14d", kind="binary", baseline=0.02, baseline_std=None)

    problems = _refusal(raw_spec, [Row("p1")], guardrails=[good, bad])

    assert len(problems) == 1 and problems[0].startswith("guardrails[1].name: 'refund_rate_14d'")


def test_every_problem_is_reported_at_once(raw_spec) -> None:
    problems = _refusal(
        raw_spec,
        [Row("p1", "variant_z")],
        primary_metric={"name": "nope", "kind": "binary", "baseline": 0.05},
    )

    assert len(problems) == 2
    with pytest.raises(ResultsError, match="2 problems") as caught:
        _context(
            raw_spec,
            [Row("p1", "variant_z")],
            primary_metric={"name": "nope", "kind": "binary", "baseline": 0.05},
        )
    assert str(caught.value).splitlines()[1].startswith("  - ")


def test_hand_built_data_without_an_outcome_for_an_assigned_player_is_refused(raw_spec) -> None:
    data = build_data([Row("p1"), Row("p2")])
    data = type(data)(
        experiment_id=data.experiment_id,
        assignments=data.assignments,
        exposures=data.exposures,
        outcomes=data.outcomes[:1],
    )

    with pytest.raises(ResultsError) as caught:
        ResultsContext.of(results_spec(raw_spec), data)

    assert caught.value.problems == ("1 assigned players have no outcome row (first: 'p2')",)


def test_an_export_with_no_assignments_is_refused(raw_spec) -> None:
    assert _refusal(raw_spec, []) == ("the export has no assignments",)


# --- The plan, the metrics and the arms --------------------------------------------------


def test_the_required_size_is_found_by_arm_name(raw_spec) -> None:
    context = _context(raw_spec, [Row("p1")])

    assert context.plan is not None and context.power_error is None
    assert dict(context.plan.required_per_arm).keys() == set(ARMS)
    assert all(context.required_n(arm) == context.plan.required_per_arm[0][1] for arm in ARMS)
    assert context.required_n("no_such_arm") is None


def test_a_design_that_cannot_be_sized_has_a_reason_and_no_required_size(raw_spec) -> None:
    context = _context(
        raw_spec,
        [Row("p1")],
        primary_metric={"name": "purchased_7d", "kind": "binary", "baseline": 0.9},
        design__mde_relative=0.2,
    )

    assert context.plan is None and context.power_error
    assert context.required_n("control") is None


def test_the_control_and_the_arm_names_come_from_the_spec(raw_spec) -> None:
    context = _context(raw_spec, [Row("p1")])

    assert context.control == "control" and context.arm_names == ARMS


def test_the_export_metrics_are_the_four_the_design_names() -> None:
    record = PlayerRecord(
        player_id="p",
        arm="control",
        assigned_at=T0,
        assigned_version=1,
        first_exposed_at=T0,
        first_exposure_version=1,
        sessions_7d=4,
        purchases_7d=2,
        revenue_usd_7d=7.25,
        first_purchase_at=T0,
        window_end=None,
    )

    never_bought = replace(record, purchases_7d=0, revenue_usd_7d=0.0, first_purchase_at=None)

    assert list(METRICS) == ["sessions_7d", "purchases_7d", "revenue_usd_7d", "purchased_7d"]
    assert [m.value(never_bought) for m in METRICS.values()] == [4.0, 0.0, 0.0, 0.0]
    assert [(m.kind, m.value(record)) for m in METRICS.values()] == [
        ("continuous", 4.0),
        ("continuous", 2.0),
        ("continuous", 7.25),
        ("binary", 1.0),
    ]


# --- The committed export of the lab's 5,000-player experiment ------------------------------


def test_on_the_committed_export_198_players_are_late_and_the_rest_are_analysed(raw_spec) -> None:
    context = ResultsContext.of(results_spec(raw_spec), load_export(FIXTURE, "hybrid_offer_page"))

    assert len(context.players) == 2824 and len(context.analysed) == 2824 - 198
    assert sum(p.late_exposed for p in context.players) == 198
    assert context.count_by_arm(context.players) == {
        "control": 997,
        "variant_b": 1046,
        "variant_c": 781,
    }
    assert context.count_by_arm(context.analysed) == {
        "control": 926,
        "variant_b": 969,
        "variant_c": 731,
    }
    assert sorted(Counter(context.week_of(p.assigned_at) for p in context.players).items()) == [
        (0, 1006),
        (1, 951),
        (2, 867),
    ]
    assert context.origin.isoformat() == "2026-04-11T00:02:25+00:00"
    assert context.exported_at is None and context.ignored_before_start == ()


def test_on_the_committed_export_a_registered_start_leaves_out_the_earlier_assignments(
    raw_spec,
) -> None:
    data = load_export(FIXTURE, "hybrid_offer_page")
    context = ResultsContext.of(
        results_spec(raw_spec, design__start_utc="2026-04-18T00:00:00Z"), data
    )
    expected = sum(a.assigned_at < context.origin for a in data.assignments)

    assert 0 < expected < 2824
    assert len(context.ignored_before_start) == expected
    assert len(context.players) == 2824 - expected
    assert context.week_of(context.origin) == 0


# --- The estimate the rules quote ---------------------------------------------------------------


def _estimate_rows() -> list[Row]:
    return [
        *[Row(f"c{i:02d}", "control", sessions=2 + i % 5, purchases=int(i < 6)) for i in range(40)],
        *[
            Row(f"b{i:02d}", "variant_b", sessions=3 + i % 7, purchases=int(i < 12))
            for i in range(40)
        ],
        *[Row(f"z{i:02d}", "variant_c", sessions=9) for i in range(40)],
    ]


def test_a_binary_metric_is_estimated_with_the_two_proportion_interval(raw_spec) -> None:
    context = _context(raw_spec, _estimate_rows())

    got = effect_estimate(context, "variant_b", context.players)
    expected = two_proportion_difference(12, 40, 6, 40)

    assert got == {
        "n_treatment": 40,
        "n_control": 40,
        "difference": round(expected.difference, 6),
        "ci_low": round(expected.ci_low, 6),
        "ci_high": round(expected.ci_high, 6),
        "confidence": 0.95,
    }


def test_a_continuous_metric_is_estimated_with_welchs_interval(raw_spec) -> None:
    sessions = {"name": "sessions_7d", "kind": "continuous", "baseline": 4.0, "baseline_std": 2.0}
    context = _context(raw_spec, _estimate_rows(), primary_metric=sessions)

    got = effect_estimate(context, "variant_b", context.players)
    expected = welch_difference(
        [float(3 + i % 7) for i in range(40)], [float(2 + i % 5) for i in range(40)]
    )

    assert got["difference"] == round(expected.difference, 6)
    assert (got["ci_low"], got["ci_high"]) == (
        round(expected.ci_low, 6),
        round(expected.ci_high, 6),
    )


def test_the_estimate_uses_only_the_players_it_is_given_and_the_two_arms_asked_for(
    raw_spec,
) -> None:
    context = _context(raw_spec, _estimate_rows())
    some = [p for p in context.players if not p.player_id.endswith("00")]

    got = effect_estimate(context, "variant_b", some)

    assert (got["n_treatment"], got["n_control"]) == (39, 39)  # variant_c is not in it
    assert effect_estimate(context, "variant_b", [])["n_treatment"] == 0


def test_an_estimate_that_cannot_be_made_carries_its_reason_and_the_counts(raw_spec) -> None:
    context = _context(raw_spec, [Row("c1", "control"), Row("b1", "variant_b")])

    got = effect_estimate(context, "variant_b", context.players)

    assert got["n_treatment"] == got["n_control"] == 1
    assert "every unit has the same outcome" in got["error"]
    assert "difference" not in got


# --- After the independent review of 4b-1 ---------------------------------------------------------


def test_players_and_the_ignored_come_back_in_player_order_whatever_order_the_data_is_in(
    raw_spec,
) -> None:
    rows = [
        Row("b", assigned_at=at(1)),
        Row("a", assigned_at=at(2)),
        Row("y", assigned_at=at(-3)),
        Row("x", assigned_at=at(-2)),
    ]
    data = build_data(rows)
    data = replace(data, assignments=data.assignments[::-1])
    spec = results_spec(raw_spec, design__start_utc="2026-04-11T00:00:00Z")

    context = ResultsContext.of(spec, data)

    assert [p.player_id for p in context.players] == ["a", "b"]
    assert context.ignored_before_start == ("x", "y")


def test_unknown_arms_are_listed_in_sorted_order_and_beside_the_arms_the_spec_has(
    raw_spec,
) -> None:
    names = ["zeta", "alpha", "mid", "omega", "beta", "kappa", "delta"]

    (problem,) = _refusal(raw_spec, [Row(f"p{i}", name) for i, name in enumerate(names)])

    assert str(sorted(names)) in problem
    assert "(the spec's arms: ['control', 'variant_b', 'variant_c'])" in problem


def test_the_first_player_without_an_outcome_is_the_first_in_player_order(raw_spec) -> None:
    data = build_data([Row("p1"), Row("p2"), Row("p3")])
    data = replace(data, outcomes=data.outcomes[:1])

    with pytest.raises(ResultsError) as caught:
        ResultsContext.of(results_spec(raw_spec), data)

    assert caught.value.problems == ("2 assigned players have no outcome row (first: 'p2')",)


def test_one_problem_is_not_pluralised_in_the_header(raw_spec) -> None:
    with pytest.raises(ResultsError) as caught:
        _context(raw_spec, [])

    assert str(caught.value).splitlines()[0].endswith(": 1 problem")


@pytest.mark.parametrize("declared", ["none", "bonferroni", "dunnett", None])
def test_the_power_plan_honours_the_declared_alpha_adjustment(raw_spec, declared) -> None:
    from referee.power import plan_power

    spec = results_spec(raw_spec, design__mde_relative=1.5, design__alpha_adjustment=declared)
    context = ResultsContext.of(spec, build_data([Row("p1")]))
    adjustment = "none" if declared == "none" else "bonferroni"

    assert context.plan == plan_power(spec, alpha_adjustment=adjustment)
    default = ResultsContext.of(
        results_spec(raw_spec, design__mde_relative=1.5), build_data([Row("p1")])
    )
    if declared == "none":
        assert context.required_n("control") < default.required_n("control")


def test_the_control_is_the_arm_marked_so_wherever_it_is_listed_and_whatever_it_is_called(
    raw_spec,
) -> None:
    arms = [
        {"name": "variant_b", "allocation": 0.5},
        {"name": "holdout", "allocation": 0.5, "is_control": True},
    ]

    context = _context(raw_spec, [Row("p1", "holdout"), Row("p2", "variant_b")], arms=arms)

    assert context.control == "holdout"


def test_the_context_carries_the_experiment_id_and_the_time_of_the_export(raw_spec) -> None:
    from datetime import UTC, datetime

    moment = datetime(2026, 5, 9, 6, tzinfo=UTC)
    data = build_data([Row("p1")], experiment_id="exp_7", exported_at=moment)

    context = ResultsContext.of(results_spec(raw_spec), data)

    assert (context.experiment_id, context.exported_at) == ("exp_7", moment)


def test_a_first_exposure_on_configuration_version_zero_is_version_zero(raw_spec) -> None:
    (record,) = _context(raw_spec, [Row("p1", assigned_version=3, exposure_version=0)]).players

    assert record.version == 0


def test_a_player_who_bought_but_was_never_exposed_is_not_late(raw_spec) -> None:
    rows = [Row("p1", exposed_at=None, purchases=1, first_purchase_at=at(1))]

    (record,) = _context(raw_spec, rows).players

    assert record.late_exposed is False and not record.exposed


# --- A player's first exposure is the earliest, whatever order the data comes in -----------------


def _first(raw_spec, rows: list[Row], *, reverse: bool = True):
    data = build_data(rows)
    if reverse:
        data = replace(data, exposures=data.exposures[::-1])
    (record,) = ResultsContext.of(results_spec(raw_spec), data).players
    return record


def test_the_first_exposure_is_the_earliest_even_when_the_exposures_arrive_reversed(
    raw_spec,
) -> None:
    row = Row(
        "p1",
        exposed_at=at(0, 1),
        exposure_version=1,
        extra_exposures=((at(0, 3), 2),),
        purchases=1,
        first_purchase_at=at(0, 2),
    )

    for reverse in (False, True):
        record = _first(raw_spec, [row], reverse=reverse)
        assert (record.first_exposed_at, record.version) == (at(0, 1), 1)
        assert record.late_exposed is False


def test_two_exposures_at_one_instant_take_the_lower_version_in_any_order(raw_spec) -> None:
    row = Row("p1", exposed_at=at(0, 1), exposure_version=2, extra_exposures=((at(0, 1), 1),))

    for reverse in (False, True):
        assert _first(raw_spec, [row], reverse=reverse).version == 1


def test_an_exposure_without_a_version_is_lower_than_one_with_a_version_at_the_same_instant(
    raw_spec,
) -> None:
    row = Row(
        "p1",
        assigned_version=7,
        exposed_at=at(0, 1),
        exposure_version=3,
        extra_exposures=((at(0, 1), None),),
    )

    for reverse in (False, True):
        record = _first(raw_spec, [row], reverse=reverse)
        assert record.first_exposure_version is None and record.version == 7


# --- A player appearing twice is refused ---------------------------------------------------------


def test_a_player_assigned_twice_is_refused_not_counted_twice(raw_spec) -> None:
    data = build_data([Row("p1"), Row("p2")])
    data = replace(data, assignments=(*data.assignments, data.assignments[0]))

    with pytest.raises(ResultsError) as caught:
        ResultsContext.of(results_spec(raw_spec), data)

    assert caught.value.problems == (
        "1 players appear more than once in the assignments (first: 'p1')",
    )


def test_a_player_with_two_outcome_rows_is_refused_not_resolved_to_the_last(raw_spec) -> None:
    data = build_data([Row("p1"), Row("p2")])
    data = replace(data, outcomes=(*data.outcomes, replace(data.outcomes[1], purchases_7d=9)))

    with pytest.raises(ResultsError) as caught:
        ResultsContext.of(results_spec(raw_spec), data)

    assert caught.value.problems == (
        "1 players appear more than once in the outcomes (first: 'p2')",
    )


# --- Values too large for a float are infinite, which the statistics refuse ----------------------


def test_a_session_count_beyond_any_float_is_infinite_and_the_estimate_says_why(raw_spec) -> None:
    spec = results_spec(
        raw_spec,
        primary_metric__name="sessions_7d",
        primary_metric__kind="continuous",
        primary_metric__baseline=10.0,
        primary_metric__baseline_std=5.0,
    )
    rows = [
        Row("c1", sessions=10**400),
        Row("c2", sessions=3),
        Row("c3", sessions=4),
        Row("b1", "variant_b", sessions=3),
        Row("b2", "variant_b", sessions=5),
        Row("b3", "variant_b", sessions=7),
    ]
    context = ResultsContext.of(spec, build_data(rows))

    got = effect_estimate(context, "variant_b", context.players)

    huge = next(p for p in context.players if p.player_id == "c1")
    assert context.metrics["sessions_7d"].value(huge) == float("inf")
    assert got["error"] == "control must hold only finite numbers"
    assert (got["n_treatment"], got["n_control"]) == (3, 3)


def test_an_empty_group_has_a_reason_of_its_own_in_the_estimate(raw_spec) -> None:
    context = _context(raw_spec, [Row("c1"), Row("c2")])

    assert effect_estimate(context, "variant_b", context.players) == {
        "n_treatment": 0,
        "n_control": 2,
        "error": "the treatment group has no players",
    }
    assert effect_estimate(context, "variant_b", [])["error"] == (
        "the treatment and control group has no players"
    )


def test_effect_estimates_gives_every_non_control_arm_from_one_pass(raw_spec) -> None:
    from referee.results import effect_estimates

    rows = [
        *[Row(f"c{i}", "control", purchases=int(i < 4)) for i in range(20)],
        *[Row(f"b{i}", "variant_b", purchases=int(i < 8)) for i in range(20)],
        *[Row(f"v{i}", "variant_c", purchases=int(i < 2)) for i in range(20)],
    ]
    context = _context(raw_spec, rows)

    got = effect_estimates(context, context.players)

    assert list(got) == ["variant_b", "variant_c"]
    assert got["variant_b"] == effect_estimate(context, "variant_b", context.players)
    assert got["variant_b"]["difference"] == 0.2 and got["variant_c"]["difference"] == -0.1
    assert list(effect_estimates(context, context.players, arms=["variant_c"])) == ["variant_c"]


def test_the_analysed_players_are_worked_out_once_and_the_context_can_be_pickled(
    raw_spec,
) -> None:
    import pickle

    context = _context(raw_spec, [Row("p1"), Row("p2", exposed_at=None)])
    copy = pickle.loads(pickle.dumps(context))

    assert context.analysed is context.analysed
    assert [p.player_id for p in context.analysed] == ["p1"]
    assert [p.player_id for p in copy.analysed] == ["p1"]
    assert METRICS["sessions_7d"].value(copy.players[0]) == 3.0
    assert copy == context
