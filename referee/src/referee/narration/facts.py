"""The report check and the fact list (design section 24.4).

`read_report` opens a saved results report and parses it within bounds. `check_report_consistency`
refuses a report that Referee's own code could not have written. `fact_list` turns the evidence of
a report that passed the check into the few numbers, booleans and enumeration words that an
allowlist names, each beside a label written here, with the arms aliased. `catalogue_sentences`
gives the engine's sentences of the nine results rules, each with an ID.

Nothing here calls a model, reads anything but the report, or prints. Everything that is not on the
allowlist (titles, IDs, arm and metric names, hashes, error texts, notes, lists of rows) is dropped
and counted, and the keys that carry an effect estimate are withheld and counted.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from referee import __version__
from referee.display import for_line
from referee.report import REPORT_VERSION
from referee.rules import RESULTS_RULES

MAX_REPORT_BYTES = 5 * 1024 * 1024
MAX_PROBLEMS = 1_000
SHOWN_CHARS = 80  # of a report's name or key in a problem line
MAX_DEPTH = 32  # of nesting; the engine's own reports go 10 deep

SEVERITIES = ("blocker", "warning", "info")  # most serious first, as findings.py ranks them
SUMMARISED_RULES = ("RES-004", "RES-007", "RES-008")
# Copies of the two rule sets of report.py (a test compares them with the originals).
HARM_RULES = frozenset({"RES-004"})
EFFECT_UNTRUSTED = frozenset({"RES-001", "RES-003", "RES-012"})

_RULES = {rule.id: rule for rule in RESULTS_RULES}


class ReportError(ValueError):
    """The report cannot be used. `problems` holds the first 1,000, `total` how many there are
    (the check keeps no more than 1,000; a read has one problem).

    No problem line quotes the report except by key path, name and count, and a name is cut and
    written through `for_line`; an exception of the parser or the check is named by its type.
    """

    def __init__(self, problems: list[str], total: int | None = None) -> None:
        self.problems = problems
        self.total = len(problems) if total is None else total
        super().__init__("\n".join(self.problems))


class _Problems:
    """The problems found so far: the first 1,000 kept, all of them counted."""

    def __init__(self) -> None:
        self.shown: list[str] = []
        self.total = 0

    def add(self, text: str) -> None:
        self.total += 1
        if len(self.shown) < MAX_PROBLEMS:
            self.shown.append(text)


def _shown(text: object) -> str:
    """A name or key of the report as one short line: cut, then written by `for_line`."""
    text = str(text)
    return for_line(text if len(text) <= SHOWN_CHARS else text[:SHOWN_CHARS] + "...")


def _names(names: list[str]) -> str:
    more = f" and {len(names) - 3} more" if len(names) > 3 else ""
    return ", ".join(_shown(name) for name in names[:3]) + more


# --- Reading ----------------------------------------------------------------------------------


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ReportError(["an object of the report repeats a key"])
    return dict(pairs)


def _read(path: str | os.PathLike[str]) -> bytes:
    # O_NONBLOCK so that a FIFO opens at once, without a writer; it is refused before any read.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReportError(["the report is not a regular file"])
        with open(descriptor, "rb", closefd=False) as handle:
            data = handle.read(MAX_REPORT_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_REPORT_BYTES:
        raise ReportError([f"the report is longer than {MAX_REPORT_BYTES:,} bytes"])
    return data


def read_report(path: str | os.PathLike[str]) -> Any:
    """The JSON in the regular file at `path`, of at most 5 MiB, with no repeated key.

    Raises `ReportError` for a file that is not regular, is too long or repeats a key, and for any
    other exception (a missing file, text that is not UTF-8 or JSON, nesting beyond the parser's
    limit, an integer of 5,000 digits) with the exception's type and no text of the input.
    """
    try:
        return json.loads(_read(path).decode("utf-8"), object_pairs_hook=_object)
    except Exception as error:
        if isinstance(error, ReportError):
            raise
        raise ReportError([f"the report could not be read: {type(error).__name__}"]) from None


# --- Checking ---------------------------------------------------------------------------------


def _same(found: object, wanted: object) -> bool:
    """Equal as JSON is: 2 is not 2.0 and True is not 1."""
    return json.dumps(found, sort_keys=True) == json.dumps(wanted, sort_keys=True)


def _at(node: object, *path: str) -> object:
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _check_values(report: object, out: _Problems) -> None:
    """Refuse a number that is not finite and, once, nesting deeper than MAX_DEPTH, so that the
    recursive readers below are bounded whatever the caller's stack."""
    stack: list[tuple[object, tuple[str | int, ...]]] = [(report, ())]
    deep = False
    while stack:
        node, path = stack.pop()
        if len(path) > MAX_DEPTH:
            if not deep:
                out.add(f"the report is nested more than {MAX_DEPTH} levels deep")
            deep = True
        elif isinstance(node, float) and not math.isfinite(node):
            where = "".join(f"[{p}]" if isinstance(p, int) else f".{_shown(p)}" for p in path)
            out.add(f"{where[1:]}: not a finite number")
        elif isinstance(node, dict):
            stack.extend((item, (*path, key)) for key, item in reversed(node.items()))
        elif isinstance(node, list):
            stack.extend((item, (*path, index)) for index, item in reversed(list(enumerate(node))))


