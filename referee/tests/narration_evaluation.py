"""The first score of the narration router on the held-out half, and the evaluation report (24.10).

    python tests/narration_evaluation.py                 # the current score beside the first
    python tests/narration_evaluation.py --first-score   # take the first score, once
    python tests/narration_evaluation.py --write         # docs/narration-evaluation.md and .json

Run from `referee/`, with `src` and `tests` on `PYTHONPATH`. Status 0, or 2 with a message on
standard error: a refusal to run, or unusable arguments.

The default mode refuses until `tests/data/narration_eval/heldout_first_score.json` exists. Only
`--first-score` calls `git`, through `run_git`, the one function of this module that starts a
process, so that a test can pass a fake. It checks that the last commit reachable from HEAD that
changed `router_freeze.json` is an ancestor of HEAD, that each frozen file equals its content at
that commit (the held-out files: their pins), that every `referee.narration` module this process
loaded is a frozen file under this tree, and that the worktree is clean; it refuses when the score
file exists; then it routes the half and writes the file. It prints counts and the path, never a
question. Routing uses the files of this tree only if `src` leads `PYTHONPATH`: the loaded
modules are checked by the file they came from, so another checkout's router is refused.

The closure of `route()` is read from `sys.modules`, not from a child process (the freeze test
uses one): this module imports `referee.narration.router` and no other narration module, so what
a fresh interpreter has loaded is what `route()` needs. A test checks that on a fresh interpreter.

A question is `{id, text, fixture, stratum, label}` (see `narration_scoring`); `label` None is a
question the labellers excluded. Everything here takes the questions as arguments or reads them
under `root`, so a test points it at a tree of synthetic questions.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Any

import narration_scoring as ns

from referee.narration.router import (
    DOMAIN,
    INTENT_PATTERNS,
    PHRASES,
    compile_pattern,
    matches,
    normalise,
    read,
    route,
)

ROOT = Path(__file__).resolve().parents[1]  # referee/
EVAL = "tests/data/narration_eval"
HELDOUT = f"{EVAL}/heldout/questions.json"
DEVELOPMENT = f"{EVAL}/development/questions.json"
FIRST_SCORE = f"{EVAL}/heldout_first_score.json"
FREEZE = f"{EVAL}/router_freeze.json"
PINS = f"{EVAL}/pins.json"
TRIGGERS = f"{EVAL}/baseline_triggers.txt"
GROUNDING = "docs/grounding-study.json"
DOCUMENTS = ("docs/narration-evaluation.md", "docs/narration-evaluation.json")
ROUTER = "src/referee/narration/router.py"
SCHEMA = "referee-narration-first-score/1"
FIRST_KEYS = ("schema", "freeze_sha", "head_sha", "router_sha256")  # the rest is `measure`'s

PROVENANCE = (
    "Language-model agents wrote the code, tests, labels and reviews and every question except "
    "the three quoted from the design document; no human labelled a question."
)
# The budget of 24.11, timed by hand on Linux when the report was written (the command and the
# seconds of separate runs); the macOS figure comes from CI. Edit it with a new measurement, then
# run --write.
BUDGET = {
    "command": "pytest -q tests/test_narration_*.py tests/test_repository_hygiene.py",
    "linux_seconds": [26.5, 26.7, 25.5],
    "macos": "not measured",
}

Result = ns.Label
Git = Callable[..., tuple[int, bytes]]


class Refusal(Exception):
    """A reason not to run; `main` prints it and exits with status 2."""


# ---------------------------------------------------------------- the router and its baselines


def result_of(understanding: Any) -> Result:
    """The router's result as the scorer reads it; a refusal with no category is the default."""
    if understanding.kind == "unreadable":
        return {"route": "unreadable"}
    if understanding.kind == "refusal":
        if not understanding.categories:
            return {"route": "out_of_scope"}
        return {"route": "refuse", "categories": list(understanding.categories)}
    return {"route": "answer", "intent": understanding.intent, "target": understanding.target}


_INTENTS = {
    name: tuple(compile_pattern(pattern) for pattern in patterns)
    for name, patterns in INTENT_PATTERNS.items()
}
_PHRASES = tuple(compile_pattern(pattern) for table in PHRASES.values() for pattern in table)
_DOMAIN = compile_pattern((DOMAIN,))


def _holds(words: list[str], patterns: Collection[Any]) -> bool:
    return any(matches(words, steps) for steps in patterns)


def _answer(intent: str) -> Result:
    return {"route": "answer", "intent": intent, "target": None}


