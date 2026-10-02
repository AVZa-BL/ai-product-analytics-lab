"""Rules about the question the experiment asks (HYP)."""

from __future__ import annotations

from typing import Any

from referee.rules.base import ReviewContext, Rule
from referee.rules.references import DENG_KNOBLICH_LU_2018


def _normalised(statement: str) -> str:
    return " ".join(statement.casefold().split())


def _identical_statements(context: ReviewContext) -> dict[str, Any] | None:
    hypothesis = context.spec.hypothesis
    if _normalised(hypothesis.null) != _normalised(hypothesis.alternative):
        return None
    return {"null": hypothesis.null, "alternative": hypothesis.alternative}


def _no_governed_reference(context: ReviewContext) -> dict[str, Any] | None:
    metric = context.spec.primary_metric
    if metric.governed_reference is not None:
        return None
    return {"metric": metric.name, "governed_reference": None}


def _units_differ(context: ReviewContext) -> dict[str, Any] | None:
    population = context.spec.population
    if population.analysis_unit == population.randomization_unit:
        return None
    return {
        "randomization_unit": population.randomization_unit,
        "analysis_unit": population.analysis_unit,
    }


def _one_sided(context: ReviewContext) -> dict[str, Any] | None:
    design = context.spec.design
    if design.sided != "one_sided":
        return None
    return {"sided": design.sided, "direction": context.spec.hypothesis.direction}


def _ratio_metric(context: ReviewContext) -> dict[str, Any] | None:
    metric = context.spec.primary_metric
    if metric.kind != "ratio":
        return None
    return {"metric": metric.name, "kind": metric.kind, "baseline_std": metric.baseline_std}


HYP_001 = Rule(
    id="HYP-001",
    severity="blocker",
    title="Null and alternative hypotheses are the same statement",
    fires_when=(
        "The null and alternative statements are the same text once case is ignored and runs "
        "of whitespace are collapsed."
    ),
    why_it_matters=(
        "A test weighs an alternative against a null. If both say the same thing, no outcome "
        "can favour one over the other, so the experiment cannot be falsified."
    ),
    remediation=(
        "State the null as no effect, and the alternative as the specific change, with its "
        "direction, that the treatment is expected to cause."
    ),
    references=(),
    check=_identical_statements,
)

HYP_002 = Rule(
    id="HYP-002",
    severity="warning",
    title="Primary metric has no governed reference",
    fires_when="primary_metric.governed_reference is absent.",
    why_it_matters=(
        "Without a governed definition the metric can be computed differently at planning "
        "and at readout, and the result cannot be reproduced or audited."
    ),
    remediation=(
        "Define the metric in docs/metrics/ and set primary_metric.governed_reference to that file."
    ),
    references=(),
    check=_no_governed_reference,
)

HYP_003 = Rule(
    id="HYP-003",
    severity="warning",
    title="Analysis unit differs from randomization unit",
    fires_when="population.analysis_unit differs from population.randomization_unit.",
    why_it_matters=(
        "Units that are randomized together are not independent when they are analysed at a "
        "different level, for example many sessions from one player. Treating the analysed "
        "rows as independent understates the variance and makes false positives more likely."
    ),
    remediation=(
        "Aggregate to the randomization unit before testing, or use a variance estimate that "
        "accounts for the grouping, such as the delta method or cluster-robust standard errors."
    ),
    references=(DENG_KNOBLICH_LU_2018,),
    check=_units_differ,
)

HYP_004 = Rule(
    id="HYP-004",
    severity="warning",
    title="One-sided test requested",
    fires_when="design.sided is one_sided.",
    why_it_matters=(
        "A one-sided test cannot detect an effect in the other direction, and choosing it "
        "after seeing the data halves the p-value without adding evidence. It is defensible "
        "only when the direction was fixed in advance."
    ),
    remediation=(
        "Record before launch why an effect in the other direction is impossible or irrelevant "
        "to the decision; otherwise use a two-sided test."
    ),
    references=(),
    check=_one_sided,
)

HYP_005 = Rule(
    id="HYP-005",
    severity="warning",
    title="Primary metric is a ratio of two unit-level quantities",
    fires_when="primary_metric.kind is ratio. Guardrails are not checked.",
    why_it_matters=(
        "The variance of a ratio depends on both quantities and on how they move together, so "
        "the standard error of a per-unit mean does not apply. The sample size then rests on "
        "the standard deviation of the ratio that the spec supplies."
    ),
    remediation=(
        "Estimate the standard deviation of the ratio with the delta method, use it in "
        "baseline_std, and analyse the results with the same method."
    ),
    references=(DENG_KNOBLICH_LU_2018,),
    check=_ratio_metric,
)

HYPOTHESIS_RULES = (HYP_001, HYP_002, HYP_003, HYP_004, HYP_005)