def _check_arms(report: dict[str, Any], out: _Problems) -> list[str] | None:
    """The arm names, the control first, if the arm tables agree; otherwise None and why."""
    assigned = _at(report, "population", "assigned")
    if not isinstance(assigned, dict):
        out.add("population.assigned: not a table of arms")
        return None
    ok = True
    for name in ("population.analysed", "effect.left_out"):
        table = _at(report, *name.split("."))
        if not isinstance(table, dict):
            out.add(f"{name}: not a table of arms")
            ok = False
        elif set(table) != set(assigned):
            different = [arm for arm in {*table, *assigned} if (arm in table) != (arm in assigned)]
            out.add(f"{name}: not the arms of population.assigned ({_names(sorted(different))})")
            ok = False
    rows = _at(report, "effect", "arms")
    others = (
        [row.get("arm") if isinstance(row, dict) else None for row in rows]
        if isinstance(rows, list)
        else []
    )
    named = {arm for arm in others if isinstance(arm, str)}
    control = [arm for arm in assigned if arm not in named]
    if not isinstance(rows, list) or len(control) != 1 or len(others) != len(assigned) - 1:
        out.add("effect.arms: the arms and the control are not the arms of population.assigned")
        return None
    return [control[0], *(arm for arm in assigned if arm != control[0])] if ok else None


def _is_finding(item: object) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("rule_id"), str)
        and item.get("severity") in SEVERITIES
        and isinstance(item.get("evidence"), dict)
    )


