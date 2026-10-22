"""What the results rules look at: the export joined to its spec (design sections 21.3, 21.8)."""

import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from results_helpers import T0, Row, at, build_data, results_spec

from referee import results
from referee.methods import bonferroni, two_proportion_difference, welch_difference
from referee.results import (
    METRICS,
    PlayerRecord,
    ResultsContext,
    ResultsError,
    effect_estimate,
    effect_table,
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
        "the treatment and control groups have no players"
    )


# --- The effect table (design section 22.3) --------------------------------------------------

REVENUE = {
    "primary_metric__name": "revenue_usd_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 1.0,
    "primary_metric__baseline_std": 5.0,
}
CONTROL_REVENUE = [0.0, 0.0, 1.5, 0.0, 4.0, 0.0, 2.5, 0.0]
B_REVENUE = [0.0, 3.0, 5.5, 0.0, 6.0, 2.0, 0.0, 9.0]
C_REVENUE = [0.0, 0.0, 2.0, 1.0, 0.0, 3.5, 0.0, 0.5]


def _revenue_rows(**by_arm: list[float]) -> list[Row]:
    return [
        Row(f"{arm}_{i:02d}", arm, revenue=value)
        for arm, values in by_arm.items()
        for i, value in enumerate(values)
    ]


def test_the_effect_table_is_welchs_test_adjusted_for_the_arms(raw_spec) -> None:
    rows = _revenue_rows(control=CONTROL_REVENUE, variant_b=B_REVENUE, variant_c=C_REVENUE)

    table = effect_table(_context(raw_spec, rows, **REVENUE))

    b = welch_difference(B_REVENUE, CONTROL_REVENUE)
    c = welch_difference(C_REVENUE, CONTROL_REVENUE)
    adjusted = bonferroni([b.p_value, c.p_value]).adjusted
    assert (table["metric"], table["kind"], table["adjustment"]) == (
        "revenue_usd_7d",
        "continuous",
        "bonferroni",
    )
    assert table["comparisons"] == 2
    assert [row["arm"] for row in table["arms"]] == ["variant_b", "variant_c"]
    for row, found, p_adjusted in zip(table["arms"], (b, c), adjusted, strict=True):
        assert (row["n_treatment"], row["n_control"]) == (found.n_treatment, found.n_control)
        assert row["mean_treatment"] == pytest.approx(found.mean_treatment, abs=1e-6)
        assert row["mean_control"] == pytest.approx(found.mean_control, abs=1e-6)
        assert row["difference"] == pytest.approx(found.difference, abs=1e-6)
        assert (row["ci_low"], row["ci_high"]) == pytest.approx(
            (found.ci_low, found.ci_high), abs=1e-6
        )
        assert row["confidence"] == 0.95
        assert row["relative_difference"] == pytest.approx(
            found.difference / found.mean_control, abs=1e-6
        )
        assert row["p_value"] == found.p_value
        assert row["adjusted_p_value"] == p_adjusted


def test_the_effect_table_of_a_binary_metric_is_the_two_proportion_test(raw_spec) -> None:
    buys = {"control": 7, "variant_b": 19, "variant_c": 11}
    rows = [
        Row(f"{arm}_{i:03d}", arm, purchases=int(i < n_buying))
        for arm, n_buying in buys.items()
        for i in range(100)
    ]

    table = effect_table(_context(raw_spec, rows))

    b = two_proportion_difference(19, 100, 7, 100)
    assert table["kind"] == "binary"
    row = table["arms"][0]
    assert (row["mean_treatment"], row["mean_control"]) == (0.19, 0.07)
    assert row["difference"] == pytest.approx(b.difference, abs=1e-6)
    assert (row["ci_low"], row["ci_high"]) == pytest.approx((b.ci_low, b.ci_high), abs=1e-6)
    assert row["p_value"] == b.p_value
    assert row["adjusted_p_value"] == min(1.0, 2 * b.p_value)


