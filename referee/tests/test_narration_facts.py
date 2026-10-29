"""The report check and the fact list of the narration layer (design sections 24.4 and 24.11)."""

import copy
import itertools
import json
import os
import threading
from collections import Counter
from pathlib import Path

import pytest
from narration_reports import NAMES, report

from referee.findings import is_more_serious
from referee.narration.facts import (
    ALLOWLIST,
    ARM,
    DROPPED_KEYS,
    EFFECT_KEYS,
    EFFECT_UNTRUSTED,
    HARM_RULES,
    SEVERITIES,
    ReportError,
    catalogue_sentences,
    check_report_consistency,
    fact_list,
    read_report,
    split_sentences,
)
from referee.report import render_json
from referee.rules import RESULTS_RULES


@pytest.fixture
def golden(raw_spec: dict) -> dict:
    return report("golden", raw_spec)


def problems_of(candidate: object) -> list[str]:
    try:
        check_report_consistency(candidate)
    except ReportError as error:
        return error.problems
    return []


def evidence_of(candidate: dict, rule_id: str) -> dict:
    return next(f for f in candidate["findings"] if f["rule_id"] == rule_id)["evidence"]


# --- The fixtures -----------------------------------------------------------------------------

FIXTURES = {
    "golden": ("invalid", ["RES-001", "RES-002", "RES-007", "RES-008", "RES-012", "RES-013"], 21),
    "clear": ("clear", [], 28),
    "warnings_only": ("caution", ["RES-012", "RES-013"], 28),
    "harm_blocker": ("invalid", ["RES-004"], 28),
    "unattainable_design": ("invalid", ["RES-002", "RES-007"], 14),
    "short_arms": ("invalid", ["RES-002", "RES-007"], 14),
    "short_run": ("invalid", ["RES-002", "RES-003", "RES-007"], 5),
    "weekly_drift": ("invalid", ["RES-002", "RES-011"], 28),
}


def test_the_eight_fixtures_are_the_eight_names_and_each_has_the_findings_it_exists_for(
    raw_spec: dict,
) -> None:
    assert list(FIXTURES) == list(NAMES)
    for name, (verdict, rule_ids, days) in FIXTURES.items():
        built = report(name, raw_spec)
        assert (built["verdict"], [f["rule_id"] for f in built["findings"]]) == (verdict, rule_ids)
        assert built["population"]["observed_days"] == days, name
        assert len(built["population"]["ignored_before_start"]) == (name == "short_run") * 4, name


def test_harm_blocks_alone_in_one_fixture_and_a_design_that_cannot_be_sized_is_not_underpowered(
    raw_spec: dict,
) -> None:
    assert report("harm_blocker", raw_spec)["blocking_groups"] == {
        "data_validity": [],
        "harm": ["RES-004"],
    }
    for name, unattainable in (("unattainable_design", True), ("short_arms", False)):
        built = report(name, raw_spec)
        assert evidence_of(built, "RES-002").get("unattainable", False) is unattainable
        assert built["effect"]["underpowered"] is not unattainable


def test_short_run_names_its_four_early_players_and_weekly_drift_fails_two_weeks_of_four(
    raw_spec: dict,
) -> None:
    run = report("short_run", raw_spec)
    drift = evidence_of(report("weekly_drift", raw_spec), "RES-011")

    assert len(evidence_of(run, "RES-003")["ignored_before_start"]) == 4
    assert (drift["failing_weeks"], drift["weeks_tested"]) == ([1, 2], 4)
    assert drift["total"]["p_value"] > 0.5


def test_clear_carries_the_lines_of_the_rules_that_compared_nothing(raw_spec: dict) -> None:
    lines = report("clear", raw_spec)["summary_lines"]

    assert [line.split(":")[0] for line in lines] == ["RES-004", "RES-007", "RES-008"]
    assert lines[0].startswith("RES-004: 0 comparisons of an arm against control on a guardrail")
    assert lines[1].startswith("RES-007: 2 tests, 0 flagged, 0 not evaluated")
    assert lines[2].startswith("RES-008: 0 comparisons (binary metrics are not read)")


def test_a_fixture_is_built_once_for_a_spec_and_handed_out_as_a_copy(raw_spec: dict) -> None:
    first = report("short_arms", raw_spec)
    first["verdict"] = "clear"
    renamed = {**raw_spec, "title": "Another title"}

    assert report("short_arms", raw_spec)["verdict"] == "invalid"
    assert report("short_arms", raw_spec)["spec"]["title"] == raw_spec["title"]
    assert report("short_arms", renamed)["spec"]["title"] == "Another title"


# --- Reading ----------------------------------------------------------------------------------


def refused(path: Path) -> ReportError:
    """What `read_report` raises for `path`, which it must do within seconds: a read of a FIFO
    whose writer is silent never ends, so the call runs in a thread that may be left behind."""
    outcome: dict[str, BaseException] = {}

    def attempt() -> None:
        try:
            read_report(path)
        except BaseException as error:  # reported below
            outcome["error"] = error

    thread = threading.Thread(target=attempt, daemon=True)
    thread.start()
    thread.join(10)
    assert not thread.is_alive(), "read_report did not return"
    assert isinstance(outcome.get("error"), ReportError), outcome
    return outcome["error"]


