"""Rules about how the test will be run (PRO)."""

from __future__ import annotations

from typing import Any

from referee.rules.base import ReviewContext, Rule
from referee.rules.references import (
    FABIJAN_ET_AL_2019,
    JOHARI_ET_AL_2017,
    KOHAVI_ET_AL_2012,
    KOHAVI_TANG_XU_2020,
)


def _no_stopping_rule(context: ReviewContext) -> dict[str, Any] | None:
    if context.spec.procedure.stopping_rule is not None:
        return None
    return {"field": "procedure.stopping_rule", "value": None}


def _no_srm_check(context: ReviewContext) -> dict[str, Any] | None:
    cadence = context.spec.procedure.srm_check_cadence
    if cadence not in (None, "none"):
        return None
    return {"field": "procedure.srm_check_cadence", "value": cadence}


def _no_guardrails(context: ReviewContext) -> dict[str, Any] | None:
    if context.spec.guardrails:
        return None
    return {"guardrails": 0}


def _no_bucketing_salt(context: ReviewContext) -> dict[str, Any] | None:
    if context.spec.procedure.bucketing_salt is not None:
        return None
    return {"field": "procedure.bucketing_salt", "value": None}


PRO_001 = Rule(
    id="PRO-001",
    severity="blocker",
    title="No stopping rule declared",
    why_it_matters=(
        "Looking at results repeatedly and stopping when they look significant pushes the "
        "false-positive rate of a fixed-horizon test well above the chosen alpha. Without a "
        "declared rule, a planned stop cannot be told from a peek."
    ),
    remediation=(
        "Set procedure.stopping_rule to fixed_horizon (analyse once, at the planned end) or "
        "to sequential (and use a test designed for repeated looks)."
    ),
    references=(JOHARI_ET_AL_2017, KOHAVI_TANG_XU_2020),
    check=_no_stopping_rule,
)

PRO_002 = Rule(
    id="PRO-002",
    severity="warning",
    title="No sample-ratio-mismatch check scheduled",
    why_it_matters=(
        "When arm counts depart from the registered allocation, assignment or logging is "
        "broken and the comparison is invalid. The mismatch is found only if someone checks."
    ),
    remediation=(
        "Set procedure.srm_check_cadence to daily (recommended) or weekly, and act on a "
        "mismatch before reading any result."
    ),
    references=(FABIJAN_ET_AL_2019, KOHAVI_TANG_XU_2020),
    check=_no_srm_check,
)

PRO_003 = Rule(
    id="PRO-003",
    severity="warning",
    title="No guardrail metrics declared",
    why_it_matters=(
        "A change can improve the primary metric while harming something it does not "
        "measure, such as refunds or retention. Guardrails make that harm visible before a "
        "ship decision."
    ),
    remediation=(
        "Declare at least one guardrail with its harmful direction and a tolerance, for "
        "example a refund rate that must not rise by more than 10% relative."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_no_guardrails,
)

PRO_004 = Rule(
    id="PRO-004",
    severity="info",
    title="Bucketing salt not declared",
    why_it_matters=(
        "Assignment hashes the unit ID with a salt. Reusing one salt across experiments "
        "gives them the same bucket boundaries, which can carry one experiment's effect "
        "into the next."
    ),
    remediation=(
        "Set procedure.bucketing_salt to a value unique to this experiment, for example its id."
    ),
    references=(KOHAVI_ET_AL_2012,),
    check=_no_bucketing_salt,
)

PROCEDURE_RULES = (PRO_001, PRO_002, PRO_003, PRO_004)
