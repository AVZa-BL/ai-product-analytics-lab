"""The figures of the grounding study and the two documents written from them.

Everything is computed from the frozen catalogue, the loaded-word list, the checker and the
probes; nothing is random and nothing is timed. The documents hold integers and strings only.
"""

import json
from functools import cache
from pathlib import Path

from grounding_study.catalogue import FROZEN_SHA256, load_frozen
from grounding_study.checker import MAX_CITED, MAX_TEXTS, check, enumerate_texts, longest_within
from grounding_study.lexicon import (
    FUNCTION_WORDS,
    LOADED,
    VIEWS,
    is_free,
    lexicon_sha256,
    loaded_tokens,
)
from grounding_study.probes import PROBES

DOCS = Path(__file__).resolve().parents[2] / "docs"
PROVENANCE = (
    "Language-model agents wrote the code, tests, loaded-word list, probes, this document and "
    "the catalogue sentences, and every harm label; no question is involved and no human "
    "labelled a probe."
)
VIEW_NAMES = {
    "full": "the full list",
    "qualifiers": "qualifiers and digits",
    "digits": "digits only",
}
LISTED_ALONE = 12  # a view with more free sentences gets its per-sentence counts in the JSON only


@cache
def frozen() -> tuple[str, dict[str, str]]:
    return load_frozen()


def study(sentences: dict[str, str], as_of: str) -> dict:
    free = {v: [i for i, t in sentences.items() if is_free(t, v)] for v in VIEWS}
    loaded = {i: list(dict.fromkeys(loaded_tokens(t, "full"))) for i, t in sentences.items()}
    fewest = min(len(words) for words in loaded.values())
    verdicts = [{v: check(p.text, p.cited, sentences, v) for v in VIEWS} for p in PROBES]
    admitted = {v: sum(row[v] is None for row in verdicts) for v in VIEWS}
    row5 = (
        f"{len(free['full'])} of the {len(sentences)} catalogue sentences contain none of the "
        f"study's loaded words under its full list and {len(free['digits'])} under the "
        f"digits-only ablation, and the checker admitted {admitted['full']} of {len(PROBES)} "
        "hand-written harmful probes under the full list "
        f"({admitted['qualifiers']} and {admitted['digits']} of {len(PROBES)} under the "
        "qualifiers-and-digits and digits-only ablations) (docs/grounding-study.md)."
    )
    return {
        "what": "a closed-vocabulary checker over bounded enumerations of short texts, and how "
        "many catalogue sentences hold none of a list of loaded words",
        "provenance": PROVENANCE,
        "no_model": "No model was run through Referee or for this study; the figures describe a "
        "checker's acceptance space, not what a model can or cannot do; harm is not computed.",
        "command": "python tests/grounding_study/run.py",
        "catalogue": {"as_of": as_of, "sha256": FROZEN_SHA256, "sentences": len(sentences)},
        "lexicon": {
            "sha256": lexicon_sha256(),
            "words": sum(len(words) for words in LOADED.values()),
            "categories": {name: sorted(words) for name, words in LOADED.items()},
            "views": {name: list(categories) for name, categories in VIEWS.items()},
        },
        "function_words": list(FUNCTION_WORDS),
        "free": {v: {"count": len(ids), "ids": ids} for v, ids in free.items()},
        "fewest_loaded": {
            "count": fewest,
            "ids": [i for i, words in loaded.items() if len(words) == fewest],
        },
        "sentences": [
            {"id": i, "loaded": loaded[i], "free_under": [v for v in VIEWS if i in free[v]]}
            for i in sentences
        ],
        "enumeration": {v: enumerate_texts(sentences, v) for v in VIEWS},
        "probes": {
            "total": len(PROBES),
            "admitted": admitted,
            "rows": [
                {"cited": list(p.cited), "text": p.text, "harm": p.harm, "verdict": row}
                for p, row in zip(PROBES, verdicts, strict=True)
            ],
        },
        "row5": row5,
    }