@pytest.mark.parametrize("name", NAMES)
def test_every_fixture_is_json_as_the_engine_wrote_it_and_passes_the_check(
    name: str, raw_spec: dict, tmp_path: Path
) -> None:
    built = report(name, raw_spec)
    path = tmp_path / "report.json"
    path.write_text(render_json(built), encoding="utf-8")

    assert json.loads(json.dumps(built)) == built
    assert read_report(path) == built
    check_report_consistency(built)
    check_report_consistency(json.loads(json.dumps(built, sort_keys=True)))  # as `jq -S` writes it


@pytest.mark.parametrize("kind", ["a FIFO", "a FIFO with a silent writer", "/dev/zero", "a folder"])
def test_what_is_not_a_regular_file_is_refused_without_being_read(
    kind: str, tmp_path: Path
) -> None:
    release = threading.Event()
    path = Path("/dev/zero") if kind == "/dev/zero" else tmp_path
    if "FIFO" in kind:
        path = tmp_path / "report.fifo"
        os.mkfifo(path)
    if "writer" in kind:

        def hold() -> None:
            with open(path, "wb"):  # waits until the reader has opened the FIFO
                release.wait(30)

        threading.Thread(target=hold, daemon=True).start()
    try:
        assert refused(path).problems == ["the report is not a regular file"]
    finally:
        release.set()


@pytest.mark.parametrize(
    ("extra", "problems"), [(0, None), (1, ["the report is longer than 5,242,880 bytes"])]
)
def test_a_report_of_5_mib_is_read_and_one_byte_more_is_too_long(
    golden: dict, tmp_path: Path, extra: int, problems: list[str] | None
) -> None:
    text = render_json(golden).encode()
    path = tmp_path / "report.json"
    path.write_bytes(text + b" " * (5_242_880 - len(text) + extra))

    if problems is None:
        assert read_report(path) == golden
    else:
        assert refused(path).problems == problems


def test_reading_leaves_no_descriptor_open_whether_it_succeeds_or_refuses(
    golden: dict, tmp_path: Path
) -> None:
    path = tmp_path / "report.json"
    path.write_text(render_json(golden), encoding="utf-8")

    def next_descriptor() -> int:
        probe = os.dup(0)
        os.close(probe)
        return probe

    before = next_descriptor()

    for _ in range(5):
        read_report(path)
        with pytest.raises(ReportError):
            read_report(tmp_path)

    assert next_descriptor() == before


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b'{"a": 1, "a": 2}', "an object of the report repeats a key"),
        (b'{"findings": [{"x": [{"k": 1, "k": 2}]}]}', "an object of the report repeats a key"),
        (b"[" * 20_000 + b"]" * 20_000, "the report could not be read: RecursionError"),
        (b"1" * 5_000, "the report could not be read: ValueError"),
        (b'{"secret": ', "the report could not be read: JSONDecodeError"),
        (b"\xff", "the report could not be read: UnicodeDecodeError"),
    ],
    ids=["repeated key", "repeated key deep", "20,000 brackets", "5,000 digits", "cut", "bytes"],
)
def test_a_report_that_cannot_be_parsed_is_one_problem_that_names_no_text_of_it(
    tmp_path: Path, content: bytes, problem: str
) -> None:
    path = tmp_path / "report.json"
    path.write_bytes(content)

    assert refused(path).problems == [problem]


def test_a_file_that_is_not_there_is_one_problem_that_names_the_exception_only(
    tmp_path: Path,
) -> None:
    assert refused(tmp_path / "secret-name.json").problems == [
        "the report could not be read: FileNotFoundError"
    ]


# --- Checking ---------------------------------------------------------------------------------


def put(candidate: dict, *path: str | int, value: object) -> None:
    node = candidate
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