def _check(report: object, out: _Problems) -> None:
    if not isinstance(report, dict):
        out.add("the report is not a JSON object")
        return
    for key, wanted in (
        ("kind", "results_review"),
        ("report_version", REPORT_VERSION),
        ("referee_version", __version__),
    ):
        if not _same(report.get(key), wanted):
            out.add(f"{key}: not what this build of Referee writes")
    _check_values(report, out)
    order = _check_arms(report, out)
    findings = report.get("findings")
    if not isinstance(findings, list) or not all(_is_finding(item) for item in findings):
        out.add("findings: not a list of findings")
        return

    ran = report.get("rules_run")
    if not _same(ran, sorted(_RULES)):
        out.add("rules_run: not the nine results rules, sorted by ID")
    ran = [name for name in ran if isinstance(name, str)] if isinstance(ran, list) else []
    ids = [item["rule_id"] for item in findings]
    for rule_id in sorted(set(ids) - set(ran)):
        out.add(f"findings: {_shown(rule_id)} is not among rules_run")
    for rule_id, times in sorted(Counter(ids).items()):
        if times > 1:
            out.add(f"findings: {_shown(rule_id)} appears {times} times")
    keys = [(SEVERITIES.index(item["severity"]), item["rule_id"]) for item in findings]
    if keys != sorted(keys):
        out.add("findings: not in report order (severity, then rule ID)")

    lines = report.get("summary_lines")
    lines = lines if isinstance(lines, list) else []
    for rule_id in SUMMARISED_RULES:
        own = sum(isinstance(line, str) and line.startswith(f"{rule_id}:") for line in lines)
        if rule_id in ran and own != 1:
            out.add(f"summary_lines: {own} entries for {rule_id}, not one")

    blocking = [item["rule_id"] for item in findings if item["severity"] == "blocker"]
    counts = {severity: sum(i["severity"] == severity for i in findings) for severity in SEVERITIES}
    unreadable = [rule_id for rule_id in blocking if rule_id in EFFECT_UNTRUSTED]
    underpowered = any(
        item["rule_id"] == "RES-002"
        and item["severity"] == "blocker"
        and not item["evidence"].get("unattainable")
        for item in findings
    )
    for name, wanted in (
        ("counts", counts),
        (
            "verdict",
            "invalid" if counts["blocker"] else "caution" if counts["warning"] else "clear",
        ),
        ("blocking_rule_ids", blocking),
        (
            "blocking_groups",
            {
                "data_validity": [rule_id for rule_id in blocking if rule_id not in HARM_RULES],
                "harm": [rule_id for rule_id in blocking if rule_id in HARM_RULES],
            },
        ),
        ("effect.readable", not unreadable),
        ("effect.unreadable_because", unreadable),
        ("effect.underpowered", underpowered),
    ):
        if not _same(_at(report, *name.split(".")), wanted):
            out.add(f"{name}: not what the findings give")

    aliases = None if order is None else _aliases(order)
    for item in findings:
        rule = _RULES.get(item["rule_id"])
        if rule is None:
            continue
        made = rule.finding(item["evidence"])
        if (
            item["severity"] != made.severity
            or item.get("title") != made.title
            or item.get("why_it_matters") != made.why_it_matters
            or item.get("remediation") != made.remediation
            or item.get("references") != list(made.references)
        ):
            out.add(f"{rule.id}: the catalogue text differs: the report was made by another build")
        if aliases is not None:
            for problem in _Walk(rule.id, aliases).walk(item["evidence"]).problems:
                out.add(problem)


def check_report_consistency(report: object) -> None:
    """Raise `ReportError` listing every way `report` is not one that Referee wrote (24.4).

    The checks: the kind, `REPORT_VERSION` and `referee_version`; no non-finite number; the counts,
    the verdict, the blocking rules and groups and the effect's `readable`, `unreadable_because`
    and `underpowered` that the findings give; `rules_run` the nine results rules, sorted; findings
    only from `rules_run`, none repeated, in report order; one summary line for each of RES-004,
    RES-007 and RES-008 that ran; arm tables that agree, in the evidence too; a value outside the
    closed set of an enumeration path; and each finding as `Rule.finding(evidence)` makes it.
    Any other exception while checking is one problem naming its type.
    """
    problems = _Problems()
    try:
        _check(report, problems)
    except Exception as error:
        problems.add(f"the report could not be checked: {type(error).__name__}")
    if problems.total:
        raise ReportError(problems.shown, problems.total)


# --- The allowlist ----------------------------------------------------------------------------

ARM = "*"  # in a key path: the key here is an arm's name


@dataclass(frozen=True)
class Admitted:
    """A key path of the evidence that may become a fact: what code calls it, in what unit, and,
    for an enumeration, the closed set of words it may hold."""

    label: str
    unit: str = ""
    words: tuple[str, ...] | None = None


_TEST = ("chi_square", "exact")

