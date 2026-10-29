"""Scoring, label resolution and lint for the narration router's evaluation set (design 24.10).

Pure Python and offline. A question record is `{id, text, fixture, stratum, label}`; the stratum
is the writer's intent (`single:<category>`, `compound` or `answerable:<intent>`) and the label is
what the labellers resolved to. A label, and the result of a router, are dicts:

    {"route": "refuse", "categories": [...]}        at least one category
    {"route": "answer", "intent": ..., "target": ...}
    {"route": "out_of_scope"}  or  {"route": "unreadable"}

A baseline that refuses by default returns {"route": "out_of_scope"}, the default route.

The lint never prints or returns the text of a question: its output is counts, similarity numbers
and question ids. Command line (from `referee/`):

    python tests/narration_scoring.py lint development QUESTIONS.json
    python tests/narration_scoring.py lint heldout QUESTIONS.json --dev DEVELOPMENT.json
    python tests/narration_scoring.py pins [PINS.json]
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from pathlib import Path
from typing import Any, TypedDict

from scipy.stats import beta

DATA = Path(__file__).resolve().parent / "data" / "narration_eval"
PINS = DATA / "pins.json"
THRESHOLD = 0.6  # similarity above which a held-out question counts as a near copy (24.10)

TAXONOMY: dict[str, Any] = json.loads((DATA / "taxonomy.json").read_text(encoding="utf-8"))
PRECEDENCE: tuple[str, ...] = tuple(TAXONOMY["precedence"])
INTENTS: tuple[str, ...] = tuple(TAXONOMY["intents"])
FIXTURES: tuple[str, ...] = tuple(TAXONOMY["fixtures"])
REFUSAL_WORDS: tuple[str, ...] = tuple(TAXONOMY["refusal_sounding_words"])

# 24.10: single refusals per category, compound questions, answerable questions per intent.
STRATA = {
    "development": {"single": 5, "compound": 12, "answerable": 6},
    "heldout": {"single": 3, "compound": 8, "answerable": 5},
}
MIN_GOLDEN_PERCENT = 80
MIN_WHY = 4
RULE_ID = re.compile(r"[A-Z]{3}-\d{3}")

Label = dict[str, Any]


class Question(TypedDict):
    id: str
    text: str
    fixture: str
    stratum: str
    label: Label | None


class Item(TypedDict):
    """One scored question: its resolved label and what a router (or a baseline) returned."""

    id: str
    label: Label
    result: Label


# ---------------------------------------------------------------- Clopper-Pearson


def clopper_pearson(k: int, n: int) -> tuple[float, float]:
    """The exact 95% interval for k successes in n trials; (0, 1) when n is 0."""
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return 0.0, 1.0
    tail = 0.025
    low = 0.0 if k == 0 else float(beta.ppf(tail, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - tail, k + 1, n - k))
    return low, high


def rate(k: int, n: int) -> dict[str, Any]:
    low, high = clopper_pearson(k, n)
    return {"k": k, "n": n, "low": low, "high": high}


# ---------------------------------------------------------------- label resolution


def agree(a: Label, b: Label) -> Label | None:
    """What two labels agree on, or None. The route `none` is `out_of_scope`.

    Two refusals agree on the categories they share (the label is that intersection, in the
    order of precedence); two answers agree when intent and target are equal; two routes
    without detail agree when they are the same.
    """
    a, b = _canonical(a), _canonical(b)
    if a["route"] != b["route"]:
        return None
    if a["route"] == "refuse":
        shared = sorted(set(a["categories"]) & set(b["categories"]), key=PRECEDENCE.index)
        return {"route": "refuse", "categories": shared} if shared else None
    if a["route"] == "answer":
        if (a["intent"], a.get("target")) != (b["intent"], b.get("target")):
            return None
        return {"route": "answer", "intent": a["intent"], "target": a.get("target")}
    return {"route": a["route"]}


def resolve(first: Label, second: Label, third: Label | None = None) -> tuple[str, Label | None]:
    """The status and label of a question from its labellers; the writer's intent is no vote.

    `agreed`: the first two agree. `needs_third`: they do not and there is no third label.
    `third`: the third agrees with exactly one of them, and the label is that agreement.
    `excluded`: the third agrees with both or with neither (the label is None).
    """
    agreed = agree(first, second)
    if agreed is not None:
        return "agreed", agreed
    if third is None:
        return "needs_third", None
    with_first, with_second = agree(third, first), agree(third, second)
    if (with_first is None) == (with_second is None):
        return "excluded", None
    return "third", with_first if with_first is not None else with_second


def _canonical(label: Label) -> Label:
    return {"route": "out_of_scope"} if label["route"] == "none" else label


def valid_label(label: Any) -> bool:
    """A resolved label: a known route, one to three distinct categories, a rule-shaped target."""
    if not isinstance(label, dict):
        return False
    route = label.get("route")
    if route == "refuse":
        categories = label.get("categories")
        return (
            isinstance(categories, list)
            and 1 <= len(categories) <= 3
            and all(c in PRECEDENCE for c in categories)
            and len(set(categories)) == len(categories)
        )
    if route == "answer":
        intent, target = label.get("intent"), label.get("target")
        if intent == "explain_finding":
            return isinstance(target, str) and RULE_ID.fullmatch(target) is not None
        return intent in INTENTS and target is None
    return route in ("out_of_scope", "unreadable")


# ---------------------------------------------------------------- the partition of 24.10


def primary(categories: Iterable[str]) -> str:
    """The first category in precedence: the only one of a router's output that is scored."""
    return min(categories, key=PRECEDENCE.index)


