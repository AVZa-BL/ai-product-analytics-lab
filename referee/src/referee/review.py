"""Run the design-review rules over a spec, and the results rules over a spec and its data."""

from __future__ import annotations

from collections.abc import Sequence

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