# The facts of each results rule, by key path under its evidence (at most four keys; `*` is an
# arm's name), in the order a page lists them. Nothing else is a fact.
ALLOWLIST: dict[str, dict[str, Admitted]] = {
    "RES-001": {
        "alpha": Admitted("significance level of the sample ratio test", "probability"),
        "allocation.*": Admitted("registered allocation", "share"),
        "assigned.*": Admitted("players assigned", "players"),
        "expected.*": Admitted("players expected at the registered allocation", "players"),
        "chi_square": Admitted("chi-squared statistic of the counts"),
        "degrees_of_freedom": Admitted("degrees of freedom of the counts"),
        "p_value": Admitted("p value of the sample ratio test", "probability"),
        "method": Admitted("test used", words=_TEST),
    },
    "RES-002": {
        "unattainable": Admitted("design cannot be sized"),
        "required.*": Admitted("players required by the power plan", "players"),
        "analysed.*": Admitted("players analysed", "players"),
        "assigned.*": Admitted("players assigned", "players"),
        "missing.*": Admitted("players missing from the number required", "players"),
    },
    "RES-003": {
        "observed_days": Admitted(
            "whole days, rounded up, from the first to the last assignment", "days"
        ),
        "min_duration_days": Admitted("registered minimum duration", "days"),
        "planned_duration_days": Admitted("registered planned duration", "days"),
    },
    "RES-004": {
        "summary.tests": Admitted("guardrail comparisons of an arm against control", "comparisons"),
        "summary.breach_shown": Admitted("comparisons with a breach shown", "comparisons"),
        "summary.breach_possible": Admitted("comparisons with a breach possible", "comparisons"),
        "summary.within_tolerance": Admitted("comparisons within the tolerance", "comparisons"),
        "summary.not_evaluated": Admitted("comparisons not evaluated", "comparisons"),
        "summary.not_verified": Admitted(
            "comparisons within the tolerance whose interval reaches beyond it", "comparisons"
        ),
        "summary.tolerance_out_of_reach": Admitted(
            "comparisons whose tolerance no data could breach", "comparisons"
        ),
    },
    "RES-007": {
        "summary.tests": Admitted("cohort tests", "tests"),
        "summary.evaluated": Admitted("tests evaluated", "tests"),
        "summary.flagged": Admitted("tests flagged", "tests"),
        "summary.not_evaluated": Admitted("tests not evaluated", "tests"),
        "summary.low_information": Admitted("tests labelled low information", "tests"),
        "summary.flags_by_chance": Admitted("flags expected by chance alone", "tests"),
        "summary.flags_by_chance_at_most": Admitted(
            "flags expected by chance alone, at most", "tests"
        ),
    },
    "RES-008": {
        "summary.tests": Admitted("comparisons on a metric that is not binary", "comparisons"),
        "summary.tripped": Admitted("comparisons with a sign of a heavy tail", "comparisons"),
        "summary.not_tripped": Admitted("comparisons with no sign of a heavy tail", "comparisons"),
        "summary.not_evaluated": Admitted("comparisons not evaluated", "comparisons"),
        "summary.largest_simulated_rate": Admitted(
            "largest simulated failure rate of the interval, ranges read for the severity", "share"
        ),
        "summary.largest_printed_rate": Admitted(
            "largest simulated failure rate of the interval, any range printed", "share"
        ),
        "summary.floor_ranges": Admitted(
            "ranges whose true failure rate is probably above the range", "ranges"
        ),
    },
    "RES-011": {
        "alpha_per_week": Admitted("significance level for one week", "probability"),
        "weeks_tested": Admitted("weeks of assignment tested", "weeks"),
        "total.assigned.*": Admitted("players assigned, all weeks", "players"),
        "total.p_value": Admitted("p value of the sample ratio test, all weeks", "probability"),
        "total.method": Admitted("test used, all weeks", words=_TEST),
        "allocation.*": Admitted("registered allocation", "share"),
    },
    "RES-012": {
        "late.*": Admitted("players first exposed after their first purchase", "players"),
        "exposed.*": Admitted("players exposed", "players"),
        "late_share_of_exposed.*": Admitted("share of exposed players exposed late", "share"),
        "late_total": Admitted("players exposed late, all arms", "players"),
        "share_of_assigned": Admitted("share of assigned players exposed late", "share"),
        "share_of_purchasers": Admitted("players exposed late as a share of purchasers", "share"),
        "homogeneity.chi_square": Admitted("chi-squared statistic of the late shares"),
        "homogeneity.degrees_of_freedom": Admitted("degrees of freedom of the late shares"),
        "homogeneity.p_value": Admitted("p value of the late shares across arms", "probability"),
        "homogeneity.alpha": Admitted("significance level for the late shares", "probability"),
        "homogeneity.method": Admitted("test used", words=_TEST),
        "homogeneity.smallest_expected": Admitted("smallest expected count", "players"),
        "purchasers.*": Admitted("exposed players who bought, by arm", "players"),
        "late_share_of_purchasers.*": Admitted(
            "share of the exposed players who bought that were exposed late", "share"
        ),
        "purchaser_homogeneity.chi_square": Admitted(
            "chi-squared statistic of the late shares of the purchasers"
        ),
        "purchaser_homogeneity.degrees_of_freedom": Admitted(
            "degrees of freedom of the late shares of the purchasers"
        ),
        "purchaser_homogeneity.p_value": Admitted(
            "p value of the late shares of the purchasers across arms", "probability"
        ),
        "purchaser_homogeneity.alpha": Admitted(
            "significance level for the late shares of the purchasers", "probability"
        ),
        "purchaser_homogeneity.method": Admitted("test used", words=_TEST),
        "purchaser_homogeneity.smallest_expected": Admitted("smallest expected count", "players"),
        "exposure_delay.median_seconds.*": Admitted(
            "median seconds from assignment to first exposure", "seconds"
        ),
        "exposure_delay.kruskal_wallis_p_value": Admitted(
            "p value of the difference in delay to first exposure across arms", "probability"
        ),
    },
    "RES-013": {
        "version_from.exposure": Admitted(
            "analysed players with the version of their first exposure", "players"
        ),
        "version_from.assignment": Admitted(
            "analysed players with the version of their assignment", "players"
        ),
        "arms.*.assigned_differs": Admitted(
            "players first exposed on another version than the one assigned", "players"
        ),
    },
}