NOT_FINITE = "not a finite number"
GIVEN = "not what the findings give"
IN_ARMS = "not the arms of population.assigned"
CATALOGUE = "the catalogue text differs: the report was made by another build"
RULES_RUN = "rules_run: not the nine results rules, sorted by ID"
ORDER = "findings: not in report order (severity, then rule ID)"
EFFECT_ARMS = "effect.arms: the arms and the control are not the arms of population.assigned"
CORRUPTIONS = [
    pytest.param(
        "golden",
        lambda r: put(r, "kind", value="design_review"),
        "kind: not what this build of Referee writes",
        id="kind",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "report_version", value=2),
        "report_version: not what this build of Referee writes",
        id="version",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "report_version", value=True),
        "report_version: not what this build of Referee writes",
        id="version true",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "referee_version", value="9.9"),
        "referee_version: not what this build of Referee writes",
        id="build",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "evidence", "p_value", value=float("nan")),
        f"findings[0].evidence.p_value: {NOT_FINITE}",
        id="nan",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "arms", 0, "p_value", value=float("inf")),
        f"effect.arms[0].p_value: {NOT_FINITE}",
        id="infinity",
    ),
    pytest.param(
        "golden", lambda r: put(r, "counts", "blocker", value=3), f"counts: {GIVEN}", id="counts"
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "counts", "blocker", value=2.0),
        f"counts: {GIVEN}",
        id="counts as a float",
    ),
    pytest.param(
        "golden", lambda r: put(r, "verdict", value="caution"), f"verdict: {GIVEN}", id="verdict"
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "blocking_rule_ids", value=["RES-001"]),
        f"blocking_rule_ids: {GIVEN}",
        id="blocking rules",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "blocking_groups", value={"data_validity": [], "harm": ["RES-001"]}),
        f"blocking_groups: {GIVEN}",
        id="blocking groups",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "readable", value=True),
        f"effect.readable: {GIVEN}",
        id="readable",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "unreadable_because", value=[]),
        f"effect.unreadable_because: {GIVEN}",
        id="unreadable because",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "underpowered", value=False),
        f"effect.underpowered: {GIVEN}",
        id="underpowered",
    ),
    pytest.param("golden", lambda r: r["rules_run"].pop(), RULES_RUN, id="a rule less"),
    pytest.param("golden", lambda r: r["rules_run"].reverse(), RULES_RUN, id="unsorted"),
    pytest.param(
        "golden",
        lambda r: r["rules_run"].append("RES-005"),
        RULES_RUN,
        id="a rule more",
    ),
    pytest.param(
        "golden",
        lambda r: r["rules_run"].remove("RES-013"),
        "findings: RES-013 is not among rules_run",
        id="a finding of a rule that did not run",
    ),
    pytest.param(
        "golden",
        lambda r: r["findings"].append({**r["findings"][-1], "rule_id": "ZZZ-001"}),
        "findings: ZZZ-001 is not among rules_run",
        id="a finding of an unknown rule",
    ),
    pytest.param(
        "golden",
        lambda r: r["findings"].insert(1, r["findings"][0]),
        "findings: RES-001 appears 2 times",
        id="a finding twice",
    ),
    pytest.param(
        "golden",
        lambda r: r["findings"].insert(0, r["findings"].pop(1)),
        ORDER,
        id="rule IDs out of order",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "severity", value="warning"),
        ORDER,
        id="severities out of order",
    ),
    *(
        pytest.param(
            "golden",
            lambda r, n=n: r["summary_lines"].pop(n),
            f"summary_lines: 0 entries for {rule_id}, not one",
            id=f"no summary line of {rule_id}",
        )
        for n, rule_id in enumerate(["RES-004", "RES-007", "RES-008"])
    ),
    pytest.param(
        "golden",
        lambda r: r["summary_lines"].append(r["summary_lines"][1]),
        "summary_lines: 2 entries for RES-007, not one",
        id="two summary lines",
    ),
    pytest.param(
        "golden",
        lambda r: r["population"]["analysed"].pop("variant_c"),
        f"population.analysed: {IN_ARMS} (variant_c)",
        id="an arm missing from analysed",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "left_out", "variant_z", value=0),
        f"effect.left_out: {IN_ARMS} (variant_z)",
        id="an arm too many in left_out",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "population", "assigned", value=[997, 1046, 781]),
        "population.assigned: not a table of arms",
        id="no table of assigned",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "population", "analysed", value=[926, 969, 731]),
        "population.analysed: not a table of arms",
        id="no table of analysed",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "left_out", value=None),
        "effect.left_out: not a table of arms",
        id="no table of left out",
    ),
    pytest.param(
        "golden",
        lambda r: r["effect"]["arms"].pop(),
        EFFECT_ARMS,
        id="an arm missing from the effect",
    ),
    pytest.param(
        "golden",
        lambda r: r["effect"]["arms"].append(copy.deepcopy(r["effect"]["arms"][0])),
        EFFECT_ARMS,
        id="an arm's row twice",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "arms", 0, "arm", value="variant_z"),
        EFFECT_ARMS,
        id="an unknown arm in the effect",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "effect", "arms", value="variant_b variant_c"),
        EFFECT_ARMS,
        id="no list of arms in the effect",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "evidence", "assigned", "variant_z", value=1),
        "RES-001.assigned: variant_z is not an arm of population",
        id="an unknown arm in the evidence",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "evidence", "method", value="bogus"),
        "RES-001.method: not one of the words the engine writes",
        id="a method outside its set",
    ),
    pytest.param(
        "golden",
        lambda r: put(evidence_of(r, "RES-012"), "homogeneity", "method", value=7),
        "RES-012.homogeneity.method: not one of the words the engine writes",
        id="a method that is not a word",
    ),
    pytest.param(
        "weekly_drift",
        lambda r: put(evidence_of(r, "RES-011"), "total", "method", value="bogus"),
        "RES-011.total.method: not one of the words the engine writes",
        id="a method of RES-011",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "title", value="Another title"),
        f"RES-001: {CATALOGUE}",
        id="title",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "why_it_matters", value="It does not."),
        f"RES-001: {CATALOGUE}",
        id="why it matters",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "remediation", value="Do nothing."),
        f"RES-001: {CATALOGUE}",
        id="remediation",
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", 0, "references", value=[]),
        f"RES-001: {CATALOGUE}",
        id="references",
    ),
    pytest.param(
        "golden",
        lambda r: put(evidence_of(r, "RES-008"), "summary", "largest_simulated_rate", value=0.01),
        f"RES-008: {CATALOGUE}",
        id="a severity the evidence does not give",
    ),
    pytest.param(
        "golden", lambda r: r.clear(), "findings: not a list of findings", id="no findings"
    ),
    pytest.param(
        "golden",
        lambda r: put(r, "findings", value=[1]),
        "findings: not a list of findings",
        id="a finding that is not one",
    ),
]