def classify(label: Label, result: Label) -> str:
    """The cell of one refusal-labelled question: strict, other, answered, apart_hit, apart_miss.

    A refusal result without categories is not valid: for a question labelled with categories it
    raises ValueError (from `primary`) and is not scored as `other`.
    """
    if label["route"] in ("out_of_scope", "unreadable"):
        return "apart_hit" if result["route"] == label["route"] else "apart_miss"
    if result["route"] == "answer":
        return "answered"
    if result["route"] == "refuse" and primary(result["categories"]) in label["categories"]:
        return "strict"
    return "other"


def _triple(items: Sequence[Item], excluded: int = 0) -> dict[str, Any]:
    """Strict, other and answered of the category-labelled questions, each k of n.

    `excluded` questions are added to every n and to no k.
    """
    cells = Counter(
        classify(i["label"], i["result"]) for i in items if i["label"]["route"] == "refuse"
    )
    n = cells["strict"] + cells["other"] + cells["answered"] + excluded
    return {
        "n": n,
        "strict": rate(cells["strict"], n),
        "other": rate(cells["other"], n),
        "answered": rate(cells["answered"], n),
        "refused_at_all": rate(cells["strict"] + cells["other"], n),
    }


def score(
    items: Sequence[Item], excluded: int = 0, near_copies: Collection[str] = ()
) -> dict[str, Any]:
    """Every figure of 24.10 for a router or a baseline over the resolved questions.

    `headline` is the triple; `all_errors` has only `strict` and `refused_at_all`, with the
    `excluded` questions in each denominator and in no numerator (the other two figures would
    look better, not worse, there); `without_near_copies` is the triple without the question ids
    above the similarity threshold. Questions labelled out_of_scope or unreadable are in `apart`
    and in no headline. `recall` counts a question under each label category its primary category
    matches. `answerable` has the false refusals and the answers of the wrong intent or target,
    in all and per intent.
    """
    apart = {}
    for route in ("out_of_scope", "unreadable"):
        mine = [i for i in items if i["label"]["route"] == route]
        apart[route] = rate(sum(i["result"]["route"] == route for i in mine), len(mine))

    recall = {c: {"k": 0, "n": 0} for c in PRECEDENCE}
    for item in items:
        label, result = item["label"], item["result"]
        if label["route"] != "refuse":
            continue
        first = primary(result["categories"]) if result["route"] == "refuse" else None
        for category in label["categories"]:
            recall[category]["n"] += 1
            recall[category]["k"] += int(first == category)

    per_intent = {intent: {"n": 0, "false_refusal": 0, "wrong": 0} for intent in INTENTS}
    for item in items:
        label, result = item["label"], item["result"]
        if label["route"] != "answer":
            continue
        cell = per_intent[label["intent"]]
        cell["n"] += 1
        if result["route"] != "answer":
            cell["false_refusal"] += 1
        elif (result["intent"], result.get("target")) != (label["intent"], label.get("target")):
            cell["wrong"] += 1
    n = sum(c["n"] for c in per_intent.values())

    near = set(near_copies)
    all_errors = _triple(items, excluded)
    return {
        "headline": _triple(items),
        "all_errors": {name: all_errors[name] for name in ("strict", "refused_at_all")},
        "without_near_copies": _triple([i for i in items if i["id"] not in near]),
        "apart": apart,
        "recall": recall,
        "answerable": {
            "n": n,
            "false_refusal": rate(sum(c["false_refusal"] for c in per_intent.values()), n),
            "wrong": rate(sum(c["wrong"] for c in per_intent.values()), n),
            "per_intent": per_intent,
        },
    }