# Subtrees of the evidence dropped whole and counted (24.4). `summary.tests` is a fact, so these
# are dropped at the root of the evidence only; elsewhere an unknown key is unlisted.
DROPPED_KEYS = frozenset({"tests", "plans", "settings", "notes"})
# Keys that carry an effect estimate: withheld and counted at any depth, and never admitted.
EFFECT_KEYS = frozenset(
    {"estimate", "difference", "ci_low", "ci_high", "relative_difference", "effect_seen"}
)


@dataclass(frozen=True)
class _Index:
    """An allowlist table read as the walk needs it."""

    entries: dict[tuple[str, ...], Admitted]
    order: dict[tuple[str, ...], int]
    interior: frozenset[tuple[str, ...]]  # the paths above an entry
    arm_parents: frozenset[tuple[str, ...]]  # the paths whose keys are arm names


def _index(table: dict[str, Admitted]) -> _Index:
    entries = {tuple(path.split(".")): admitted for path, admitted in table.items()}
    return _Index(
        entries=entries,
        order={path: number for number, path in enumerate(entries)},
        interior=frozenset(path[:n] for path in entries for n in range(1, len(path))),
        arm_parents=frozenset(
            path[:n] for path in entries for n in range(len(path)) if path[n] == ARM
        ),
    )


_INDEX = {rule_id: _index(table) for rule_id, table in ALLOWLIST.items()}