@pytest.mark.parametrize(("name", "corrupt", "problem"), CORRUPTIONS)
def test_each_check_lists_its_problem_for_a_report_corrupted_in_that_one_way(
    raw_spec: dict, name: str, corrupt, problem: str
) -> None:
    candidate = report(name, raw_spec)
    corrupt(candidate)

    problems = problems_of(candidate)

    assert problem in problems
    assert not any("could not be checked" in line for line in problems), problems


def test_a_report_that_is_not_an_object_is_one_problem() -> None:
    assert problems_of([]) == ["the report is not a JSON object"]


def test_an_exception_of_the_check_is_one_problem_that_names_its_type_and_no_text(
    golden: dict,
) -> None:
    put(evidence_of(golden, "RES-008"), "summary", value=[])

    assert problems_of(golden) == ["the report could not be checked: AttributeError"]


@pytest.mark.parametrize(
    ("name", "names"),
    [
        ("bad\x1b[2J\nname", "bad\\x1b[2J\\nname, variant_c"),
        ("x" * 500, "variant_c, " + "x" * 80 + "..."),
        ("x" * 80, "variant_c, " + "x" * 80),
    ],
    ids=["written by for_line", "cut", "just short enough"],
)
def test_a_problem_line_writes_an_arms_name_cut_and_without_a_control_character(
    golden: dict, name: str, names: str
) -> None:
    golden["population"]["analysed"][name] = golden["population"]["analysed"].pop("variant_c")

    assert problems_of(golden) == [f"population.analysed: {IN_ARMS} ({names})"]


def test_a_summary_line_is_wanted_only_for_a_rule_that_ran(raw_spec: dict) -> None:
    clear = report("clear", raw_spec)
    clear["rules_run"].remove("RES-008")
    clear["summary_lines"].pop()

    assert problems_of(clear) == ["rules_run: not the nine results rules, sorted by ID"]


def test_the_key_path_of_a_non_finite_number_is_written_by_for_line(golden: dict) -> None:
    evidence_of(golden, "RES-001")["bad\x1bkey"] = [float("nan")]

    assert problems_of(golden) == ["findings[0].evidence.bad\\x1bkey[0]: not a finite number"]


@pytest.mark.parametrize(
    ("analysed", "names"),
    [
        ({}, "control, variant_b, variant_c"),
        ({"control": 0, "variant_b": 0, "variant_c": 0, "extra": 0}, "extra"),
        ({"extra": 0}, "control, extra, variant_b and 1 more"),
        ({f"extra_{n}": 0 for n in range(5)}, "control, extra_0, extra_1 and 5 more"),
    ],
    ids=["three arms", "one arm", "four arms", "eight arms"],
)
def test_a_problem_line_names_three_arms_and_counts_the_rest(
    golden: dict, analysed: dict, names: str
) -> None:
    golden["population"]["analysed"] = analysed

    assert problems_of(golden) == [f"population.analysed: {IN_ARMS} ({names})"]


def test_at_most_1000_problems_are_listed_and_all_of_them_counted(golden: dict) -> None:
    evidence_of(golden, "RES-001")["junk"] = [float("nan")] * 1_500

    with pytest.raises(ReportError) as raised:
        check_report_consistency(golden)

    assert len(raised.value.problems) == 1_000
    assert raised.value.total == 1_500
    assert raised.value.problems[0] == "findings[0].evidence.junk[0]: not a finite number"


@pytest.mark.parametrize(("levels", "refused"), [(28, False), (29, True)])  # 32 deep, 33
def test_nesting_deeper_than_the_bound_is_refused_once_wherever_it_is(
    golden: dict, levels: int, refused: bool
) -> None:
    nested: object = 1
    for _ in range(levels):
        nested = [nested]
    evidence_of(golden, "RES-001")["notes"] = nested  # the value is 4 keys below the report
    evidence_of(golden, "RES-002")["notes"] = nested

    problems = problems_of(golden)

    assert problems == (["the report is nested more than 32 levels deep"] if refused else [])
    if not refused:
        fact_list(golden)


def test_the_rule_sets_of_the_check_are_copies_of_those_of_the_report_code() -> None:
    from referee.report import _EFFECT_UNTRUSTED, _HARM_RULES  # the one place a private is read

    assert (HARM_RULES, EFFECT_UNTRUSTED) == (_HARM_RULES, _EFFECT_UNTRUSTED)
    assert all(is_more_serious(a, b) for a, b in itertools.pairwise(SEVERITIES))


# --- Sentences --------------------------------------------------------------------------------


