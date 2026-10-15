"""What the results rules look at: the export joined to its spec (design sections 21.3, 21.8)."""

from dataclasses import replace
from pathlib import Path

import pytest
from results_helpers import T0, Row, at, build_data, results_spec

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


def test_a_player_who_was_never_exposed_is_assigned_but_not_analysed(raw_spec) -> None:
    context = _context(raw_spec, [Row("p1"), Row("p2", exposed_at=None)])

    never = [p for p in context.players if not p.exposed]

    assert [p.player_id for p in never] == ["p2"]
    assert never[0].first_exposure_version is None and not never[0].late_exposed
    assert [p.player_id for p in context.analysed] == ["p1"]


@pytest.mark.parametrize(
    ("exposed_hours", "late"),
    [(48.0, False)],
    ids=["at-the-instant"],
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


# --- The origin of the weeks -------------------------------------------------------------


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
        ("purchased_7d", "continuous", "is continuous in the spec but binary in the export"),
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


# --- After the independent review of 4b-1 ---------------------------------------------------------


def test_one_problem_is_not_pluralised_in_the_header(raw_spec) -> None:
    with pytest.raises(ResultsError) as caught:
        _context(raw_spec, [])

    assert str(caught.value).splitlines()[0].endswith(": 1 problem")


@pytest.mark.parametrize("declared", ["none", "dunnett"])
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


# --- A player's first exposure is the earliest, whatever order the data comes in -----------------


def _first(raw_spec, rows: list[Row], *, reverse: bool = True):
    data = build_data(rows)
    if reverse:
        data = replace(data, exposures=data.exposures[::-1])
    (record,) = ResultsContext.of(results_spec(raw_spec), data).players
    return record


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


