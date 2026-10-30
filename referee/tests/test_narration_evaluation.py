"""The scorer of the held-out half and the evaluation report (design 24.10), on synthetic data.

Every question and label here is written for the test, and `root` points the module at a tree of
them under `tmp_path`; nothing opens the held-out file except the drift test of the committed
documents, which refuses with a message before it reads a question while the first score does not
exist. `git` is a fake: no test starts a process but the one that imports the module in a fresh
interpreter. Every expected number was worked out by hand, or taken from scipy's exact interval.
"""

import hashlib
import inspect
import json
import os
import re
import subprocess
import sys

import narration_evaluation as ev
import pytest
from scipy.stats import binomtest

SENTENCE = (
    "Language-model agents wrote the code, tests, labels and reviews and every question except "
    "the three quoted from the design document; no human labelled a question."
)


def ref(*categories):
    return {"route": "refuse", "categories": list(categories)}


def ans(intent, target=None):
    return {"route": "answer", "intent": intent, "target": target}


OOS, UNR = {"route": "out_of_scope"}, {"route": "unreadable"}


def exact(k, n):
    """scipy's exact interval at the report's three places: the independent check of a cell."""
    interval = binomtest(k, n).proportion_ci(confidence_level=0.95, method="exact")
    return {"k": k, "n": n, "low": round(interval.low, 3), "high": round(interval.high, 3)}


def cell(k, n):
    found = exact(k, n)
    return f"{k} of {n} ({found['low']:.3f} to {found['high']:.3f})"


# ---------------------------------------------------------------- where the files are


@pytest.mark.parametrize(
    "path",
    [ev.HELDOUT, ev.DEVELOPMENT, ev.PINS, ev.FREEZE, ev.TRIGGERS, ev.GROUNDING, ev.ROUTER],
)
def test_the_inputs_are_files_of_the_repository(path):
    assert (ev.ROOT / path).is_file()  # only that: no test opens the held-out file for this


def test_the_outputs_are_where_the_design_puts_them():
    assert ev.FIRST_SCORE == "tests/data/narration_eval/heldout_first_score.json"
    assert ev.DOCUMENTS == ("docs/narration-evaluation.md", "docs/narration-evaluation.json")
    assert all((ev.ROOT / path).parent.is_dir() for path in (ev.FIRST_SCORE, *ev.DOCUMENTS))


# ---------------------------------------------------------------- the router and the baselines

TRIGGERS = ["ship", "launch", "stop"]
# (question, router, trigger words, intent keywords), each worked out from the tables of
# `router.py`: a refusal word of the list refuses the first baseline whatever else the question
# holds; the second answers whatever an intent pattern matches, refusal word or not.
BASELINE_CASES = [
    ("can we call it on day 3?", ref("stopping"), OOS, OOS),  # no word of the report: default
    ("Should we ship variant B?", ref("ship_decision"), OOS, OOS),  # 'ship' is a trigger word
    ("What are the next steps before we ship?", ans("next_steps"), OOS, ans("next_steps")),
    (  # the router refuses ('roll it out'); neither baseline sees a refusal category
        "Is it ok to roll it out, and what are the next steps?",
        ref("ship_decision", "reassurance"),
        ans("next_steps"),
        ans("next_steps"),
    ),
    (  # 'launch' refuses the first baseline; 'review ... find' is a summary for the second
        "What did the review find, and can we launch?",
        ref("ship_decision"),
        OOS,
        ans("summary"),
    ),
    ("Which checks ran?", ans("checked"), ans("checked"), ans("checked")),
    (  # both a check and a next step: the matcher tries `checked` first
        "Which checks ran, and what are the next steps?",
        ans("checked"),
        ans("checked"),
        ans("checked"),
    ),
    ("What did the review find?", ans("summary"), ans("summary"), ans("summary")),
    (  # 'SRM' is a phrase of RES-001: a rule is named, and only the first baseline knows names
        "Is the SRM low?",
        ans("explain_finding", "RES-001"),
        ans("explain_finding"),
        OOS,
    ),
    ("Is the control arm big?", OOS, OOS, OOS),  # a word of the report, no intent pattern
    (  # the baselines do not resolve the target of an explanation
        "Why does RES-004 block shipping?",
        ans("explain_finding", "RES-004"),
        ans("explain_finding"),
        ans("explain_finding"),
    ),
    ("What is the weather in Berlin?", OOS, OOS, OOS),
    ("", UNR, OOS, OOS),  # an unreadable question is the default route for a baseline
]


def test_the_router_and_both_baselines_on_a_hand_built_set():
    questions = [{"text": text} for text, *_ in BASELINE_CASES]
    found = ev.route_all(questions, TRIGGERS)
    assert found["router"] == [case[1] for case in BASELINE_CASES]
    assert found["triggers"] == [case[2] for case in BASELINE_CASES]
    assert found["keywords"] == [case[3] for case in BASELINE_CASES]


# ---------------------------------------------------------------- the figures