def test_the_nine_results_rules_have_81_sentences_that_join_back_into_their_texts() -> None:
    found = catalogue_sentences()

    assert len(RESULTS_RULES) == 9
    assert Counter(key.split(".")[1] for key in found) == {"title": 9, "why": 32, "do": 40}
    for rule in RESULTS_RULES:
        assert found[f"{rule.id}.title"] == rule.title
        for kind, text in (("why", rule.why_it_matters), ("do", rule.remediation)):
            keys = [key for key in found if key.startswith(f"{rule.id}.{kind}.")]
            assert keys == [f"{rule.id}.{kind}.{n}" for n in range(1, len(keys) + 1)]
            assert " ".join(found[key] for key in keys) == text


@pytest.mark.parametrize(
    ("text", "sentences"),
    [
        ("One. Two", ["One.", "Two"]),
        ("One! Two? Three.", ["One!", "Two?", "Three."]),
        ("One.\n  Two", ["One.", "Two"]),
        ("One. two", ["One. two"]),
        ("One.Two", ["One.Two"]),
        ("Pi is 3.14 or so", ["Pi is 3.14 or so"]),
    ],
)
def test_a_sentence_ends_at_a_stop_whitespace_and_a_capital_or_at_the_end(
    text: str, sentences: list[str]
) -> None:
    assert split_sentences(text) == sentences


# --- The allowlist ----------------------------------------------------------------------------

LABELS = {
    "RES-001.alpha": ("significance level of the sample ratio test", "probability"),
    "RES-001.allocation.*": ("registered allocation", "share"),
    "RES-001.assigned.*": ("players assigned", "players"),
    "RES-001.expected.*": ("players expected at the registered allocation", "players"),
    "RES-001.chi_square": ("chi-squared statistic of the counts", ""),
    "RES-001.degrees_of_freedom": ("degrees of freedom of the counts", ""),
    "RES-001.p_value": ("p value of the sample ratio test", "probability"),
    "RES-001.method": ("test used", ""),
    "RES-002.unattainable": ("design cannot be sized", ""),
    "RES-002.required.*": ("players required by the power plan", "players"),
    "RES-002.analysed.*": ("players analysed", "players"),
    "RES-002.assigned.*": ("players assigned", "players"),
    "RES-002.missing.*": ("players missing from the number required", "players"),
    "RES-003.observed_days": (
        "whole days, rounded up, from the first to the last assignment",
        "days",
    ),
    "RES-003.min_duration_days": ("registered minimum duration", "days"),
    "RES-003.planned_duration_days": ("registered planned duration", "days"),
    "RES-004.summary.tests": ("guardrail comparisons of an arm against control", "comparisons"),
    "RES-004.summary.breach_shown": ("comparisons with a breach shown", "comparisons"),
    "RES-004.summary.breach_possible": ("comparisons with a breach possible", "comparisons"),
    "RES-004.summary.within_tolerance": ("comparisons within the tolerance", "comparisons"),
    "RES-004.summary.not_evaluated": ("comparisons not evaluated", "comparisons"),
    "RES-004.summary.not_verified": (
        "comparisons within the tolerance whose interval reaches beyond it",
        "comparisons",
    ),
    "RES-004.summary.tolerance_out_of_reach": (
        "comparisons whose tolerance no data could breach",
        "comparisons",
    ),
    "RES-007.summary.tests": ("cohort tests", "tests"),
    "RES-007.summary.evaluated": ("tests evaluated", "tests"),
    "RES-007.summary.flagged": ("tests flagged", "tests"),
    "RES-007.summary.not_evaluated": ("tests not evaluated", "tests"),
    "RES-007.summary.low_information": ("tests labelled low information", "tests"),
    "RES-007.summary.flags_by_chance": ("flags expected by chance alone", "tests"),
    "RES-007.summary.flags_by_chance_at_most": (
        "flags expected by chance alone, at most",
        "tests",
    ),
    "RES-008.summary.tests": ("comparisons on a metric that is not binary", "comparisons"),
    "RES-008.summary.tripped": ("comparisons with a sign of a heavy tail", "comparisons"),
    "RES-008.summary.not_tripped": ("comparisons with no sign of a heavy tail", "comparisons"),
    "RES-008.summary.not_evaluated": ("comparisons not evaluated", "comparisons"),
    "RES-008.summary.largest_simulated_rate": (
        "largest simulated failure rate of the interval, ranges read for the severity",
        "share",
    ),
    "RES-008.summary.largest_printed_rate": (
        "largest simulated failure rate of the interval, any range printed",
        "share",
    ),
    "RES-008.summary.floor_ranges": (
        "ranges whose true failure rate is probably above the range",
        "ranges",
    ),
    "RES-011.alpha_per_week": ("significance level for one week", "probability"),
    "RES-011.weeks_tested": ("weeks of assignment tested", "weeks"),
    "RES-011.total.assigned.*": ("players assigned, all weeks", "players"),
    "RES-011.total.p_value": ("p value of the sample ratio test, all weeks", "probability"),
    "RES-011.total.method": ("test used, all weeks", ""),
    "RES-011.allocation.*": ("registered allocation", "share"),
    "RES-012.late.*": ("players first exposed after their first purchase", "players"),
    "RES-012.exposed.*": ("players exposed", "players"),
    "RES-012.late_share_of_exposed.*": ("share of exposed players exposed late", "share"),
    "RES-012.late_total": ("players exposed late, all arms", "players"),
    "RES-012.share_of_assigned": ("share of assigned players exposed late", "share"),
    "RES-012.share_of_purchasers": ("players exposed late as a share of purchasers", "share"),
    "RES-012.homogeneity.chi_square": ("chi-squared statistic of the late shares", ""),
    "RES-012.homogeneity.degrees_of_freedom": ("degrees of freedom of the late shares", ""),
    "RES-012.homogeneity.p_value": ("p value of the late shares across arms", "probability"),
    "RES-012.homogeneity.alpha": ("significance level for the late shares", "probability"),
    "RES-012.homogeneity.method": ("test used", ""),
    "RES-012.homogeneity.smallest_expected": ("smallest expected count", "players"),
    "RES-013.version_from.exposure": (
        "analysed players with the version of their first exposure",
        "players",
    ),
    "RES-013.version_from.assignment": (
        "analysed players with the version of their assignment",
        "players",
    ),
    "RES-013.arms.*.assigned_differs": (
        "players first exposed on another version than the one assigned",
        "players",
    ),
}
ENUMERATIONS = {
    "RES-001.method": ("chi_square", "exact"),
    "RES-011.total.method": ("chi_square", "exact"),
    "RES-012.homogeneity.method": ("chi_square", "exact"),
}