# --- The fact list ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """A value of a finding's evidence with the ID, label and unit that code wrote for it.

    `id` is the rule ID and the key path with the arm's alias for `*` (`RES-001.assigned.A2`);
    `alias` is that alias or None; `value` is a number, a boolean or an enumeration word.
    """

    id: str
    label: str
    unit: str
    value: int | float | str
    alias: str | None


@dataclass(frozen=True)
class FindingFacts:
    """The facts of one finding in allowlist order, how many other values of its evidence were
    dropped and how many were withheld as effect estimates (both counted as values, not keys),
    and the key paths found that the allowlist neither names nor drops (report text: write it with
    `for_line`; a test over the fixtures requires none)."""

    rule_id: str
    facts: tuple[Fact, ...]
    dropped: int
    withheld: int
    unlisted: tuple[str, ...]


@dataclass(frozen=True)
class FactList:
    """The facts of every finding, in report order, and the aliases of the arms: `A1` for the
    control, then `A2`, `A3` in the order of `population.assigned`."""

    aliases: dict[str, str]
    findings: tuple[FindingFacts, ...]


def _aliases(order: list[str]) -> dict[str, str]:
    return {name: f"A{number}" for number, name in enumerate(order, 1)}


def _leaves(value: object) -> int:
    """How many values `value` holds (a dict's or a list's items, counted down to the scalars)."""
    if isinstance(value, dict):
        return sum(_leaves(item) for item in value.values())
    if isinstance(value, list):
        return sum(_leaves(item) for item in value)
    return 1


@dataclass
class _Walk:
    """One finding's evidence read against the allowlist: facts, counts and problems."""

    rule_id: str
    aliases: dict[str, str]
    found: list[tuple[tuple[int, int], Fact]] = field(default_factory=list)
    dropped: int = 0
    withheld: int = 0
    unlisted: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def walk(self, evidence: dict[str, Any]) -> _Walk:
        self._visit(evidence, (), ())
        return self

    def _visit(self, node: dict[str, Any], path: tuple[str, ...], arms: tuple[str, ...]) -> None:
        index = _INDEX[self.rule_id]
        for key, value in node.items():
            here_arms = arms
            if path in index.arm_parents:
                alias = self.aliases.get(key)
                if alias is None:
                    where = ".".join((self.rule_id, *path))
                    self.problems.append(f"{where}: {_shown(key)} is not an arm of population")
                    self.dropped += _leaves(value)
                    continue
                step, here_arms = ARM, (*arms, alias)
            elif key in EFFECT_KEYS:
                self.withheld += _leaves(value)
                continue
            elif key in DROPPED_KEYS and not path:
                self.dropped += _leaves(value)
                continue
            else:
                step = key
            here = (*path, step)
            entry = index.entries.get(here)
            if entry is not None and self._admit(entry, here, here_arms, value):
                continue
            if here in index.interior and isinstance(value, dict):
                self._visit(value, here, here_arms)
                continue
            self.dropped += _leaves(value)
            known = entry is not None or here in index.interior
            if not known and isinstance(value, dict | int | float):
                self.unlisted.append(".".join(here))

    def _admit(self, entry: Admitted, here: tuple[str, ...], arms: tuple[str, ...], value) -> bool:
        if entry.words is not None:
            if not isinstance(value, str) or value not in entry.words:
                self.problems.append(
                    f"{'.'.join((self.rule_id, *here))}: not one of the words the engine writes"
                )
                return False
        elif not isinstance(value, int | float):
            return False
        aliases = iter(arms)
        parts = [next(aliases) if part == ARM else part for part in here]
        label = f"{entry.label} ({arms[0]})" if arms else entry.label
        rank = int(arms[0][1:]) if arms else 0
        fact = Fact(
            ".".join((self.rule_id, *parts)), label, entry.unit, value, arms[0] if arms else None
        )
        self.found.append(((_INDEX[self.rule_id].order[here], rank), fact))
        return True

    def facts(self) -> FindingFacts:
        return FindingFacts(
            rule_id=self.rule_id,
            facts=tuple(fact for _, fact in sorted(self.found, key=lambda pair: pair[0])),
            dropped=self.dropped,
            withheld=self.withheld,
            unlisted=tuple(self.unlisted),
        )


def fact_list(report: dict[str, Any]) -> FactList:
    """The facts of the evidence of every finding of `report`, which must have passed the check.

    A fact is an integer, a float, a boolean or an enumeration word at a key path of the
    allowlist; an arm is aliased only where the allowlist marks it, so no arm's name, however it
    is spelt, changes which facts a finding has. Raw values are kept; rounding is the page's.
    """
    order = _check_arms(report, _Problems())
    if order is None:
        raise ReportError(["the arm tables disagree: the report did not pass the check"])
    aliases = _aliases(order)
    return FactList(
        aliases=aliases,
        findings=tuple(
            _Walk(item["rule_id"], aliases).walk(item["evidence"]).facts()
            for item in report["findings"]
        ),
    )


# --- The sentences ----------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def split_sentences(text: str) -> list[str]:
    """`text` cut after `.`, `!` or `?` that is followed by whitespace and a capital letter."""
    return _SENTENCE_END.split(text)


def catalogue_sentences() -> dict[str, str]:
    """The sentences of the nine results rules by ID, in page order: `RES-001.title`, then
    `RES-001.why.1`, ... from `why_it_matters` and `RES-001.do.1`, ... from `remediation`."""
    found = {}
    for rule in RESULTS_RULES:
        found[f"{rule.id}.title"] = rule.title
        for kind, text in (("why", rule.why_it_matters), ("do", rule.remediation)):
            for number, sentence in enumerate(split_sentences(text), 1):
                found[f"{rule.id}.{kind}.{number}"] = sentence
    return found