@pytest.mark.parametrize(
    ("registered", "adjustment", "times"),
    [
        ("dunnett", "bonferroni", 2),
        ("none", "none", 1),
    ],
)
def test_the_effect_table_adjusts_as_the_power_plan_does(
    raw_spec, registered, adjustment: str, times: int
) -> None:
    rows = _revenue_rows(control=CONTROL_REVENUE, variant_b=B_REVENUE, variant_c=C_REVENUE)

    table = effect_table(_context(raw_spec, rows, design__alpha_adjustment=registered, **REVENUE))

    assert table["adjustment"] == adjustment
    for row in table["arms"]:
        assert row["adjusted_p_value"] == min(1.0, times * row["p_value"])


def test_the_effect_table_reads_the_analysed_players_only(raw_spec) -> None:
    rows = _revenue_rows(control=CONTROL_REVENUE, variant_b=B_REVENUE, variant_c=C_REVENUE)
    rows += [
        Row("never_exposed", "variant_b", exposed_at=None, revenue=1_000.0),
        Row(
            "exposed_after_buying",
            "variant_b",
            exposed_at=at(1),
            purchases=1,
            revenue=1_000.0,
            first_purchase_at=at(0, 1),
        ),
    ]

    row = effect_table(_context(raw_spec, rows, **REVENUE))["arms"][0]

    assert row["n_treatment"] == len(B_REVENUE)
    assert row["mean_treatment"] == pytest.approx(sum(B_REVENUE) / len(B_REVENUE))


def test_an_arm_that_cannot_be_estimated_says_why_and_still_counts_as_a_comparison(
    raw_spec,
) -> None:
    """Control all zeros: variant_b is estimated, with no relative difference; variant_c, also
    all zeros, has no variation to test."""
    rows = _revenue_rows(control=[0.0] * 8, variant_b=B_REVENUE, variant_c=[0.0] * 8)

    table = effect_table(_context(raw_spec, rows, **REVENUE))

    b, c = table["arms"]
    assert "neither group varies" in c["error"] and "p_value" not in c
    assert (c["arm"], c["n_treatment"], c["n_control"]) == ("variant_c", 8, 8)
    assert b["relative_difference"] is None
    assert b["adjusted_p_value"] == min(1.0, 2 * b["p_value"])  # two arms were compared


def test_a_player_whose_window_is_still_open_is_left_out_and_counted(raw_spec) -> None:
    rows = _revenue_rows(control=CONTROL_REVENUE, variant_b=B_REVENUE, variant_c=C_REVENUE)
    exported_at = at(8)
    open_windows = [
        Row("open_control", "control", assigned_at=at(5), exposed_at=at(5, 1), revenue=900.0),
        Row("open_b_1", "variant_b", assigned_at=at(5), exposed_at=at(5, 1), revenue=900.0),
        Row("open_b_2", "variant_b", assigned_at=at(7), exposed_at=at(7, 1), revenue=900.0),
    ]
    closes_at_export = Row("closes_now", "variant_b", revenue=3.0, window_end=exported_at)
    everyone = [*rows, *open_windows, closes_at_export]
    spec = results_spec(raw_spec, **REVENUE)

    known = effect_table(ResultsContext.of(spec, build_data(everyone, exported_at=exported_at)))
    unknown = effect_table(ResultsContext.of(spec, build_data(everyone)))

    assert known["left_out"] == {"control": 1, "variant_b": 2, "variant_c": 0}
    assert known["arms"][0]["n_treatment"] == len(B_REVENUE) + 1  # the window that closes now
    assert known["arms"][0]["n_control"] == len(CONTROL_REVENUE)
    assert known["arms"][0]["mean_treatment"] == pytest.approx((sum(B_REVENUE) + 3.0) / 9)
    assert unknown["left_out"] == {"control": 0, "variant_b": 0, "variant_c": 0}
    assert unknown["arms"][0]["n_treatment"] == len(B_REVENUE) + 3  # no time: nothing is open