def listed() -> dict:
    return {
        f"{rule_id}.{path}": admitted
        for rule_id, table in ALLOWLIST.items()
        for path, admitted in table.items()
    }


def test_the_allowlist_gives_every_key_path_the_label_and_unit_written_for_it() -> None:
    assert {path: (a.label, a.unit) for path, a in listed().items()} == LABELS
    assert {path: a.words for path, a in listed().items() if a.words} == ENUMERATIONS
    assert [path for path, a in listed().items() if a.boolean] == ["RES-002.unattainable"]


def test_the_allowlist_is_data_of_short_paths_that_admit_nothing_withheld_or_dropped() -> None:
    assert set(ALLOWLIST) <= {rule.id for rule in RESULTS_RULES}
    assert EFFECT_KEYS == {
        "estimate",
        "difference",
        "ci_low",
        "ci_high",
        "relative_difference",
        "effect_seen",
    }
    assert DROPPED_KEYS == {"tests", "plans", "settings", "notes"}
    for table in ALLOWLIST.values():
        paths = [tuple(path.split(".")) for path in table]
        for path in paths:
            assert 1 <= len(path) <= 4
            assert path.count(ARM) <= 1
            assert not set(path) & EFFECT_KEYS
            assert path[0] not in DROPPED_KEYS
            assert not any(path[: len(other)] == other for other in paths if other != path)


# --- The fact list ----------------------------------------------------------------------------


def paths_of(facts) -> set[str]:
    """The allowlist paths that the facts of a fact list stand for."""
    return {
        ".".join(
            [
                finding.rule_id,
                *(ARM if part == fact.alias else part for part in fact.id.split(".")[1:]),
            ]
        )
        for finding in facts.findings
        for fact in finding.facts
    }


def test_every_evidence_key_of_every_fixture_is_listed_or_dropped_and_every_listed_one_occurs(
    raw_spec: dict,
) -> None:
    seen: set[str] = set()
    for name in NAMES:
        facts = fact_list(report(name, raw_spec))
        assert [(f.rule_id, f.unlisted) for f in facts.findings if f.unlisted] == [], name
        seen |= paths_of(facts)

    assert seen == set(listed())


def test_the_facts_of_the_golden_are_the_allowed_values_under_aliases_and_the_rest_is_counted(
    golden: dict,
) -> None:
    facts = fact_list(golden)

    assert facts.aliases == {"control": "A1", "variant_b": "A2", "variant_c": "A3"}
    assert [f.rule_id for f in facts.findings] == [f["rule_id"] for f in golden["findings"]]
    first = facts.findings[0]
    assert [(f.id, f.value) for f in first.facts] == [
        ("RES-001.alpha", 0.001),
        ("RES-001.allocation.A1", 1 / 3),
        ("RES-001.allocation.A2", 1 / 3),
        ("RES-001.allocation.A3", 1 / 3),
        ("RES-001.assigned.A1", 997),
        ("RES-001.assigned.A2", 1046),
        ("RES-001.assigned.A3", 781),
        ("RES-001.expected.A1", 941.33),
        ("RES-001.expected.A2", 941.33),
        ("RES-001.expected.A3", 941.33),
        ("RES-001.chi_square", 42.2387),
        ("RES-001.degrees_of_freedom", 2),
        ("RES-001.p_value", 6.729606364817086e-10),
        ("RES-001.method", "chi_square"),
    ]
    assert first.facts[5].label == "players assigned (A2)"
    assert (first.facts[5].alias, first.facts[0].alias) == ("A2", None)
    # three weeks of (week, three arms, p value, method) are dropped; three arm names too in RES-002
    assert [(f.dropped, f.withheld) for f in facts.findings[:2]] == [(18, 0), (3, 0)]
    # two arms, each with and without the late players, of six values, and the metric's name
    assert [(f.dropped, f.withheld) for f in facts.findings if f.rule_id == "RES-012"] == [(0, 25)]