def intent_of(words: list[str], ids: list[str]) -> Result:
    """The router's intent matcher without its refusal categories: an answer, or the default
    route. The target of an explanation is not resolved; the baselines are scored on whether they
    refuse, not on what they answer."""
    named = bool(ids) or _holds(words, _PHRASES)
    if not (named or matches(words, _DOMAIN)):
        return {"route": "out_of_scope"}
    for intent in ("checked", "next_steps"):
        if _holds(words, _INTENTS[intent]):
            return _answer(intent)
    if named:
        return _answer("explain_finding")
    if _holds(words, _INTENTS["summary"]):
        return _answer("summary")
    return {"route": "out_of_scope"}


def baseline_triggers(text: str, triggers: Collection[str]) -> Result:
    """Refused when a word of the question is a trigger word, else the intent matcher decides."""
    words, ids = read(normalise(text))
    return {"route": "out_of_scope"} if set(words) & set(triggers) else intent_of(words, ids)


def baseline_keywords(text: str) -> Result:
    """Answered when any intent pattern matches, else refused."""
    words, _ = read(normalise(text))
    for intent, patterns in _INTENTS.items():
        if _holds(words, patterns):
            return _answer(intent)
    return {"route": "out_of_scope"}


def route_all(questions: Sequence[ns.Question], triggers: Collection[str]) -> dict[str, list]:
    """The result of the router and of each baseline for every question, in order."""
    texts = [question["text"] for question in questions]
    return {
        "router": [result_of(route(text)) for text in texts],
        "triggers": [baseline_triggers(text, triggers) for text in texts],
        "keywords": [baseline_keywords(text) for text in texts],
    }


# ---------------------------------------------------------------- the score


def near_copies(questions: Sequence[ns.Question], reference: Sequence[str]) -> set[str]:
    """The ids of the questions whose largest similarity (from the lint) is above the threshold."""
    similarity = ns.lint(questions, "heldout", reference)["max_similarity"]
    return {q["id"] for q, s in zip(questions, similarity, strict=True) if s > ns.THRESHOLD}


def miss_kind(label: ns.Label, result: Result) -> str | None:
    """Why a question is a miss, or None when it is a hit. A refusal-labelled question that is
    not strict is `other` or `answered`; an answerable one is a `false_refusal` or a
    `wrong_intent` (intent or target); one labelled out_of_scope or unreadable is an `apart`."""
    if label["route"] == "refuse":
        cell = ns.classify(label, result)
        return None if cell == "strict" else cell
    if label["route"] == "answer":
        if result["route"] != "answer":
            return "false_refusal"
        same = (result["intent"], result.get("target")) == (label["intent"], label.get("target"))
        return None if same else "wrong_intent"
    return None if result["route"] == label["route"] else "apart"


def tabulate(
    questions: Sequence[ns.Question], results: dict[str, list], near: Collection[str]
) -> dict[str, Any]:
    """Every figure of 24.10 for the questions and the results `route_all` gave, floats at three
    places. A question with no label is excluded (counted, in no k)."""
    kept = [i for i, q in enumerate(questions) if q["label"] is not None]
    excluded = len(questions) - len(kept)

    def items(name: str) -> list[ns.Item]:
        return [
            {"id": questions[i]["id"], "label": questions[i]["label"], "result": results[name][i]}
            for i in kept
        ]

    scored = ns.score(items("router"), excluded, near)
    baselines = {name: ns.score(items(name)) for name in ("triggers", "keywords")}
    misses = []
    for i in kept:
        kind = miss_kind(questions[i]["label"], results["router"][i])
        if kind is not None:
            misses.append(
                {
                    "index": i + 1,
                    "kind": kind,
                    "label": questions[i]["label"],
                    "router_result": results["router"][i],
                    "text": questions[i]["text"],
                }
            )
    return _rounded(
        {
            "questions": len(questions),
            "excluded": excluded,
            "headline": scored["headline"],
            "all_errors": scored["all_errors"],
            "without_near_copies": scored["without_near_copies"],
            "near_copies": {"above": len(near), "of": len(questions), "threshold": ns.THRESHOLD},
            "recall": scored["recall"],
            "apart": scored["apart"],
            "answerable": scored["answerable"],
            "baselines": {
                name: {
                    "refused_at_all": s["headline"]["refused_at_all"],
                    "false_refusal": s["answerable"]["false_refusal"],
                }
                for name, s in baselines.items()
            },
            "misses": misses,
        }
    )