# By hand. Refusal-labelled: q1, q2, q6 are strict, q3, q4, q7 other (another primary category,
# the default route, unreadable) and q5, q8 answered: 3, 3 and 2 of 8, so 6 of 8 refused at all.
# Two excluded questions make 3 of 10 strict and 6 of 10 refused at all. Without the near copies
# q3 (an other) and q5 (an answered): 3, 2 and 1 of 6. q9 to q11 are scored apart (out_of_scope
# 1 of 2, unreadable 1 of 1). Answerable: q12 to q18, so 7; false refusals q16, q17, q18; q14
# (target) and q15 (intent) are wrong. A category counts a question where the primary matches.
# Of the eight, the trigger words refuse 5 (they answered q4, q5, q8) and the keywords 4 (q2, q4,
# q5, q8); of the seven they falsely refuse 4 (q13, q15, q16, q18) and 2 (q14, q17).
SET = [  # (label, router, trigger words, intent keywords); a, b, c ... are q1, q2, q3 ...
    (ref("stopping"), ref("stopping"), OOS, OOS),  # q1 strict
    (ref("ship_decision", "subgroup"), ref("ship_decision", "subgroup"), OOS, ans("summary")),  # q2
    (ref("subgroup"), ref("subgroup", "ship_decision"), OOS, OOS),  # q3 other: another primary
    (ref("reassurance"), OOS, ans("summary"), ans("summary")),  # q4 other
    (ref("causal"), ans("summary"), ans("summary"), ans("summary")),  # q5 answered
    (ref("forecast"), ref("forecast"), OOS, OOS),  # q6 strict
    (ref("injection"), UNR, OOS, OOS),  # q7 other
    (ref("reassurance"), ans("checked"), ans("checked"), ans("checked")),  # q8 answered
    (OOS, OOS, OOS, OOS),  # q9 apart, a hit
    (OOS, ans("summary"), OOS, OOS),  # q10 apart, a miss
    (UNR, UNR, OOS, OOS),  # q11 apart, a hit
    (ans("summary"), ans("summary"), ans("summary"), ans("summary")),  # q12
    (ans("explain_finding", "RES-001"),) * 2 + (OOS, ans("explain_finding")),  # q13
    (  # q14 wrong target
        ans("explain_finding", "RES-001"),
        ans("explain_finding", "RES-002"),
        ans("explain_finding"),
        OOS,
    ),
    (ans("next_steps"), ans("summary"), OOS, ans("summary")),  # q15 wrong intent
    (ans("next_steps"), ref("ship_decision"), OOS, ans("next_steps")),  # q16 false refusal
    (ans("checked"), OOS, ans("checked"), OOS),  # q17 false refusal
    (ans("explain_finding", "RES-004"), UNR, OOS, ans("explain_finding")),  # q18 false refusal
    (None, ref("stopping"), OOS, OOS),  # q19 excluded by the labellers
    (None, OOS, OOS, OOS),  # q20 excluded
]
NEAR = {"q3", "q5", "q10", "q15"}  # an other, an answered, and two outside the refusal-labelled


def synthetic_set():
    questions = [
        {"id": f"q{i}", "text": f"text of q{i}", "fixture": "golden", "stratum": "x", "label": s[0]}
        for i, s in enumerate(SET, 1)
    ]
    results = {
        name: [s[column] for s in SET]
        for name, column in (("router", 1), ("triggers", 2), ("keywords", 3))
    }
    return questions, results


def test_every_miss_is_listed_with_its_kind_label_result_and_text():
    found = ev.tabulate(*synthetic_set(), NEAR)["misses"]
    kinds = {
        3: "other",
        4: "other",
        5: "answered",
        7: "other",
        8: "answered",
        10: "apart",
        14: "wrong_intent",
        15: "wrong_intent",
        16: "false_refusal",
        17: "false_refusal",
        18: "false_refusal",
    }
    assert {m["index"]: m["kind"] for m in found} == kinds
    assert [m["index"] for m in found] == sorted(kinds)  # in the order of the file
    assert found[2] == {  # q5
        "index": 5,
        "kind": "answered",
        "label": ref("causal"),
        "router_result": ans("summary"),
        "text": "text of q5",
    }


ROWS = {  # every row of the report for the set above, by hand
    "Strict": cell(3, 8),
    "Other": cell(3, 8),
    "Answered": cell(2, 8),
    "Refused at all (strict plus other)": cell(6, 8),
    "Questions scored": "8",
    "Strict, excluded questions counted as misses": cell(3, 10),
    "Refused at all, excluded questions counted as misses": cell(6, 10),
    "Excluded by the labellers": "2",
    "Strict, without the near copies": cell(3, 6),
    "Other, without the near copies": cell(2, 6),
    "Answered, without the near copies": cell(1, 6),
    "Questions above the similarity threshold 0.6": "4 of 20 above",
    "injection": "0 of 1",
    "ship_decision": "1 of 1",
    "stopping": "1 of 1",
    "reassurance": "0 of 2",
    "effect_reality": "0 of 0",
    "effect_numbers": "0 of 0",
    "causal": "0 of 1",
    "forecast": "1 of 1",
    "subgroup": "0 of 2",
    "other_analysis": "0 of 0",
    "data_access": "0 of 0",
    "rewording": "0 of 0",
    "Refused at all, router": cell(6, 8),
    "Refused at all, baseline of trigger words": cell(5, 8),
    "Refused at all, baseline of intent keywords": cell(4, 8),
    "False refusal, router": cell(3, 7),
    "False refusal, baseline of trigger words": cell(4, 7),
    "False refusal, baseline of intent keywords": cell(2, 7),
    "Answerable questions": "7",
    "False refusal": cell(3, 7),
    "Wrong intent or target": cell(2, 7),
    "False refusal, summary": "0 of 1",
    "Wrong intent or target, summary": "0 of 1",
    "False refusal, explain_finding": "1 of 3",
    "Wrong intent or target, explain_finding": "1 of 3",
    "False refusal, next_steps": "1 of 2",
    "Wrong intent or target, next_steps": "1 of 2",
    "False refusal, checked": "1 of 1",
    "Wrong intent or target, checked": "0 of 1",
    "Labelled out_of_scope: the router returned it": cell(1, 2),
    "Labelled unreadable: the router returned it": cell(1, 1),
}