def test_the_order_of_the_facts_is_the_allowlists_and_the_aliases_whatever_the_report_does(
    golden: dict,
) -> None:
    def reversed_keys(node):
        if isinstance(node, dict):
            return {key: reversed_keys(node[key]) for key in reversed(list(node))}
        return [reversed_keys(item) for item in node] if isinstance(node, list) else node

    scrambled = copy.deepcopy(golden)
    scrambled["findings"] = [
        {**f, "evidence": reversed_keys(f["evidence"])} for f in scrambled["findings"]
    ]

    assert fact_list(scrambled).findings == fact_list(golden).findings


def test_the_control_is_the_first_alias_and_the_others_follow_population_assigned(
    golden: dict,
) -> None:
    golden["population"]["assigned"] = dict(
        reversed(list(golden["population"]["assigned"].items()))
    )

    facts = fact_list(golden)

    assert facts.aliases == {"control": "A1", "variant_c": "A2", "variant_b": "A3"}
    assigned = [(f.id, f.value) for f in facts.findings[0].facts if ".assigned." in f.id]
    assert assigned == [
        ("RES-001.assigned.A1", 997),  # control
        ("RES-001.assigned.A2", 781),  # variant_c
        ("RES-001.assigned.A3", 1046),  # variant_b
    ]


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda r: r["population"]["analysed"].pop("control"),
        lambda r: put(r, "population", "analysed", value=[926, 969, 731]),
    ],
    ids=["an arm missing", "no table"],
)
def test_a_fact_list_is_refused_for_a_report_whose_arm_tables_disagree(
    golden: dict, corrupt
) -> None:
    corrupt(golden)

    with pytest.raises(ReportError) as raised:
        fact_list(golden)

    assert raised.value.problems == ["the arm tables disagree: the report did not pass the check"]


def test_an_unknown_key_inside_a_listed_group_is_unlisted_with_its_path(golden: dict) -> None:
    golden["findings"] = [{**golden["findings"][0], "rule_id": "RES-012"}]
    golden["findings"][0]["evidence"] = {
        "homogeneity": {"p_value": 0.1, "novel": 3, "novel_rate": 0.5}
    }

    (found,) = fact_list(golden).findings

    assert [f.id for f in found.facts] == ["RES-012.homogeneity.p_value"]
    assert found.unlisted == ("homogeneity.novel", "homogeneity.novel_rate")


def test_only_a_number_at_a_numeric_path_and_a_listed_word_at_its_path_is_a_fact(
    golden: dict,
) -> None:
    golden["findings"] = golden["findings"][:1]
    golden["findings"][0]["evidence"] = {
        "alpha": "0.001",  # a string where a number belongs
        "allocation": [1, 2],  # a list where the arms are
        "assigned": {"control": "997", "variant_b": 1046.5, "variant_c": None},
        "expected": {"control": True, "variant_b": {"x": 1}},  # True is no number
        "p_value": {"x": 1, "y": [2, 3]},
        "method": "bogus",
    }

    (found,) = fact_list(golden).findings

    assert [(f.id, f.value) for f in found.facts] == [("RES-001.assigned.A2", 1046.5)]
    # alpha 1, allocation 2, two of assigned, two of expected, p_value 3, method 1
    assert (found.dropped, found.withheld, found.unlisted) == (11, 0, ())


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        (True, True),
        (False, True),
        (1, False),
        (0, False),
        (1.0, False),
        ("yes", False),
        (None, False),
    ],
)
def test_the_one_boolean_path_admits_a_boolean_and_nothing_else(
    golden: dict, value: object, kept: bool
) -> None:
    golden["findings"] = [f for f in golden["findings"] if f["rule_id"] == "RES-002"]
    golden["findings"][0]["evidence"] = {"unattainable": value}

    (found,) = fact_list(golden).findings

    assert [(f.id, f.value) for f in found.facts] == (
        [("RES-002.unattainable", value)] if kept else []
    )
    assert found.dropped == (0 if kept else 1)


def test_a_value_is_counted_as_dropped_for_each_value_in_a_subtree_or_list_and_unknown_keys_named(
    golden: dict,
) -> None:
    golden["findings"] = golden["findings"][:1]
    golden["findings"][0]["evidence"] = {
        "tests": {"a": 1, "b": [2, 3]},
        "notes": {"k": "x"},
        "settings": {},
        "plans": {"v": {"k": None}},
        "by_week": [1, {"p": "q"}],  # a list: dropped by its type, not unlisted
        "title": "text",  # a string: dropped by its type
        "novel": 5,
        "tree": {"leaf": 1},
        "alpha": 0.001,
    }

    (found,) = fact_list(golden).findings

    assert [f.id for f in found.facts] == ["RES-001.alpha"]
    assert found.dropped == 3 + 1 + 0 + 1 + 2 + 1 + 1 + 1
    assert found.unlisted == ("novel", "tree")


