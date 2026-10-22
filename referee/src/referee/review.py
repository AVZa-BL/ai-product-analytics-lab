"""Run the design-review rules over a spec, and the results rules over a spec and its data."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, timedelta
from typing import Any

from referee.data import ExperimentData
from referee.findings import DesignReview, ResultsReview
from referee.results import ResultsContext
from referee.rules import ALL_RULES, RESULTS_RULES, ReviewContext, Rule
from referee.spec import ExperimentSpec


def review_design(spec: ExperimentSpec, *, rules: Sequence[Rule] = ALL_RULES) -> DesignReview:
    """Review a valid spec's design. Same spec in, same review out."""
    context = ReviewContext.of(spec)
    findings = [f for rule in rules if (f := rule.evaluate(context)) is not None]
    return DesignReview(spec_id=spec.id, findings=tuple(findings))


def review_context(
    context: ResultsContext, *, rules: Sequence[Rule[ResultsContext]] = RESULTS_RULES
) -> ResultsReview:
    """Run the results rules over a context that was already made, so that a report can use it."""
    findings = [f for rule in rules if (f := rule.evaluate(context)) is not None]
    return ResultsReview(
        spec_id=context.spec.id,
        experiment_id=context.experiment_id,
        rules_run=tuple(rule.id for rule in rules),
        findings=tuple(findings),
        origin=context.origin,
        ignored_before_start=context.ignored_before_start,
    )


def review_results(
    spec: ExperimentSpec,
    data: ExperimentData,
    *,
    rules: Sequence[Rule[ResultsContext]] = RESULTS_RULES,
) -> ResultsReview:
    """Review an experiment's data against its spec. Same spec and data in, same review out.

    Raises `ResultsError` when the data cannot be read against the spec at all.
    """
    return review_context(ResultsContext.of(spec, data), rules=rules)


ORIGIN_SHIFT_DAYS = (1, 2, 3, 4, 5, 6)


def _findings_of(review: ResultsReview) -> set[str]:
    return {f"{finding.rule_id}:{finding.severity}" for finding in review.findings}


def origin_sensitivity(
    spec: ExperimentSpec,
    data: ExperimentData,
    review: ResultsReview,
    *,
    rules: Sequence[Rule[ResultsContext]] = RESULTS_RULES,
) -> dict[str, Any]:
    """Whether the findings stay the same when the weeks are counted from an earlier origin.

    Without a registered `design.start_utc` the origin is the first assignment, and a stray
    early row moves it and every block edge with it (design section 21.8). The review is run
    again with the origin 1 to 6 days earlier, with nobody added or left out, and compared
    with `review`, which was made at the actual origin. Judgement: what is compared is which
    rules fire and at which severity, not only the verdict, because RES-007 is a warning and
    appearing or disappearing would not change a verdict that other warnings already set.
    With a registered origin nothing is varied: players before it were left out on purpose, and
    an earlier origin would bring them back.
    """
    if spec.design.start_utc is not None:
        return {"ran": False, "reason": "design.start_utc is registered", "shifts": []}
    actual = _findings_of(review)
    assert review.origin is not None
    shifts = []
    for days in ORIGIN_SHIFT_DAYS:
        start = (review.origin - timedelta(days=days)).astimezone(UTC)
        shifted = replace(
            spec, design=replace(spec.design, start_utc=start.isoformat().replace("+00:00", "Z"))
        )
        other = review_context(ResultsContext.of(shifted, data), rules=rules)
        found = _findings_of(other)
        shifts.append(
            {
                "days_earlier": days,
                "same": found == actual,
                "verdict": other.verdict,
                "appear": sorted(found - actual),
                "disappear": sorted(actual - found),
            }
        )
    return {"ran": True, "reason": None, "shifts": shifts}