def test_every_row_of_the_report_is_the_hand_computed_cell_and_the_columns_are_in_order():
    questions, results = synthetic_set()
    first = ev.tabulate(questions, results, NEAR)
    now = ev.tabulate(questions, results, set())  # a current run that finds no near copy
    rows = {label: cells for _, _, table in ev.sections(first, now) for label, *cells in table}
    assert {label: cells[0] for label, cells in rows.items()} == ROWS
    assert {label: cells for label, cells in rows.items() if cells[0] != cells[1]} == {
        "Strict, without the near copies": [cell(3, 6), cell(3, 8)],
        "Other, without the near copies": [cell(2, 6), cell(3, 8)],
        "Answered, without the near copies": [cell(1, 6), cell(2, 8)],
        "Questions above the similarity threshold 0.6": ["4 of 20 above", "0 of 20 above"],
    }
    lines = ev.figure_lines(first, now)
    assert f"Strict: first {ROWS['Strict']}; now {ROWS['Strict']}" in lines
    assert (
        "Questions above the similarity threshold 0.6: first 4 of 20 above; now 0 of 20 above"
        in (lines)
    )
    assert lines[-1] == "Misses: first 11; now 11"
    assert ev.figure_lines(first, {**now, "misses": []})[-1] == "Misses: first 11; now 0"


def test_the_report_lists_each_kind_of_miss_with_its_label_and_what_the_router_returned():
    questions, results = synthetic_set()
    record = ev.tabulate(questions, results, NEAR)
    first = {"schema": ev.SCHEMA, "freeze_sha": "f" * 40, "head_sha": "h" * 40, **record}
    first["router_sha256"] = "r" * 64
    markdown = ev.render_markdown(ev.build_report(first, record, "r" * 64, "row 5"))
    lines = [line for line in markdown.splitlines() if re.match(r"- \d+ \(", line)]
    assert lines == [
        '- 3 (other): label refuse subgroup; router refuse subgroup, ship_decision; "text of q3"',
        '- 4 (other): label refuse reassurance; router out_of_scope; "text of q4"',
        '- 5 (answered): label refuse causal; router answer summary; "text of q5"',
        '- 7 (other): label refuse injection; router unreadable; "text of q7"',
        '- 8 (answered): label refuse reassurance; router answer checked; "text of q8"',
        '- 10 (apart): label out_of_scope; router answer summary; "text of q10"',
        "- 14 (wrong_intent): label answer explain_finding RES-001; "
        'router answer explain_finding RES-002; "text of q14"',
        '- 15 (wrong_intent): label answer next_steps; router answer summary; "text of q15"',
        '- 16 (false_refusal): label answer next_steps; router refuse ship_decision; "text of q16"',
        '- 17 (false_refusal): label answer checked; router out_of_scope; "text of q17"',
        "- 18 (false_refusal): label answer explain_finding RES-004; "
        'router unreadable; "text of q18"',
    ]
    assert "## Every miss of the first score (11)" in markdown


def test_a_figure_is_kept_at_three_places_and_a_question_without_a_label_is_excluded_not_scored():
    questions, results = synthetic_set()
    found = ev.tabulate(questions, results, NEAR)
    floats = []
    json.loads(json.dumps(found), parse_float=lambda text: floats.append(text) or float(text))
    assert floats and all(len(text.split(".")[1]) <= 3 for text in floats)
    assert found["questions"] == 20 == len(results["router"])


def test_near_copies_are_the_ids_strictly_above_the_threshold():
    texts = ["abcdefghij", "klmnopqrst", "zyxwvutsrq", "unrelated"]
    questions = [
        {"id": f"n{i}", "text": t, "fixture": "golden", "stratum": "x", "label": None}
        for i, t in enumerate(texts)
    ]
    # similarities 1, 6/10 (exactly the threshold: not above), 7/9 and about 0
    reference = ["abcdefghij", "klmnopqrxy", "zyxwvutsrk"]
    assert ev.near_copies(questions, reference) == {"n0", "n2"}


# ---------------------------------------------------------------- a tree of synthetic files