@pytest.mark.parametrize(
    "key", ["estimate", "difference", "ci_low", "ci_high", "relative_difference", "effect_seen"]
)
def test_an_effect_estimate_is_withheld_and_counted_at_any_depth_never_dropped_or_a_fact(
    golden: dict, key: str
) -> None:
    golden["findings"] = [{**golden["findings"][0], "rule_id": "RES-004"}]
    golden["findings"][0]["evidence"] = {
        "summary": {"tests": 2, key: 0.5},
        key: {"a": 1, "b": [2, 3]},
    }

    (found,) = fact_list(golden).findings

    assert [(f.id, f.value) for f in found.facts] == [("RES-004.summary.tests", 2)]
    assert (found.dropped, found.withheld, found.unlisted) == (0, 3 + 1, ())


def test_the_arms_are_aliased_and_listed_in_numeric_order_beyond_nine(golden: dict) -> None:
    arms = [f"arm_{n:02d}" for n in range(11)]
    golden["population"]["assigned"] = dict.fromkeys(arms, 1)
    golden["population"]["analysed"] = dict.fromkeys(arms, 1)
    golden["effect"]["left_out"] = dict.fromkeys(arms, 0)
    golden["effect"]["arms"] = [{"arm": arm} for arm in arms[1:]]
    evidence_of(golden, "RES-001")["assigned"] = {arm: n for n, arm in enumerate(reversed(arms))}

    facts = fact_list(golden)

    assigned = [(f.id, f.value) for f in facts.findings[0].facts if ".assigned." in f.id]
    assert assigned == [(f"RES-001.assigned.A{n}", 11 - n) for n in range(1, 12)]
    assert facts.aliases["arm_10"] == "A11"


def rename_arms(node, names: dict[str, str]):
    """`node` with each arm named as `names` says, in keys and in values alike."""
    if isinstance(node, dict):
        return {names.get(key, key): rename_arms(item, names) for key, item in node.items()}
    if isinstance(node, list):
        return [rename_arms(item, names) for item in node]
    return names.get(node, node) if isinstance(node, str) else node


@pytest.mark.parametrize(
    "arms",
    [
        ("alpha", "p_value", "estimate"),
        ("tests", "settings", "notes"),
        ("difference", "summary", "method"),
        ("a", "A", "1"),
        ("control", "variant_c", "variant_b"),
        ("A3", "A1", "A2"),
    ],
)
def test_an_arm_named_like_a_key_of_the_evidence_or_like_an_alias_keeps_every_fact(
    golden: dict, arms: tuple[str, ...]
) -> None:
    renamed = rename_arms(
        golden, dict(zip(("control", "variant_b", "variant_c"), arms, strict=True))
    )

    check_report_consistency(renamed)
    facts = fact_list(renamed)

    assert facts.aliases == {arms[0]: "A1", arms[1]: "A2", arms[2]: "A3"}
    assert facts.findings == fact_list(golden).findings


def with_canaries(source: dict) -> tuple[dict, list[str]]:
    """`source` with each free text of it replaced by a canary that is unique to it, and the
    canaries: arm names (keys and values), the ids of the spec and the experiment, metric and
    guardrail names, error texts, notes and summary lines. The structure is kept, so that the
    check still passes and the allowlist still matches."""
    count = itertools.count(1)
    canaries: list[str] = []

    def canary(kind: str) -> str:
        canaries.append(f"CANARY-{kind}-{next(count)}")
        return canaries[-1]

    names = {arm: canary("ARM") for arm in source["population"]["assigned"]}
    names[source["spec"]["id"]] = canary("SPEC")
    names[source["spec"]["title"]] = canary("TITLE")
    names[source["experiment_id"]] = canary("EXPERIMENT")
    names[source["effect"]["metric"]] = canary("METRIC")
    for metric in evidence_of(source, "RES-008")["settings"]["metrics_read"]:
        if metric not in names:  # the guardrail
            names[metric] = canary("GUARDRAIL")

    def walk(node, key=None):
        if isinstance(node, dict):
            return {names.get(k, k): walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, key) for item in node]
        if key in ("error", "reason", "notes", "line"):
            return canary(key.upper())
        if key == "summary_lines":
            return f"{node.split(':')[0]}: {canary('LINE')}"
        return names.get(node, node) if isinstance(node, str) else node

    return walk(source), canaries


def test_no_free_text_of_the_report_reaches_the_fact_list(golden: dict) -> None:
    canaried, canaries = with_canaries(golden)
    check_report_consistency(canaried)

    facts, plain = fact_list(canaried), fact_list(golden)

    # not vacuous: the canaries are in the report, and the facts are the golden's, aliases too
    text = json.dumps(canaried)
    assert len(canaries) > 30 and all(canary in text for canary in canaries)
    assert sum(len(f.facts) for f in facts.findings) == 61
    assert sorted(facts.aliases.values()) == ["A1", "A2", "A3"]
    assert facts.findings == plain.findings
    # and no canary is in them
    assert not any(canary in repr(facts.findings) for canary in canaries)