def test_the_effect_table_adjusts_for_every_arm_compared_with_control(raw_spec) -> None:
    arms = [{"name": "control", "allocation": 0.25, "is_control": True}] + [
        {"name": name, "allocation": 0.25} for name in ("a", "b", "c")
    ]
    rows = _revenue_rows(control=CONTROL_REVENUE, a=B_REVENUE, b=C_REVENUE, c=C_REVENUE[::-1])

    table = effect_table(_context(raw_spec, rows, arms=arms, **REVENUE))

    assert table["comparisons"] == 3
    assert [row["arm"] for row in table["arms"]] == ["a", "b", "c"]
    assert all(row["adjusted_p_value"] == min(1.0, 3 * row["p_value"]) for row in table["arms"])
    assert any(row["adjusted_p_value"] < 1.0 for row in table["arms"])  # not clipped everywhere


def test_a_relative_difference_that_is_not_a_finite_number_is_left_out(raw_spec) -> None:
    """A control mean of 1.25e-321 is above 0, and the ratio to it overflows."""
    rows = _revenue_rows(control=[0.0] * 7 + [1e-320], variant_b=B_REVENUE, variant_c=C_REVENUE)

    table = effect_table(_context(raw_spec, rows, **REVENUE))

    assert table["arms"][0]["relative_difference"] is None
    json.dumps(table, allow_nan=False)  # every number in the table can be written


@pytest.mark.parametrize(
    ("mean_control", "zeros"),
    [
        (1.0, {"mean_treatment", "difference", "ci_low", "ci_high", "relative_difference"}),
        (-1e-9, {"mean_treatment", "mean_control", "difference", "ci_low", "ci_high"}),
    ],
)
def test_no_number_of_the_table_or_the_estimate_is_a_negative_zero(
    raw_spec, monkeypatch: pytest.MonkeyPatch, mean_control: float, zeros: set[str]
) -> None:
    """A number that rounds to nothing must not be written as -0.0, which JSON keeps."""
    tiny = -1e-9
    found = SimpleNamespace(
        mean_treatment=tiny,
        mean_control=mean_control,
        difference=tiny,
        ci_low=tiny,
        ci_high=tiny,
        confidence=0.95,
        p_value=0.5,
    )
    monkeypatch.setattr(results, "welch_difference", lambda treatment, control: found)
    rows = _revenue_rows(control=CONTROL_REVENUE, variant_b=B_REVENUE, variant_c=C_REVENUE)
    context = _context(raw_spec, rows, **REVENUE)

    row = effect_table(context)["arms"][0]
    estimate = effect_estimate(context, "variant_b", context.players)

    for shown, keys in ((row, zeros), (estimate, {"difference", "ci_low", "ci_high"})):
        written = {key for key, value in shown.items() if isinstance(value, float) and value == 0}
        assert keys <= written
        assert all(math.copysign(1.0, shown[key]) == 1.0 for key in written)


def test_a_window_that_would_close_after_the_calendar_ends_is_still_open(raw_spec) -> None:
    first = datetime(9999, 12, 28, tzinfo=UTC)
    rows = [
        Row(f"{arm}_{i}", arm, assigned_at=first, exposed_at=first + timedelta(minutes=5))
        for arm in ("control", "variant_b", "variant_c")
        for i in range(3)
    ]
    data = build_data(rows, exported_at=datetime(9999, 12, 31, tzinfo=UTC), window_column=False)
    context = ResultsContext.of(results_spec(raw_spec), data)

    assert all(
        player.window_closes_at == datetime.max.replace(tzinfo=UTC) for player in context.players
    )
    assert effect_table(context)["left_out"] == {"control": 3, "variant_b": 3, "variant_c": 3}


def test_an_arm_compared_with_an_empty_control_says_the_control_has_no_players(raw_spec) -> None:
    rows = _revenue_rows(control=[], variant_b=B_REVENUE, variant_c=C_REVENUE)
    rows.append(Row("never_control", "control", exposed_at=None))

    row = effect_table(_context(raw_spec, rows, **REVENUE))["arms"][0]

    assert row["error"] == "the control group has no players"
    assert (row["n_treatment"], row["n_control"]) == (len(B_REVENUE), 0)
