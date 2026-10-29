"""The deterministic checks on a draft.

Nothing here trusts the model. Each claim's quote is searched for in the document it names, a
number must be written in its quote, approximate wording is never accepted as a number, a spec is
built from the claims and read by Referee, the design rules are run on it, and the sizes come from
Referee's power plan. A problem is a blocker, a warning or info. Only blockers that the model can
fix go back to it: a warning is a finding about the design, and fixing it would often mean
inventing something the documents do not say.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from referee.findings import DesignReview
from referee.power import PowerPlan, plan_power
from referee.review import review_design
from referee.spec import ExperimentSpec, SpecError
from tracewright.propose.documents import Document
from tracewright.propose.grounding import quote_in_document

from specwright.draft import Claim, Draft
from specwright.fields import assemble, is_numeric, required_paths
from specwright.numbers import hedges_in, quote_has_number

Status = Literal["ok", "needs_answers", "infeasible", "unresolved"]
SIZE_TOLERANCE = 0.01
# A blocker of these rules is a fact about the brief, not a mistake of the draft: changing a stated
# number to clear it would be inventing. DES-001 says the stated numbers cannot reach the stated
# power, which is what `infeasible` reports.
UNREPAIRABLE_RULES = frozenset({"DES-001"})


@dataclass(frozen=True, kw_only=True)
class Problem:
    code: str
    severity: Literal["blocker", "warning", "info"]
    message: str
    repairable: bool = False
    path: str | None = None

    def line(self) -> str:
        where = f" {self.path}:" if self.path else ""
        return f"[{self.code}]{where} {self.message}"


@dataclass(frozen=True, kw_only=True)
class Question:
    """Something the analyst must answer before a spec can be built."""

    path: str
    kind: Literal["missing", "ambiguous", "omitted"]
    note: str


@dataclass(frozen=True, kw_only=True)
class CheckResult:
    problems: tuple[Problem, ...]
    questions: tuple[Question, ...]
    optional_questions: tuple[Question, ...]  # optional fields the draft leaves out
    values: dict[str, Any]  # path -> value, for the claims that carry one
    spec_dict: dict[str, Any] | None  # built only when nothing is asked
    spec: ExperimentSpec | None
    review: DesignReview | None
    plan: PowerPlan | None
    plan_error: str | None
    inferred: tuple[Claim, ...] = field(default=())

    @property
    def blockers(self) -> tuple[Problem, ...]:
        return tuple(p for p in self.problems if p.severity == "blocker")

    @property
    def to_repair(self) -> tuple[Problem, ...]:
        return tuple(p for p in self.problems if p.severity == "blocker" and p.repairable)

    @property
    def status(self) -> Status:
        """`unresolved` while a blocker other than DES-001 stands (a quote that is not in its
        document, a field the draft left out, a spec Referee refuses); then `needs_answers` when
        the analyst must answer something before a spec can be built; then `infeasible` when the
        spec is built and the stated numbers cannot reach the stated power; else `ok`."""
        if any(p.code != "RULE:DES-001" for p in self.blockers):
            return "unresolved"
        if self.questions:
            return "needs_answers"
        return "infeasible" if self.blockers else "ok"


def _claim_problems(claim: Claim, documents: dict[str, Document]) -> list[Problem]:
    evidence, problems = claim.evidence, []
    if evidence.kind == "document":
        document = documents.get(evidence.document)
        if document is None:
            problems.append(
                Problem(
                    code="QUOTE_DOCUMENT",
                    severity="blocker",
                    message=f"cites a document that was not provided: {evidence.document!r} "
                    f"(the documents are {sorted(documents)})",
                    repairable=True,
                    path=claim.path,
                )
            )
        else:
            found = quote_in_document(evidence.quote, document)
            if found is False:
                problems.append(
                    Problem(
                        code="QUOTE_NOT_FOUND",
                        severity="blocker",
                        message=f"the quote {evidence.quote!r} is not in {evidence.document!r}; "
                        "quote the document exactly (at least 8 characters), or label the claim "
                        "inferred, missing or ambiguous",
                        repairable=True,
                        path=claim.path,
                    )
                )
            elif found is None:
                problems.append(
                    Problem(
                        code="QUOTE_UNVERIFIABLE",
                        severity="info",
                        message=f"{evidence.document!r} is a PDF and cannot be searched",
                        path=claim.path,
                    )
                )
    if is_numeric(claim.field) and evidence.kind == "document":
        hedges = hedges_in(evidence.quote)
        if hedges:
            problems.append(
                Problem(
                    code="AMBIGUOUS_WORDING",
                    severity="blocker",
                    message=f"the quote is approximate ({', '.join(map(repr, hedges))}), so it "
                    "does not give a number: label the claim ambiguous, with value null and a "
                    "note saying what to ask",
                    repairable=True,
                    path=claim.path,
                )
            )
        if not quote_has_number(evidence.quote, float(claim.value)):
            problems.append(
                Problem(
                    code="NUMBER_NOT_IN_QUOTE",
                    severity="blocker",
                    message=f"the value {claim.value!r} is not written in the quote "
                    f"{evidence.quote!r}: quote the sentence that gives the number, or label the "
                    "claim inferred (a number in words, or one you worked out, is inferred)",
                    repairable=True,
                    path=claim.path,
                )
            )
    return problems


def power_adjustment(spec: ExperimentSpec) -> Literal["none", "bonferroni"]:
    """The alpha adjustment Referee's design rules plan with: only an explicit none turns it off."""
    return "none" if spec.design.alpha_adjustment == "none" else "bonferroni"