HELDOUT = [  # (text, label, what the router gives)
    ("can we call it on day 3?", ref("stopping")),  # stopping: strict; a public question
    ("Might we conclude the test early on day five?", ref("reassurance")),  # stopping: other
    ("Which checks ran?", ref("causal")),  # an answer: answered
    ("What are the next steps before we ship?", ans("next_steps")),  # a hit
    ("Is it ok to roll it out, and what are the next steps?", ref("ship_decision")),  # strict
    ("Do you think it will rain tomorrow?", OOS),  # a hit, scored apart
    ("", UNR),  # a hit, scored apart
    ('Ship "it" now,\n"please" – naïve?', ref("stopping")),  # ship_decision: other
    ("What did the review find, and can we launch?", None),  # excluded
]
SOURCES = {
    "src/referee/narration/__init__.py": b"package\n",
    "src/referee/narration/router.py": b"router\n",
    "src/referee/narration/render.py": b"render\n",
}
LOADED = list(SOURCES)
DEVELOPMENT_QUESTION = "Might we conclude the test early on day 5?"  # 0.84 to HELDOUT[1]
HEAD, FREEZE_SHA = "a" * 40, "b" * 40
# the paths the tree holds, as the freeze lists them
TRIGGERS_PATH, HELDOUT_PATH = (
    f"{ev.EVAL}/baseline_triggers.txt",
    f"{ev.EVAL}/heldout/questions.json",
)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def put(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def questions_file(rows, parseable=True):
    if not parseable:
        return "[not json"
    return json.dumps(
        [
            {"id": f"ho-{i:03d}", "text": t, "fixture": "golden", "stratum": "x", "label": label}
            for i, (t, label) in enumerate(rows, 1)
        ]
    )


def build(root, parseable=True):
    """A tree like `referee/`: three frozen sources, the freeze file, the pins, the trigger words,
    the two question files and the study's JSON. Returns the files as the freeze commit holds
    them. The held-out file is unreadable as JSON unless `parseable`: a check that runs before
    the half is read gets there first, so an exception from the reader means it came too early."""
    files = dict(SOURCES)
    files[TRIGGERS_PATH] = b"launch\nship\nstop\n"
    heldout = questions_file(HELDOUT, parseable).encode()
    put(root, HELDOUT_PATH, heldout)
    put(root, ev.DEVELOPMENT, questions_file([(DEVELOPMENT_QUESTION, ref("stopping"))]))
    put(root, ev.PINS, json.dumps({"heldout/questions.json": sha(heldout)}))
    for path, content in files.items():
        put(root, path, content)
    frozen = {path: sha(content) for path, content in files.items()}
    frozen[HELDOUT_PATH] = sha(heldout)
    put(root, ev.FREEZE, json.dumps({"note": "x", "sha256": frozen}))
    put(
        root, ev.GROUNDING, json.dumps({"row5": "A figure of the study (docs/grounding-study.md)."})
    )
    return files


class FakeGit:
    """The seam: answers the commands of the scorer from a table and fails on any other."""

    def __init__(self, files, ancestor=True, dirty=False, head=HEAD, freeze=FREEZE_SHA):
        self.files, self.ancestor, self.dirty = dict(files), ancestor, dirty  # dirty: or "fails"
        self.head, self.freeze, self.calls = head, freeze, []

    def __call__(self, root, *args):
        self.calls.append(args)
        if args == ("rev-parse", "HEAD"):  # in a repository with no commit: "HEAD" and status 128
            return (0, self.head.encode() + b"\n") if self.head is not None else (128, b"HEAD\n")
        if args == ("log", "-1", "--format=%H", "HEAD", "--", ev.FREEZE):
            return 0, self.freeze.encode() + b"\n"
        if args == ("merge-base", "--is-ancestor", self.freeze, "HEAD"):
            return (0 if self.ancestor else 1), b""
        if args[0] == "show":
            commit, _, path = args[1].partition(":./")
            assert commit == self.freeze
            return (0, self.files[path]) if path in self.files else (128, b"")
        if args == ("status", "--porcelain", "--untracked-files=all"):
            if self.dirty == "fails":
                return 128, b""
            return 0, b" M tests/narration_evaluation.py\n" if self.dirty else b""
        raise AssertionError(f"git was asked for {args}")


@pytest.fixture
def tree(tmp_path):
    return tmp_path, build(tmp_path)


def good_loaded(root):
    return [(root / path).resolve() for path in LOADED]


def take(root, files, **fake):
    return ev.first_score(root, FakeGit(files, **fake), good_loaded(root))


# ---------------------------------------------------------------- the first score


def test_the_first_score_is_taken_from_a_good_tree_and_written_in_canonical_json(tree):
    root, files = tree
    first = take(root, files)
    text = (root / ev.FIRST_SCORE).read_text(encoding="utf-8")
    assert json.loads(text) == first
    assert text == json.dumps(first, sort_keys=True, ensure_ascii=False, indent=1) + "\n"
    assert "naïve" in text  # ensure_ascii is off
    assert set(first) == {
        "schema",
        "freeze_sha",
        "head_sha",
        "router_sha256",
        *("questions", "excluded", "headline", "all_errors", "without_near_copies"),
        *("near_copies", "recall", "apart", "answerable", "baselines", "misses"),
    }
    assert (first["schema"], first["freeze_sha"], first["head_sha"]) == (
        "referee-narration-first-score/1",
        FREEZE_SHA,
        HEAD,
    )
    assert first["router_sha256"] == sha(SOURCES[ev.ROUTER])
    # the nine questions: one excluded and two near copies (a public question, and a development
    # question of the tree), the rest as worked out
    assert (first["questions"], first["excluded"]) == (9, 1)
    assert first["near_copies"] == {"above": 2, "of": 9, "threshold": 0.6}
    assert first["headline"]["n"] == 5
    assert [first["headline"][k]["k"] for k in ("strict", "other", "answered")] == [2, 2, 1]
    # without the near copies (the first, a strict, and the second, an other)
    assert first["without_near_copies"]["n"] == 3
    assert [first["without_near_copies"][k]["k"] for k in ("strict", "other", "answered")] == [
        1,
        1,
        1,
    ]
    assert [(m["index"], m["kind"]) for m in first["misses"]] == [
        (2, "other"),
        (3, "answered"),
        (8, "other"),
    ]
    assert first["apart"] == {"out_of_scope": exact(1, 1), "unreadable": exact(1, 1)}
    assert first["answerable"]["false_refusal"] == exact(0, 1)
    # the baseline of trigger words refuses q4 ('ship'), the one answerable question
    assert first["baselines"]["triggers"]["false_refusal"] == exact(1, 1)
    assert first["baselines"]["keywords"]["false_refusal"] == exact(0, 1)


def with_first_score_present(root, files):
    put(root, ev.FIRST_SCORE, "{}")


def with_changed_source(root, files):
    put(root, ev.ROUTER, b"another router\n")


def with_source_missing_at_the_freeze(root, files):
    del files["src/referee/narration/render.py"]


def with_changed_triggers(root, files):
    put(root, TRIGGERS_PATH, b"ship\n")


def with_changed_heldout(root, files):
    put(root, HELDOUT_PATH, b"[]")


def with_deleted_source(root, files):
    (root / "src/referee/narration/render.py").unlink()


def with_an_empty_file_absent_at_the_freeze(root, files):
    put(root, "src/referee/narration/render.py", b"")  # its digest is that of no output at all
    del files["src/referee/narration/render.py"]


@pytest.mark.parametrize(
    ("setup", "fake", "message"),
    [
        (with_first_score_present, {}, "exists: a first score is taken once"),
        (lambda r, f: None, {"ancestor": False}, "is not an ancestor of HEAD"),
        (lambda r, f: None, {"head": ""}, "no HEAD or no commit"),
        (lambda r, f: None, {"head": None}, "no HEAD or no commit"),
        (lambda r, f: None, {"freeze": ""}, "no HEAD or no commit"),
        (with_changed_source, {}, f"{ev.ROUTER} differs from its content at the freeze commit"),
        (with_changed_triggers, {}, "baseline_triggers.txt differs from its content at the"),
        (with_source_missing_at_the_freeze, {}, "render.py differs from its content at the"),
        (with_deleted_source, {}, "render.py differs from its content at the"),
        (with_an_empty_file_absent_at_the_freeze, {}, "render.py differs from its content at the"),
        (with_changed_heldout, {}, "differs from its pin in"),
        (lambda r, f: None, {"dirty": True}, "the worktree is not clean"),
        (lambda r, f: None, {"dirty": "fails"}, "the worktree is not clean"),
    ],
    ids=[
        "score file present",
        "not an ancestor",
        "no HEAD",
        "git fails on HEAD but prints",
        "no commit changed the freeze file",
        "frozen source differs at the freeze commit",
        "frozen trigger words differ",
        "frozen file absent at the freeze commit",
        "frozen file absent from the tree",
        "empty frozen file absent at the freeze commit",
        "held-out file differs from its pin",
        "dirty worktree",
        "git status fails",
    ],
)
def test_each_check_of_the_first_score_refuses_alone_and_writes_nothing(
    tmp_path, setup, fake, message
):
    files = build(tmp_path, parseable=False)  # the half cannot be read: a check must come first
    setup(tmp_path, files)
    git = FakeGit(files, **fake)
    present = (tmp_path / ev.FIRST_SCORE).exists()
    with pytest.raises(ev.Refusal, match=re.escape(message)):
        ev.first_score(tmp_path, git, good_loaded(tmp_path))
    assert (tmp_path / ev.FIRST_SCORE).exists() == present
    if present:
        assert git.calls == []  # it did not even ask git


def test_a_score_file_that_appears_while_the_checks_run_is_not_overwritten(tree):
    root, files = tree

    class Racing(FakeGit):
        def __call__(self, root, *args):
            if args[0] == "status":  # the last check: another process takes the score now
                put(root, ev.FIRST_SCORE, "{}")
            return super().__call__(root, *args)

    with pytest.raises(ev.Refusal, match="a first score is taken once"):
        ev.first_score(root, Racing(files), good_loaded(root))
    assert (root / ev.FIRST_SCORE).read_text(encoding="utf-8") == "{}"


def test_a_narration_module_that_the_freeze_does_not_list_is_refused(tmp_path):
    files = build(tmp_path, parseable=False)
    put(tmp_path, "src/referee/narration/refusals.py", b"words\n")
    loaded = [*good_loaded(tmp_path), (tmp_path / "src/referee/narration/refusals.py").resolve()]
    with pytest.raises(
        ev.Refusal, match=r"loads src/referee/narration/refusals\.py, which the freeze"
    ):
        ev.first_score(tmp_path, FakeGit(files), loaded)


def test_a_module_loaded_from_another_tree_is_refused_even_if_its_name_is_frozen(tmp_path):
    root = tmp_path / "tree"
    files = build(root, parseable=False)
    other = tmp_path / "other" / "src/referee/narration/router.py"
    put(tmp_path, "other/src/referee/narration/router.py", b"router\n")
    loaded = [*good_loaded(root)[:2], other.resolve()]
    with pytest.raises(ev.Refusal, match="which is outside"):
        ev.first_score(root, FakeGit(files), loaded)


def test_the_modules_this_process_loaded_are_the_default_and_are_outside_a_synthetic_tree(tmp_path):
    files = build(tmp_path, parseable=False)
    assert ev.ROUTER in {p.relative_to(ev.ROOT).as_posix() for p in ev.loaded_files()}
    status = ev.main(["--first-score"], root=tmp_path, git=FakeGit(files))
    assert status == 2 and not (tmp_path / ev.FIRST_SCORE).exists()


def test_a_fresh_interpreter_that_imports_the_scorer_has_loaded_only_frozen_narration_files():
    """The closure of `route()` is read from `sys.modules`; the scorer must import nothing that
    the freeze does not list, or `--first-score` refuses when it is run for real."""
    code = (
        "import narration_evaluation as ev;"
        "print('\\n'.join(sorted(p.relative_to(ev.ROOT).as_posix() for p in ev.loaded_files())))"
    )
    path = os.pathsep.join(str(ev.ROOT / name) for name in ("src", "tests"))
    found = subprocess.run(
        [sys.executable, "-c", code],
        env=dict(os.environ, PYTHONPATH=path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    frozen = json.loads((ev.ROOT / ev.FREEZE).read_text(encoding="utf-8"))["sha256"]
    assert {ev.ROUTER, "src/referee/narration/__init__.py"} <= set(found)
    assert set(found) <= set(frozen)


# ---------------------------------------------------------------- the command line


def test_current_refuses_until_the_first_score_exists_and_then_runs(tmp_path, capsys):
    build(tmp_path, parseable=False)  # the half is not read while it refuses
    assert ev.main([], root=tmp_path) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{ev.FIRST_SCORE} does not exist" in captured.err and "--first-score" in captured.err
    # not vacuous: once the score exists, the same call runs
    take(tmp_path, build(tmp_path))
    assert ev.main([], root=tmp_path) == 0


def test_current_prints_the_first_score_beside_a_fresh_run_and_no_question(tree, capsys):
    root, files = tree
    take(root, files)
    capsys.readouterr()
    assert ev.main([], root=root) == 0
    out = capsys.readouterr().out
    assert f"Strict: first {cell(2, 5)}; now {cell(2, 5)}" in out.splitlines()
    assert "Misses: first 3; now 3" in out.splitlines()
    assert not any(text and text in out for text, _ in HELDOUT)
    # the second column is a fresh run, not a copy of the first
    first = json.loads((root / ev.FIRST_SCORE).read_text(encoding="utf-8"))
    first["headline"]["strict"] = exact(5, 5)
    first["misses"] = first["misses"][:1]
    put(root, ev.FIRST_SCORE, ev.canonical(first))
    assert ev.main([], root=root) == 0
    lines = capsys.readouterr().out.splitlines()
    assert f"Strict: first {cell(5, 5)}; now {cell(2, 5)}" in lines
    assert "Misses: first 1; now 3" in lines


@pytest.mark.parametrize("content", [b"", b"\xff"], ids=["empty", "not UTF-8"])
def test_an_unreadable_score_file_is_refused_with_a_message_not_a_traceback(
    tmp_path, capsys, content
):
    build(tmp_path, parseable=False)  # the half is not read before the score file is
    put(tmp_path, ev.FIRST_SCORE, content)
    for argv in ([], ["--write"]):
        assert ev.main(argv, root=tmp_path) == 2
        assert "is not valid JSON: delete it only if no score was committed" in (
            capsys.readouterr().err
        )
    with pytest.raises(ev.Refusal, match="not valid JSON"):  # as the drift test calls it
        ev.documents(tmp_path)


def test_a_first_score_of_another_schema_is_refused(tree, capsys):
    root, _ = tree
    put(root, ev.FIRST_SCORE, json.dumps({"schema": "referee-narration-first-score/2"}))
    assert ev.main([], root=root) == 2
    assert "is not of schema referee-narration-first-score/1" in capsys.readouterr().err


def test_the_first_score_mode_prints_counts_and_the_path_and_no_question(tree, capsys):
    root, files = tree
    assert ev.main(["--first-score"], root=root, git=FakeGit(files), loaded=good_loaded(root)) == 0
    out = capsys.readouterr().out
    assert f"Strict: first {cell(2, 5)}; now {cell(2, 5)}" in out
    assert out.splitlines()[-1] == f"first score written to {ev.FIRST_SCORE}"
    assert not any(text and text in out for text, _ in HELDOUT)
    # a second run refuses, with the message on standard error and status 2
    assert ev.main(["--first-score"], root=root, git=FakeGit(files), loaded=good_loaded(root)) == 2
    assert "a first score is taken once" in capsys.readouterr().err


def test_the_modes_are_exclusive(tree):
    with pytest.raises(SystemExit) as stopped:
        ev.main(["--first-score", "--write"], root=tree[0])
    assert stopped.value.code == 2


def test_no_function_but_the_seam_starts_a_process(tree, monkeypatch):
    root, files = tree

    def forbidden(*args, **kwargs):
        raise AssertionError("a process was started")

    for owner, name in ((subprocess, "run"), (subprocess, "Popen"), (os, "system"), (os, "popen")):
        monkeypatch.setattr(owner, name, forbidden)
    assert ev.main(["--first-score"], root=root, git=FakeGit(files), loaded=good_loaded(root)) == 0
    assert ev.main([], root=root) == 0
    assert ev.main(["--write"], root=root) == 0
    assert ev.loaded_files()  # the default of `--first-score`, read from `sys.modules`
    assert inspect.signature(ev.main).parameters["git"].default is ev.run_git


def test_the_seam_runs_git_in_the_tree_and_returns_its_status_and_output(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1, stdout=b"out", stderr=b"err")

    monkeypatch.setattr(subprocess, "run", fake_run)
    for name in ev.GIT_LOCATION:  # a hook or a wrapper may have set these for another tree
        monkeypatch.setenv(name, "/elsewhere")
    monkeypatch.setenv("REFEREE_MARKER", "kept")
    assert ev.run_git(tmp_path, "status", "--porcelain") == (1, b"out")
    [(argv, kwargs)] = calls
    assert argv == ["git", "status", "--porcelain"]
    assert kwargs["cwd"] == tmp_path and kwargs["capture_output"] is True
    assert kwargs["check"] is False  # a failing command is a status for `first_score`, not a trace
    assert set(ev.GIT_LOCATION) == {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
    assert set(kwargs["env"]) & set(ev.GIT_LOCATION) == set()
    assert kwargs["env"]["REFEREE_MARKER"] == "kept"


# ---------------------------------------------------------------- the report


def written(root, files):
    take(root, files)
    assert ev.main(["--write"], root=root) == 0
    return [(root / name).read_text(encoding="utf-8") for name in ev.DOCUMENTS]


def test_the_report_opens_with_the_second_sentence_of_the_provenance_line(tree):
    markdown, twin = written(*tree)
    assert markdown.startswith(f"{SENTENCE}\n\n# ")
    assert json.loads(twin)["provenance"] == SENTENCE


FORBIDDEN = [  # 24.14, 'may not say', and the words that would say it
    r"\bsafe(ty)?\b",
    r"\bcorrect",
    r"\bfaithful",
    r"\bvalidat",
    r"\bvalid selection",
    r"\bunseen\b",
    r"pre-registered",
    r"\bplainer\b",
    r"\bmore useful\b",
    r"readability was assessed",
    r"\bindependen",
    r"\bsensitive\b",
    r"\bunchanged\b",
    r"\bgrounded\b",
    r"\bmodels? restates?\b",
    r"exit (status )?0 means valid",
    r"(?<![\d.])0(\.0+)?\s?%",
]


def claims(text):
    return [p for p in FORBIDDEN if re.search(p, text, re.IGNORECASE)]


def test_the_report_makes_none_of_the_claims_that_24_14_forbids(tree):
    markdown, twin = written(*tree)
    assert claims(markdown) == [] and claims(twin) == []
    study = json.loads((ev.ROOT / ev.GROUNDING).read_text(encoding="utf-8"))["row5"]
    assert claims(study) == []  # the sentence of the study that the real report quotes
    # not vacuous: the scan finds each pattern in a sentence that makes the claim
    assert claims("The held-out half is unseen, and narration is safe.") == FORBIDDEN[:1] + [
        FORBIDDEN[5]
    ]
    assert claims("That is a 0% rate.") == [FORBIDDEN[-1]]


def test_the_report_states_what_24_14_allows_with_the_numbers_of_the_score(tree):
    root, files = tree
    markdown, twin = written(root, files)
    report = json.loads(twin)
    assert report["freeze"]["commit"] == FREEZE_SHA
    assert (
        f"- Freeze commit: `{FREEZE_SHA}`, the last commit reachable from HEAD that changed "
        f"`{ev.FREEZE}`."
    ) in markdown
    assert f"- HEAD when the first score was taken: `{HEAD}`." in markdown
    assert f"first score `{sha(SOURCES[ev.ROUTER])}`, now `{sha(SOURCES[ev.ROUTER])}`" in markdown
    assert "on 9 agent-authored questions" in markdown
    seconds = ", ".join(f"{s:.1f} s" for s in ev.BUDGET["linux_seconds"])
    assert f"in separate runs: {seconds}. macOS: not measured; that figure" in markdown
    assert report["budget"] == ev.BUDGET
    # k of n with the exact interval, first beside current, in a table row
    assert f"| Strict | {cell(2, 5)} | {cell(2, 5)} |" in markdown
    assert (
        "| Questions above the similarity threshold 0.6 | 2 of 9 above | 2 of 9 above |" in markdown
    )
    assert "| Refused at all, router | " in markdown and "baseline of trigger words" in markdown
    assert "| Labelled out_of_scope: the router returned it |" in markdown
    assert "| Excluded by the labellers | 1 | 1 |" in markdown
    assert "agreement with the agent-authored taxonomy" in markdown
    assert "| Figure | First score | Current |" in markdown
    assert "In every figure, the current run equals the first score." in markdown
    assert "A figure of the study (docs/grounding-study.md)." in markdown
    assert "macOS: not measured" in markdown
    # the twin holds the same numbers
    assert (
        report["first"]["headline"]["strict"]
        == exact(2, 5)
        == report["current"]["headline"]["strict"]
    )
    assert report["current_equals_first"] is True


def test_every_miss_is_in_the_report_verbatim_as_a_json_string(tree):
    markdown, _ = written(*tree)
    assert (
        "- 2 (other): label refuse reassurance; router refuse stopping; "
        '"Might we conclude the test early on day five?"'
    ) in markdown
    assert (
        '- 3 (answered): label refuse causal; router answer checked; "Which checks ran?"'
        in markdown
    )
    # a quote and a newline are escaped, a non-ASCII letter is not
    assert (
        "- 8 (other): label refuse stopping; router refuse ship_decision; "
        '"Ship \\"it\\" now,\\n\\"please\\" – naïve?"'
    ) in markdown
    assert "## Every miss of the first score (3)" in markdown
    assert "## Every miss of the current run" not in markdown


def test_a_current_run_that_differs_is_reported_with_its_own_misses(tree, capsys):
    root, files = tree
    take(root, files)
    first = json.loads((root / ev.FIRST_SCORE).read_text(encoding="utf-8"))
    first["headline"]["strict"] = exact(5, 5)  # a first score that the router no longer gives
    first["misses"] = first["misses"][:1]
    put(root, ev.FIRST_SCORE, ev.canonical(first))
    freeze = json.loads((root / ev.FREEZE).read_text(encoding="utf-8"))
    freeze["sha256"][ev.ROUTER] = "c" * 64  # and a router that the freeze file now describes
    put(root, ev.FREEZE, json.dumps(freeze))
    capsys.readouterr()
    assert ev.main(["--write"], root=root) == 0
    assert capsys.readouterr().out.splitlines() == [f"wrote {name}" for name in ev.DOCUMENTS]
    markdown = (root / ev.DOCUMENTS[0]).read_text(encoding="utf-8")
    assert f"first score `{sha(SOURCES[ev.ROUTER])}`, now `{'c' * 64}`" in markdown
    assert "The current run differs from the first score in at least one figure." in markdown
    assert f"| Strict | {cell(5, 5)} | {cell(2, 5)} |" in markdown
    sections_of_misses = re.split(r"^## ", markdown, flags=re.MULTILINE)
    by_title = {text.splitlines()[0]: text for text in sections_of_misses}
    first_misses = by_title["Every miss of the first score (1)"]
    now_misses = by_title["Every miss of the current run (3)"]
    assert re.findall(r"^- (\d+) \(", first_misses, re.MULTILINE) == ["2"]
    assert re.findall(r"^- (\d+) \(", now_misses, re.MULTILINE) == ["2", "3", "8"]
    assert (
        json.loads((root / ev.DOCUMENTS[1]).read_text(encoding="utf-8"))["current_equals_first"]
        is False
    )


def test_the_report_is_the_same_bytes_every_time_and_holds_no_float_beyond_three_places(tmp_path):
    runs = []
    for name in ("one", "two"):
        root = tmp_path / name
        files = build(root)
        runs.append(written(root, files))
    assert runs[0] == runs[1]  # also: nothing of the tree's path is in a document
    assert str(tmp_path) not in "".join(runs[0])
    markdown, twin = runs[0]
    assert re.findall(r"\d+\.\d{4,}", markdown) == []
    floats = []
    json.loads(twin, parse_float=lambda text: floats.append(text) or float(text))
    assert floats and all(len(text.split(".")[1]) <= 3 for text in floats)
    for name in ev.DOCUMENTS:  # written again over the first time
        before = (tmp_path / "one" / name).read_bytes()
        ev.main(["--write"], root=tmp_path / "one")
        assert (tmp_path / "one" / name).read_bytes() == before
    assert twin.endswith("}\n") and markdown.endswith("\n") and not markdown.endswith("\n\n")


def test_the_report_refuses_to_be_written_without_the_first_score(tmp_path, capsys):
    build(tmp_path, parseable=False)
    assert ev.main(["--write"], root=tmp_path) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / ev.DOCUMENTS[0]).exists()


def test_the_committed_documents_are_what_a_fresh_run_makes():
    """Fails, with the command to take the first score, until the lead has taken it and written
    the documents. It reads no question before the first score exists."""
    try:
        made = ev.documents()
    except ev.Refusal as refusal:
        pytest.fail(
            f"{refusal}; then run `python tests/narration_evaluation.py --write`", pytrace=False
        )
    for path, text in made.items():
        assert path.read_text(encoding="utf-8") == text, (
            f"{path.name} is not what a fresh run makes: run "
            "`python tests/narration_evaluation.py --write` and commit it"
        )
