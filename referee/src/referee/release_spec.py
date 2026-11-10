"""Typed, validated release specification for Referee (design handoff, section 4.2).

A release spec registers, before the data is looked at, what a release review reads: the
release, the whole weeks before it that form the baseline, the horizon after it, which KPIs of
the export's catalogue are read, the tolerance each guardrail may not exceed, what the release
was meant to do, and the segments the mix check reads. This module answers one question: is
the spec well-formed? Whether a KPI is in the catalogue, whether the release is in the calendar
and whether the data covers the windows are the reader's questions (REL-001 to REL-004), asked
of a valid spec and never of a repaired one.

No threshold is defaulted. A KPI without a line under `guardrails` is monitored but can never
be a breach, and the constants of the method are not spec fields.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

from referee.schema import (
    COLUMN_PATTERN,
    ID_PATTERN,
    Node,
    SpecError,
    canonical_json,
    drop_unset,
    fingerprint,
    show,
)

RELEASE_SPEC_VERSION = 1
KIND = "release spec"
MIN_PRE_PERIOD_DAYS = 28  # four whole weeks, the shortest baseline a weekday profile is built from
MIN_POST_PERIOD_DAYS = 7

ExpectedDirection = Literal["increase", "decrease"]


@dataclass(frozen=True, kw_only=True)
class Release:
    release_id: str  # a row of the export's release_calendar.csv


@dataclass(frozen=True, kw_only=True)
class KpiSelection:
    """Which KPIs of the catalogue the review reads: every KPI the catalogue marks `default`
    when `defaults` is true, plus `include`, minus `exclude`."""

    defaults: bool
    include: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ReleaseGuardrail:
    kpi: str
    tolerance_relative: float  # the registered tolerance, a share of the baseline level


@dataclass(frozen=True, kw_only=True)
class Expectation:
    """What the release was meant to do to one KPI; read by REL-014 and REL-015."""

    kpi: str
    direction: ExpectedDirection
    size_relative: float | None


@dataclass(frozen=True, kw_only=True)
class ReleaseSpec:
    """A validated release spec. Build it with `from_dict`, never by hand.

    Direct construction skips validation: the dataclasses are plain, immutable data.
    """

    referee_release_spec_version: int
    id: str
    title: str
    owner: str
    release: Release
    pre_period_days: int
    post_period_days: int
    kpis: KpiSelection
    guardrails: tuple[ReleaseGuardrail, ...]
    expectation: Expectation | None
    segments: tuple[str, ...] | None  # None: the mix check reads none

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReleaseSpec:
        """Validate `data` and return the spec, or raise SpecError listing every violation."""
        if not isinstance(data, Mapping):
            raise SpecError([f"spec: must be a mapping, got {show(data)}"], KIND)

        violations: list[str] = []
        root = Node(data, "", violations)

        version = root.integer("referee_release_spec_version", ge=1)
        supported = RELEASE_SPEC_VERSION
        if not root.failed("referee_release_spec_version") and version != supported:
            root.fail(
                "referee_release_spec_version",
                f"unsupported version {version}; this Referee reads version {supported}",
            )

        # The fields are read in schema order, so violations come out in that order; the KPI
        # selection comes before the guardrails and the expectation, which are checked against it.
        id_ = root.text("id", pattern=ID_PATTERN)
        title = root.text("title")
        owner = root.text("owner")
        release = _release(root.mapping("release"))
        pre_period_days = _pre_period_days(root)
        post_period_days = root.integer("post_period_days", ge=MIN_POST_PERIOD_DAYS)
        kpis_node = root.mapping("kpis", required=False)
        selection = _selection(kpis_node)
        spec = cls(
            referee_release_spec_version=version,
            id=id_,
            title=title,
            owner=owner,
            release=release,
            pre_period_days=pre_period_days,
            post_period_days=post_period_days,
            kpis=selection,
            guardrails=_guardrails(root, kpis_node, selection),
            expectation=_expectation(root, kpis_node, selection),
            segments=_segments(root),
        )
        root.reject_unknown()

        if violations:
            raise SpecError(violations, KIND)
        return spec

    def to_dict(self) -> dict[str, Any]:
        """The spec as plain data that `from_dict` accepts, in schema order.

        What was not given is left out, as for an experiment spec: an absent optional section or
        list, a null one and an empty `include` or `exclude` read the same, so none is written. A
        spec with no `kpis` section and one that spells out `defaults: true` have one canonical
        form, and with it one fingerprint.
        """
        data = drop_unset(asdict(self))
        for key in ("include", "exclude"):
            if not data["kpis"][key]:
                del data["kpis"][key]
        return data

    def canonical_json(self) -> str:
        """One fixed text for this spec (`referee.schema.canonical_json`)."""
        return canonical_json(self.to_dict())

    def sha256(self) -> str:
        """This spec's fingerprint (`referee.schema.fingerprint`)."""
        return fingerprint(self.to_dict())