def _rounded(value: Any) -> Any:
    """The same record with every float at three places, so that a file does not move with the
    last digits of a library. A float sits in a dict of rates; none sits in a list."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def measure(root: Path = ROOT) -> dict[str, Any]:
    """Route the held-out half under `root` and score it: the router, the near copies and the
    baselines. This is the one function that reads the held-out questions."""
    heldout, development = _json(root / HELDOUT), _json(root / DEVELOPMENT)
    triggers = (root / TRIGGERS).read_text(encoding="utf-8").split()
    near = near_copies(heldout, ns.reference_texts(development))
    return tabulate(heldout, route_all(heldout, triggers), near)


# ---------------------------------------------------------------- the first score


def run_git(root: Path, *args: str) -> tuple[int, bytes]:
    """The one place that starts a process: `git ARGS` in `root`; its status and standard output."""
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    return done.returncode, done.stdout


def loaded_files() -> set[Path]:
    """The files of the `referee.narration` modules this process has loaded."""
    return {
        Path(module.__file__).resolve()
        for name, module in sys.modules.items()
        if name == "referee.narration" or name.startswith("referee.narration.")
    }


def _digest(path: Path) -> str | None:
    return ns.sha256_file(path) if path.is_file() else None


def first_score(root: Path, git: Git, loaded: Collection[Path]) -> dict[str, Any]:
    """Check the freeze with `git`, route the held-out half once and write the first score."""
    if (root / FIRST_SCORE).exists():
        raise Refusal(f"{FIRST_SCORE} exists: a first score is taken once")
    code, out = git(root, "rev-parse", "HEAD")  # with no commit it prints HEAD and fails
    head = out.decode().strip() if code == 0 else ""
    freeze_sha = git(root, "log", "-1", "--format=%H", "HEAD", "--", FREEZE)[1].decode().strip()
    if not head or not freeze_sha:
        raise Refusal(f"git gave no HEAD or no commit that changed {FREEZE}")
    if git(root, "merge-base", "--is-ancestor", freeze_sha, "HEAD")[0] != 0:
        raise Refusal(f"the freeze commit {freeze_sha} is not an ancestor of HEAD")

    frozen = _json(root / FREEZE)["sha256"]
    pins = _json(root / PINS)
    for path in sorted(frozen):
        now = _digest(root / path)
        pin = pins.get(path.removeprefix(f"{EVAL}/"))
        if pin is not None:  # a held-out file: its pin, not git
            if now != pin:
                raise Refusal(f"{path} differs from its pin in {PINS}")
            continue
        code, content = git(root, "show", f"{freeze_sha}:./{path}")
        if code != 0 or hashlib.sha256(content).hexdigest() != now:
            raise Refusal(f"{path} differs from its content at the freeze commit")
    for file in sorted(loaded):
        try:
            relative = file.relative_to(root.resolve()).as_posix()
        except ValueError:
            raise Refusal(f"route() loads {file}, which is outside {root}") from None
        if relative not in frozen:
            raise Refusal(f"route() loads {relative}, which the freeze does not list")
    code, out = git(root, "status", "--porcelain")
    if code != 0 or out.strip():
        raise Refusal("the worktree is not clean: commit or remove what git status lists")

    first = {
        "schema": SCHEMA,
        "freeze_sha": freeze_sha,
        "head_sha": head,
        "router_sha256": frozen[ROUTER],
        **measure(root),
    }
    (root / FIRST_SCORE).write_bytes(canonical(first).encode("utf-8"))
    return first


def load_first(root: Path) -> dict[str, Any]:
    path = root / FIRST_SCORE
    if not path.is_file():
        raise Refusal(
            f"no first score: {FIRST_SCORE} does not exist. It is taken once, by "
            "`python tests/narration_evaluation.py --first-score` (design 24.10)"
        )
    first = _json(path)
    if first.get("schema") != SCHEMA:
        raise Refusal(f"{FIRST_SCORE} is not of schema {SCHEMA}")
    return first


def record_of(first: dict[str, Any]) -> dict[str, Any]:
    """What `measure` gave when the first score was taken."""
    return {key: value for key, value in first.items() if key not in FIRST_KEYS}


# ---------------------------------------------------------------- the figures, as text


def rate_cell(rate: dict[str, Any]) -> str:
    return f"{rate['k']} of {rate['n']} ({rate['low']:.3f} to {rate['high']:.3f})"


def count_cell(count: dict[str, Any]) -> str:
    return f"{count['k']} of {count['n']}"


def sections(first: dict[str, Any], now: dict[str, Any]) -> list[tuple[str, str, list]]:
    """Every figure as `(title, text before the table, rows)`, a row being `(label, the first
    score's cell, the current cell)`. The terminal and the report both print this."""

    def row(label: str, get: Callable[[dict], Any], fmt: Callable = rate_cell) -> tuple:
        return label, fmt(get(first)), fmt(get(now))

    def head(name: str) -> Callable[[dict], Any]:
        return lambda r: r["headline"][name]

    refused = [
        row("Strict", head("strict")),
        row("Other", head("other")),
        row("Answered", head("answered")),
        row("Refused at all (strict plus other)", head("refused_at_all")),
        row("Questions scored", lambda r: r["headline"]["n"], str),
    ]
    variants = [
        row("Strict, excluded questions counted as misses", lambda r: r["all_errors"]["strict"]),
        row(
            "Refused at all, excluded questions counted as misses",
            lambda r: r["all_errors"]["refused_at_all"],
        ),
        row("Excluded by the labellers", lambda r: r["excluded"], str),
        row("Strict, without the near copies", lambda r: r["without_near_copies"]["strict"]),
        row("Other, without the near copies", lambda r: r["without_near_copies"]["other"]),
        row("Answered, without the near copies", lambda r: r["without_near_copies"]["answered"]),
        row(
            f"Questions above the similarity threshold {ns.THRESHOLD}",
            lambda r: r["near_copies"],
            lambda c: f"{c['above']} of {c['of']} above",
        ),
    ]
    recall = [row(c, lambda r, c=c: r["recall"][c], count_cell) for c in ns.PRECEDENCE]
    baselines = []
    for name, key, router in (
        ("Refused at all", "refused_at_all", lambda r: r["headline"]["refused_at_all"]),
        ("False refusal", "false_refusal", lambda r: r["answerable"]["false_refusal"]),
    ):
        baselines += [
            row(f"{name}, router", router),
            row(
                f"{name}, baseline of trigger words", lambda r, k=key: r["baselines"]["triggers"][k]
            ),
            row(
                f"{name}, baseline of intent keywords",
                lambda r, k=key: r["baselines"]["keywords"][k],
            ),
        ]
    answerable = [
        row("Answerable questions", lambda r: r["answerable"]["n"], str),
        row("False refusal", lambda r: r["answerable"]["false_refusal"]),
        row("Wrong intent or target", lambda r: r["answerable"]["wrong"]),
    ]
    for intent in ns.INTENTS:
        for name, key in (("False refusal", "false_refusal"), ("Wrong intent or target", "wrong")):
            answerable.append(
                row(
                    f"{name}, {intent}",
                    lambda r, i=intent: r["answerable"]["per_intent"][i],
                    lambda cell, k=key: f"{cell[k]} of {cell['n']}",
                )
            )
    apart = [
        row("Labelled out_of_scope: the router returned it", lambda r: r["apart"]["out_of_scope"]),
        row("Labelled unreadable: the router returned it", lambda r: r["apart"]["unreadable"]),
    ]
    return [
        ("Questions labelled with refusal categories", REFUSED_TEXT, refused),
        ("The same questions, two variants", VARIANTS_TEXT, variants),
        ("Recall by category", RECALL_TEXT, recall),
        ("The router and the two baselines", BASELINES_TEXT, baselines),
        ("Answerable questions", ANSWERABLE_TEXT, answerable),
        ("Questions scored apart", APART_TEXT, apart),
    ]


def describe(result: Result) -> str:
    if result["route"] == "refuse":
        return "refuse " + ", ".join(result["categories"])
    if result["route"] == "answer":
        target = result.get("target")
        return " ".join(["answer", result["intent"], *([target] if target else [])])
    return result["route"]


def figure_lines(first: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """The terminal's view of `sections`: counts and intervals, never a question."""
    lines = [
        f"{label}: first {a}; now {b}"
        for _, _, rows in sections(first, now)
        for label, a, b in rows
    ]
    return [*lines, f"Misses: first {len(first['misses'])}; now {len(now['misses'])}"]