def render_json(result: dict) -> str:
    return json.dumps(result, indent=1) + "\n"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _enumeration(name: str, found: dict) -> list[str]:
    free, size, length = found["free"], found["vocabulary"], found["max_length"]
    lines = [f"### {name}: {len(free)} free sentences", ""]
    if not free:
        longest, total = longest_within(size, MAX_TEXTS)
        counts = ", ".join(f"{size**n:,}" for n in range(1, longest))
        counts += f" and {size**longest:,}"
        return lines + [
            "No sentence is free, so no cited sentence adds a word to the vocabulary: whatever is "
            f"cited, the checker admits exactly the texts made of the {size} function words, which "
            "hold no word that a sentence adds. "
            f"There are {size}^n of them with n words, for every n; "
            f"for 1 to {longest} words, the longest within the bound of {MAX_TEXTS:,} texts in "
            f"all, they number {counts} ({total:,} in all). The rule gives these counts; no text "
            "was enumerated.",
            "",
        ]
    lines += [
        f"Vocabulary of {size:,} words: the {len(FUNCTION_WORDS)} function words and "
        f"{size - len(FUNCTION_WORDS):,} words of the free sentences. Every text of 1 to {length} "
        f"words was enumerated, {found['texts']:,} in all (the bound is {MAX_TEXTS:,} texts). The "
        "counts are of admitted texts that hold at least one word that is no function word.",
        "",
    ]
    lines += _table(
        ["words", "texts", "function words only", f"some cited set of 1 to {MAX_CITED}"],
        [
            [
                str(n),
                f"{size**n:,}",
                f"{found['function_words_only'][n - 1]:,}",
                f"{found['any'][n - 1]:,}",
            ]
            for n in range(1, length + 1)
        ],
    )
    if len(free) > LISTED_ALONE:
        return lines + ["", "The counts for each sentence cited alone are in the JSON.", ""]
    return (
        lines
        + [""]
        + _table(
            ["cited alone"] + [f"{n} words" for n in range(1, length + 1)],
            [[f"`{i}`"] + [f"{c:,}" for c in found["alone"][i]] for i in free],
        )
        + [""]
    )