# --- Section parsers: each one reads like the schema it validates -------------------------


def _release(node: Node) -> Release:
    release = Release(release_id=node.text("release_id"))
    node.reject_unknown()
    return release


def _pre_period_days(root: Node) -> int:
    days = root.integer("pre_period_days", ge=MIN_PRE_PERIOD_DAYS)
    if not root.failed("pre_period_days") and days % 7:
        root.fail(
            "pre_period_days", f"must be a whole number of weeks (a multiple of 7), got {days}"
        )
    return days


def _selection(node: Node) -> KpiSelection:
    selection = KpiSelection(
        defaults=node.boolean("defaults", default=True),
        include=node.texts("include", pattern=ID_PATTERN),
        exclude=node.texts("exclude", pattern=ID_PATTERN),
    )
    if not node.failed("include", "exclude"):
        for kpi in selection.include:
            if kpi in selection.exclude:
                node.fail("include", f"{kpi!r} is also in exclude")
    if not node.failed("defaults", "include") and not (selection.defaults or selection.include):
        node.fail("include", "must name at least one KPI when defaults is false")
    node.reject_unknown()
    return selection


def _selected_kpi(node: Node, kpis: Node, selection: KpiSelection) -> str:
    """The `kpi` of a guardrail or of the expectation: one the review will read, as far as the
    spec alone can tell. Whether it is in the catalogue is the reader's question (REL-003)."""
    kpi = node.text("kpi", pattern=ID_PATTERN)
    if node.failed("kpi") or kpis.failed("defaults", "include", "exclude"):
        return kpi
    if kpi in selection.exclude:
        node.fail("kpi", f"{kpi!r} is in kpis.exclude, so the review does not read it")
    elif not selection.defaults and kpi not in selection.include:
        node.fail("kpi", f"{kpi!r} is not in kpis.include, and kpis.defaults is false")
    return kpi


def _guardrails(root: Node, kpis: Node, selection: KpiSelection) -> tuple[ReleaseGuardrail, ...]:
    nodes = root.sequence("guardrails", required=False)
    guardrails = tuple(_guardrail(node, kpis, selection) for node in nodes)
    named = [g.kpi for node, g in zip(nodes, guardrails, strict=True) if not node.failed("kpi")]
    for kpi, count in Counter(named).items():
        if count > 1:
            root.fail("guardrails", f"duplicate kpi {kpi!r} (used {count} times)")
    return guardrails


def _guardrail(node: Node, kpis: Node, selection: KpiSelection) -> ReleaseGuardrail:
    guardrail = ReleaseGuardrail(
        kpi=_selected_kpi(node, kpis, selection),
        tolerance_relative=node.number("tolerance_relative", gt=0, lt=1),
    )
    node.reject_unknown()
    return guardrail


def _expectation(root: Node, kpis: Node, selection: KpiSelection) -> Expectation | None:
    if not root.given("expectation"):
        return None
    node = root.mapping("expectation")
    expectation = Expectation(
        kpi=_selected_kpi(node, kpis, selection),
        direction=node.choice("direction", get_args(ExpectedDirection)),
        size_relative=_size_relative(node),
    )
    node.reject_unknown()
    return expectation


def _size_relative(node: Node) -> float | None:
    size = node.optional_number("size_relative")
    if size is not None and not 0 < size < 1:
        node.fail("size_relative", f"must be > 0 and < 1, got {size:g}")
        return None
    return size


def _segments(root: Node) -> tuple[str, ...] | None:
    if not root.given("segments"):
        return None
    segments = root.texts("segments", pattern=COLUMN_PATTERN)
    if not root.failed("segments") and not segments:
        root.fail("segments", "must name at least one segment column, or be left out")
    return segments


def selected_kpis(spec: ReleaseSpec, catalogue_defaults: Sequence[str]) -> tuple[str, ...]:
    """The KPIs a review reads, once the catalogue is known: the catalogue's defaults when the
    spec takes them, then `include`, without `exclude`, each once, in that order."""
    chosen = list(catalogue_defaults) if spec.kpis.defaults else []
    chosen += [kpi for kpi in spec.kpis.include if kpi not in chosen]
    return tuple(kpi for kpi in chosen if kpi not in spec.kpis.exclude)