# ---------------------------------------------------------------- the report

REFUSED_TEXT = (
    "A question labelled with one to three refusal categories is *strict* when the router's "
    "primary category (the first in precedence) is in its label, *other* when the router refused "
    "and its primary category is not in the label (the default route and `unreadable` included), "
    "and *answered* when it returned any intent route. Each figure is k of n with a 95% "
    "Clopper-Pearson interval, and is agreement with the agent-authored taxonomy."
)
VARIANTS_TEXT = (
    "A question the labellers could not resolve is excluded and counted; the first two rows add "
    "the excluded questions to each denominator and to no numerator. A near copy is a question "
    "whose largest character-trigram similarity to a development question, an example of the "
    "taxonomy or a public question is above the threshold fixed in design 24.10; the count "
    "measures near copies, not shared trigger words, and the rows without them leave those "
    "questions out."
)
RECALL_TEXT = (
    "A question counts under each category of its label that its primary category matches. "
    "Counts only: a category rests on a handful of questions."
)
BASELINES_TEXT = (
    "Both baselines refuse by default, so they are compared with the router only on these two "
    "figures, on the same questions. *Trigger words*: the router's intent matcher, with a "
    "question that holds a word of the committed `baseline_triggers.txt` refused. *Intent "
    "keywords*: a question is answered if any of the router's intent patterns matches, else "
    "refused."
)
ANSWERABLE_TEXT = (
    "A question labelled with an intent is a false refusal when the router did not answer it, "
    "and a wrong intent or target when it answered something else."
)
APART_TEXT = (
    "Questions labelled `out_of_scope` or `unreadable` are scored apart: a hit is that route. "
    "They are in no figure above."
)