def render_markdown(result: dict, sentences: dict[str, str]) -> str:
    free, lexicon, probes = result["free"], result["lexicon"], result["probes"]
    total, admitted = result["catalogue"]["sentences"], probes["admitted"]
    out = [
        PROVENANCE,
        "",
        "# Grounding study: what a closed-vocabulary checker accepts",
        "",
        "Generated by `python tests/grounding_study/run.py` from the frozen catalogue (design "
        "section 24.12); do not edit. No model was run through Referee, and none was run for "
        "this study. The figures describe a checker's acceptance space, not what a model can or "
        "cannot do. The checker tests words, not meaning: harm is not computed, by it or by "
        "anything here. The model-written channel is not shipped, because the user decided that "
        "the model path selects and never writes; this study does not decide that.",
        "",
        "## The figures",
        "",
        f"> {result['row5']}",
        "",
        f"- Bound of the first two figures: the {total} sentences, frozen as of "
        f"{result['catalogue']['as_of']} (SHA-256 `{result['catalogue']['sha256']}`), against "
        f"the loaded-word list of {lexicon['words']} words (SHA-256 `{lexicon['sha256']}`), "
        "and, for the second figure, against the tokens that hold a digit. Under the full list "
        "every sentence holds at least "
        f"{result['fewest_loaded']['count']} distinct loaded tokens, so the first figure would "
        "not move if one word were taken off the list.",
        f"- Bound of the third: {probes['total']} probes written by hand, put to the checker with "
        "the full list. With the list cut to qualifiers and digits it admits "
        f"{admitted['qualifiers']} of {probes['total']}, and with digits only "
        f"{admitted['digits']} of {probes['total']}. Under the full list {free['full']['count']} "
        "sentences are free, so no cited sentence adds a word and only texts of function words "
        f"are admitted: that the checker admitted {admitted['full']} follows from that and from "
        "each probe holding a word outside the function words, by construction, and is not a "
        "finding that it catches harm, and the probes are not independent of the list.",
        "",
        "## The loaded words",
        "",
        "A sentence is free under a view when none of its tokens is loaded under it. A token "
        "is a chunk between spaces and hyphens, in lower case, without the punctuation at its"
        " ends. A token that holds a digit (`5%`, the `007` of `RES-007`) is loaded under "
        "every view. One that holds a symbol and no digit (`min_duration_days`, the inner dot"
        " of `design.start_utc`) is loaded under the full list, where every sentence is "
        "loaded anyway and the count is 0 whichever way a symbol is treated, and not under "
        "the two ablations, so that the digits-only ablation loads digits and nothing else. "
        "The list holds the words that carry a decision, a condition, a negation, a modal, a "
        "limit, a quantity, a comparison, a certainty, a cause, a severity or verdict, a "
        "unit, a position, an arm or an ordinal, in the folded form of the tokeniser (a "
        "trailing plural s off). It is one agent's judgement, made with the sentences in view"
        " and read once against those that the qualifiers view left free, after which two of "
        "the words added took that count from 11 to 8. The count of free sentences is a "
        "property of this list, and the two ablations show how much it moves. A phrase such "
        "as `up to` or `at least` is not recognised, only its words.",
        "",
        *(
            f"- {name} ({len(words)}): {' '.join(words)}"
            for name, words in lexicon["categories"].items()
        ),
        "",
    ]
    out += _table(
        ["view", "categories", f"free of {total}"],
        [
            [VIEW_NAMES[v], ", ".join(lexicon["views"][v]) or "none", str(free[v]["count"])]
            for v in VIEWS
        ],
    )
    out += [
        "",
        "Fewest loaded tokens under the full list: "
        + ", ".join(f"`{i}`" for i in result["fewest_loaded"]["ids"])
        + ".",
        "",
        "Free under qualifiers and digits:",
        "",
        *(f"- `{i}`: {sentences[i]}" for i in free["qualifiers"]["ids"]),
        "",
        "Free under digits only (the text is in the last table): "
        + ", ".join(f"`{i}`" for i in free["digits"]["ids"]),
        "",
        "## The checker",
        "",
        "A text is admitted for a cited set of one or two sentences when it holds no digit or "
        "symbol (neither can be typed into model text in this design) and each of its words is a "
        "function word or a word of a cited sentence that is free under the view; the words of a "
        "cited sentence that is not free add nothing, and neither do the digit and symbol tokens "
        "of one that is. The "
        f"{len(FUNCTION_WORDS)} function words: "
        + ", ".join(f"`{w}`" for w in FUNCTION_WORDS)
        + ".",
        "",
        "## What it admits, enumerated",
        "",
        "The checker tests each word alone, so what it admits is every sequence of the permitted "
        "words, sense or nonsense. The counts say how many; they do not reach what a model writes. "
        "The vocabularies are in the folded form of the tokeniser, and the digits-only one holds "
        "artefacts of the trailing-s fold (`does`, `passes`, `reaches` and `re-check` become "
        "`doe`, `passe`, `reache` and `re`): a text is folded the same way, so the checker takes "
        "`does` for `doe`, and the sizes count folded forms.",
        "",
    ]
    for v in VIEWS:
        out += _enumeration(VIEW_NAMES[v], result["enumeration"][v])
    out += [
        "## The probes",
        "",
        f"{probes['total']} texts, each citing the sentence it distorts and each with a one-line "
        "reason it is harmful. They are probes, not a sample, and they were written by the agent "
        "that wrote the list and the checker, so they are not independent of either. The reason "
        "for each rejection is in the JSON.",
        "",
    ]
    out += _table(
        ["#", "cites", "text", "why it is harmful", *VIEW_NAMES.values()],
        [
            [
                str(n),
                ", ".join(f"`{i}`" for i in row["cited"]),
                row["text"],
                row["harm"],
                *("admitted" if row["verdict"][v] is None else "rejected" for v in VIEWS),
            ]
            for n, row in enumerate(probes["rows"], 1)
        ],
    )
    out += [
        "",
        "## The sentences",
        "",
        "Free under: the views under which the sentence holds no loaded token (`qualifiers` is "
        "qualifiers and digits, `digits` is digits only). Loaded: its distinct loaded tokens "
        "under the full list, in order.",
        "",
    ]
    out += _table(
        ["ID", "sentence", "free under", "loaded"],
        [
            [
                f"`{row['id']}`",
                sentences[row["id"]],
                ", ".join(row["free_under"]) or "none",
                ", ".join(f"`{t}`" for t in row["loaded"]),
            ]
            for row in result["sentences"]
        ],
    )
    out += [
        "",
        "## Not verified",
        "",
        "- That any model can or cannot restate a sentence: none was run, and the enumeration is "
        "of words in any order.",
        "- That the list is right: another list gives other counts, and no one but its author has "
        "read it. The probes are one author's too.",
        "- That the 81 sentences are the catalogue of today: they are frozen, and a test says "
        "when the rules have moved on without failing.",
        "",
    ]
    return "\n".join(out)


def documents() -> dict[Path, str]:
    as_of, sentences = frozen()
    result = study(sentences, as_of)
    return {
        DOCS / "grounding-study.md": render_markdown(result, sentences),
        DOCS / "grounding-study.json": render_json(result),
    }