def _size_problems(draft_values: dict[str, Any], plan: PowerPlan) -> list[Problem]:
    problems = []
    computed = {
        "stated.required_total_players": (plan.required_total, "players"),
        "stated.required_days": (plan.required_days, "days"),
    }
    for path, (ours, unit) in computed.items():
        said = draft_values.get(path)
        if said is not None and abs(said - ours) > SIZE_TOLERANCE * ours:
            problems.append(
                Problem(
                    code="SIZE_DIFFERS",
                    severity="warning",
                    message=f"the draft states {said:g} {unit}; Referee's power plan for these "
                    f"inputs needs {ours:,} {unit}. Referee's figure is the one reported",
                    path=path,
                )
            )
    return problems


def check_draft(
    draft: Draft, documents: tuple[Document, ...], *, owner: str | None = None
) -> CheckResult:
    by_name = {document.name: document for document in documents}
    problems: list[Problem] = []
    for claim in draft.claims:
        problems += _claim_problems(claim, by_name)

    claims = draft.by_path()
    values = {path: c.value for path, c in claims.items() if c.stated}
    if owner and "owner" not in values:
        values["owner"] = owner  # given on the command line
    needed = set(required_paths({path: c.value for path, c in claims.items()} | values))
    questions = [
        Question(path=c.path, kind=c.evidence.kind, note=c.evidence.note)  # type: ignore[arg-type]
        for c in draft.claims
        if not c.stated and c.path in needed and c.path not in values
    ]
    optional = tuple(
        Question(path=c.path, kind=c.evidence.kind, note=c.evidence.note)  # type: ignore[arg-type]
        for c in draft.claims
        if not c.stated and c.path not in needed
    )
    asked = {q.path for q in questions}
    for path in sorted(needed - set(values) - asked):
        questions.append(
            Question(path=path, kind="omitted", note="the draft makes no claim about this field")
        )
        problems.append(
            Problem(
                code="FIELD_OMITTED",
                severity="blocker",
                message="a required field has no claim: state it, or label it missing (value "
                "null, with a note saying what to ask)",
                repairable=True,
                path=path,
            )
        )
    inferred = tuple(c for c in draft.claims if c.evidence.kind == "inferred")

    spec_dict = spec = review = plan = None
    plan_error = None
    if not questions:
        spec_dict = assemble(values)
        try:
            spec = ExperimentSpec.from_dict(spec_dict)
        except SpecError as error:
            for violation in error.violations:
                problems.append(
                    Problem(code="SPEC", severity="blocker", message=violation, repairable=True)
                )
        if spec is not None:
            review = review_design(spec)
            for finding in review.findings:
                severity = finding.severity
                problems.append(
                    Problem(
                        code=f"RULE:{finding.rule_id}",
                        severity=severity,
                        message=f"{finding.title}. {finding.remediation}",
                        repairable=severity == "blocker"
                        and finding.rule_id not in UNREPAIRABLE_RULES,
                    )
                )
            try:
                plan = plan_power(spec, alpha_adjustment=power_adjustment(spec))
                problems += _size_problems(values, plan)
            except ValueError as error:
                plan_error = str(error)
    return CheckResult(
        problems=tuple(problems),
        questions=tuple(questions),
        optional_questions=optional,
        values=values,
        spec_dict=spec_dict,
        spec=spec,
        review=review,
        plan=plan,
        plan_error=plan_error,
        inferred=inferred,
    )


def repair_feedback(result: CheckResult) -> list[str]:
    """The lines that go back to the model: the blockers it can fix, one each."""
    return [problem.line() for problem in result.to_repair]