def build_report(
    first: dict[str, Any], now: dict[str, Any], now_router_sha256: str, grounding: str
) -> dict[str, Any]:
    """What the two documents hold: the first score, a fresh run and the fixed figures."""
    then = record_of(first)
    return {
        "provenance": PROVENANCE,
        "freeze": {
            "commit": first["freeze_sha"],
            "head_at_first_score": first["head_sha"],
            "router_sha256": {"first": first["router_sha256"], "current": now_router_sha256},
        },
        "first": then,
        "current": now,
        "current_equals_first": then == now,
        "budget": BUDGET,
        "grounding_study": grounding,
    }


def render_json(report: dict[str, Any]) -> str:
    return canonical(report)


def _miss_lines(record: dict[str, Any]) -> list[str]:
    return [
        f"- {miss['index']} ({miss['kind']}): label {describe(miss['label'])}; "
        f"router {describe(miss['router_result'])}; {json.dumps(miss['text'], ensure_ascii=False)}"
        for miss in record["misses"]
    ]


def render_markdown(report: dict[str, Any]) -> str:
    first, now, freeze, budget = (report[k] for k in ("first", "current", "freeze", "budget"))
    shas = freeze["router_sha256"]
    lines = [
        report["provenance"],
        "",
        "# Narration evaluation: the router on the held-out half",
        "",
        "Generated by `python tests/narration_evaluation.py --write` from "
        f"`{FIRST_SCORE}` and a fresh run of the router (design section 24.10); do not edit. "
        "It reports what was built and tested offline: the router of the narration layer "
        f"(`{ROUTER}`) on {first['questions']} agent-authored questions that were held out of its "
        "construction by procedure. No model was run through Referee. The counts are agreement "
        "with the agent-authored taxonomy (`tests/data/narration_eval/taxonomy.json`); they say "
        "nothing about usefulness, readability, a model's behaviour or real users' phrasing, "
        "none of which was measured.",
        "",
        "## The freeze",
        "",
        f"- Freeze commit: `{freeze['commit']}`, the last commit reachable from HEAD that "
        f"changed `{FREEZE}`.",
        f"- HEAD when the first score was taken: `{freeze['head_at_first_score']}`.",
        f"- SHA-256 of `{ROUTER}` in the freeze file: first score `{shas['first']}`, "
        f"now `{shas['current']}`.",
        "",
        "Before it routed the held-out half, `--first-score` checked with `git` that the freeze "
        "commit is an ancestor of HEAD, that every frozen file equals its content at that "
        "commit, that the held-out files equal their pins in `pins.json`, that the narration "
        "modules the router loads are frozen files of this tree and that the worktree was clean. "
        "It refuses to run when the score file exists, so the first score is taken once.",
        "",
        "Git can show that the router was frozen before it was scored. It does not show that "
        "nobody had read the half: that is a procedure, not a technical barrier. The file is in "
        "an open repository, and the questions, labels and reviews all come from one kind of "
        "agent (`tests/data/narration_eval/PROVENANCE.md` records by count who saw what). The "
        "first score is a score taken after a freeze, with that limit.",
        "",
        "## The first score beside the current score",
        "",
        "The first column is the file in git. The second is a fresh run of the router in this "
        "tree. A later change to the router is a later pull request and shows as the columns "
        "differing. "
        + (
            "In every figure, the current run equals the first score."
            if report["current_equals_first"]
            else "The current run differs from the first score in at least one figure."
        ),
    ]
    for title, text, rows in sections(first, now):
        lines += [
            "",
            f"### {title}",
            "",
            text,
            "",
            "| Figure | First score | Current |",
            "| --- | --- | --- |",
        ]
        lines += [f"| {label} | {a} | {b} |" for label, a, b in rows]
    lines += [
        "",
        f"## Every miss of the first score ({len(first['misses'])})",
        "",
        "A miss is a question that is not strict (refusal-labelled), not answered with its "
        "label's intent and target, or not returned as the route it is scored apart for. "
        "`index` counts the questions of the file from 1. The question is quoted verbatim as a "
        "JSON string, which escapes a control character.",
        "",
        *_miss_lines(first),
    ]
    if not report["current_equals_first"]:
        lines += ["", f"## Every miss of the current run ({len(now['misses'])})", ""]
        lines += _miss_lines(now)
    lines += [
        "",
        "## The budget of design 24.11",
        "",
        f"The narration tests (`{budget['command']}`) were timed by hand on Linux when this "
        "report was written, in separate runs: "
        + ", ".join(f"{seconds:.1f} s" for seconds in budget["linux_seconds"])
        + f". macOS: {budget['macos']}; that figure comes from CI. The budget is about 30 s.",
        "",
        "## The checker study",
        "",
        "`docs/grounding-study.md` measures what a closed-vocabulary checker accepts over "
        "enumerations of short texts: a checker's acceptance space, not what a model can or "
        "cannot do. No model was run for it or through Referee. Its figures, as "
        f"`docs/grounding-study.json` states them: {report['grounding_study']}",
        "",
        "## Known gaps, and what is not verified",
        "",
        "The known gaps are those of design section 24.13; this report adds none and removes "
        "none. Those that bear on the figures above:",
        "",
        "- The held-out half is a procedure, not a technical barrier, and its questions, labels "
        "and reviews come from one kind of agent. The counts are agreement with an "
        "agent-authored taxonomy, not recall on real users' phrasing.",
        "- Three questions per refusal category and five per intent rest on very little; no "
        "per-category figure should be read as a rate.",
        "- The router is not injection-proof and its twelve categories are not complete. A "
        "question answered when it should have been refused gets the fixed page, which prints "
        "every finding.",
        "",
        "Not verified: the model path has never been run with a model. Nothing here was run on "
        "macOS. That a page is byte-identical between machines is not checked until CI runs it.",
        "",
        "## Reproduce",
        "",
        "From `referee/`, with `src` and `tests` on `PYTHONPATH`:",
        "",
        "- `python tests/narration_evaluation.py` prints the current score beside the first; it "
        "refuses until the first score exists.",
        "- `python tests/narration_evaluation.py --first-score` takes the first score, once.",
        "- `python tests/narration_evaluation.py --write` writes these two documents.",
        "",
    ]
    return "\n".join(lines)


def documents(root: Path = ROOT) -> dict[Path, str]:
    """The two documents, from the first score and a fresh run (`Refusal` without the first)."""
    first = load_first(root)
    now_router = _json(root / FREEZE)["sha256"][ROUTER]
    grounding = _json(root / GROUNDING)["row5"]
    report = build_report(first, measure(root), now_router, grounding)
    markdown, twin = DOCUMENTS
    return {root / markdown: render_markdown(report), root / twin: render_json(report)}


# ---------------------------------------------------------------- command line


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path = ROOT,
    git: Git = run_git,
    loaded: Collection[Path] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--first-score", action="store_true", help="take the first score, once")
    mode.add_argument("--write", action="store_true", help="write the two documents of docs/")
    args = parser.parse_args(argv)
    try:
        if args.first_score:
            first = first_score(root, git, loaded_files() if loaded is None else loaded)
            print("\n".join(figure_lines(first, first)))
            print(f"first score written to {FIRST_SCORE}")
        elif args.write:
            written = documents(root)
            for path, text in written.items():
                path.write_bytes(text.encode("utf-8"))
                print(f"wrote {path.relative_to(root)}")
        else:
            print("\n".join(figure_lines(load_first(root), measure(root))))
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