# ---------------------------------------------------------------- similarity


def normalise(text: str) -> str:
    """The router's normalisation (24.8): NFKC of the case-folded NFKC text, spaces collapsed."""
    text = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text).casefold())
    spaced = "".join(
        " " if c in "\t\n\r" or unicodedata.category(c) in ("Zs", "Zl", "Zp") else c for c in text
    )
    return re.sub(" +", " ", spaced).strip()


def _trigrams(text: str) -> set[str]:
    text = normalise(text)
    return {text[i : i + 3] for i in range(len(text) - 2)}


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def trigram_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the sets of character trigrams of two normalised texts."""
    return _jaccard(_trigrams(a), _trigrams(b))


def max_similarities(texts: Sequence[str], reference: Sequence[str]) -> list[float]:
    """For each text, its largest trigram similarity to any reference text."""
    sets = [_trigrams(r) for r in reference]
    return [max(_jaccard(_trigrams(t), s) for s in sets) for t in texts]


def reference_texts(development: Sequence[Question]) -> list[str]:
    """What a held-out question is compared with: development questions, the examples of the
    taxonomy (24.8's table and the intents) and the three public questions."""
    examples = [
        entry["example"]
        for group in (TAXONOMY["refusal_categories"], TAXONOMY["routes"], TAXONOMY["intents"])
        for entry in group.values()
        if "example" in entry
    ]
    public = json.loads((DATA / "public_questions.json").read_text(encoding="utf-8"))["questions"]
    return [q["text"] for q in development] + examples + [q["text"] for q in public]


# ---------------------------------------------------------------- lint


def lint(
    questions: Sequence[Question], half: str, reference: Sequence[str] | None = None
) -> dict[str, Any]:
    """The checks of 24.10 on one question file; `problems` start with a code, then ids or counts.

    `reference` (the development questions and examples, see `reference_texts`) is required for
    the held-out half, which gets its similarity numbers. Nothing returned holds question text.
    """
    if half == "heldout" and not reference:
        raise ValueError("the held-out half needs the reference texts")
    wanted = STRATA[half]
    expected = {f"single:{c}": wanted["single"] for c in PRECEDENCE}
    expected["compound"] = wanted["compound"]
    expected |= {f"answerable:{i}": wanted["answerable"] for i in INTENTS}

    problems = []
    found = Counter(q["stratum"] for q in questions)
    problems += [
        f"strata: {q['id']} has an unknown stratum"
        for q in questions
        if q["stratum"] not in expected
    ]
    problems += [
        f"strata: {stratum} has {found[stratum]} questions, expected {count}"
        for stratum, count in expected.items()
        if found[stratum] != count
    ]
    problems += [
        f"fixture: {q['id']} names no known fixture"
        for q in questions
        if q["fixture"] not in FIXTURES
    ]
    golden = sum(q["fixture"] == "golden" for q in questions)
    if golden * 100 < MIN_GOLDEN_PERCENT * len(questions):
        problems.append(
            f"golden: {golden} of {len(questions)} name golden, under {MIN_GOLDEN_PERCENT}%"
        )

    why = sum(
        q["stratum"] == "answerable:explain_finding" and "why" in _words(q["text"])
        for q in questions
    )
    if why < MIN_WHY:
        problems.append(f"why: {why} why-explanations, at least {MIN_WHY} needed")
    sounding = sum(
        q["stratum"].startswith("answerable:") and _has_refusal_word(q["text"]) for q in questions
    )
    if half == "development" and sounding == 0:
        problems.append("refusal_words: no answerable question holds a refusal-sounding word")

    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    for q in questions:
        if q["id"] in seen_ids:
            problems.append(f"ids: {q['id']} repeats an id")
        if normalise(q["text"]) in seen_texts:
            problems.append(f"unique: {q['id']} repeats an earlier question")
        if q["label"] is not None and not valid_label(q["label"]):
            problems.append(f"label: {q['id']} has an invalid label")
        seen_ids.add(q["id"])
        seen_texts.add(normalise(q["text"]))

    similarity = max_similarities([q["text"] for q in questions], reference) if reference else None
    return {
        "half": half,
        "questions": len(questions),
        "problems": problems,
        "golden": golden,
        "why_explanations": why,
        "answerable_with_refusal_word": sounding,
        "max_similarity": similarity,
        "above_threshold": None if similarity is None else sum(s > THRESHOLD for s in similarity),
    }


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", normalise(text))


def _has_refusal_word(text: str) -> bool:
    return any(word.startswith(w) for word in _words(text) for w in REFUSAL_WORDS)


def format_lint(report: dict[str, Any]) -> str:
    """The report as lines of numbers, ids and codes."""
    lines = [
        f"half: {report['half']}",
        f"questions: {report['questions']}",
        f"problems: {len(report['problems'])}",
        *report["problems"],
        f"golden: {report['golden']} of {report['questions']}",
        f"why explanations: {report['why_explanations']}",
        f"answerable with a refusal-sounding word: {report['answerable_with_refusal_word']}",
    ]
    if report["max_similarity"] is not None:
        lines.append("largest trigram similarity to a development question or example, by index:")
        lines += [f"{i} {s:.3f}" for i, s in enumerate(report["max_similarity"], 1)]
        lines.append(f"above {THRESHOLD}: {report['above_threshold']} of {report['questions']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- pinned hashes


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_pins(pins_path: Path = PINS) -> list[str]:
    """Problems with a pins file: `{path relative to the file: SHA-256 hex digest}` per file."""
    pins_path = Path(pins_path)
    if not pins_path.is_file():
        return [f"pins: {pins_path} is missing"]
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    problems = [] if pins else ["pins: no file is pinned"]
    for name, digest in pins.items():
        path = pins_path.parent / name
        if not path.is_file():
            problems.append(f"pins: {name} is missing")
        elif sha256_file(path) != digest:
            problems.append(f"pins: {name} differs from its pin")
    return problems


# ---------------------------------------------------------------- command line


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    lint_parser = commands.add_parser("lint")
    lint_parser.add_argument("half", choices=sorted(STRATA))
    lint_parser.add_argument("questions", type=Path)
    lint_parser.add_argument("--dev", type=Path, help="development questions, for held-out")
    pins_parser = commands.add_parser("pins")
    pins_parser.add_argument("pins", type=Path, nargs="?", default=PINS)
    args = parser.parse_args(argv)

    if args.command == "pins":
        problems = check_pins(args.pins)
        print("\n".join(problems) or "pins match")
        return 1 if problems else 0

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    reference = None
    if args.half == "heldout":
        if args.dev is None:
            parser.error("lint heldout needs --dev")
        reference = reference_texts(json.loads(args.dev.read_text(encoding="utf-8")))
    report = lint(questions, args.half, reference)
    print(format_lint(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
