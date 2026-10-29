"""The grounding study (design section 24.12): its parts, and that its documents are its output.

Every test is in the study tier (`pytest -m study tests/grounding_study`); the default run
collects none of them. The numbers in the cases are worked out by hand, not read from the study.
"""

import hashlib
import os
import re
import subprocess
import sys
from itertools import combinations, product
from pathlib import Path
from types import SimpleNamespace

import pytest

import referee
from grounding_study import catalogue, lexicon, run, study
from grounding_study.checker import check, enumerate_texts
from grounding_study.probes import PROBES, Probe

pytestmark = pytest.mark.study

FW = len(lexicon.FUNCTION_WORDS)


@pytest.fixture(scope="module")
def sentences() -> dict[str, str]:
    return study.frozen()[1]


# --- The tokeniser and the list --------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "folded"),
    [
        ("sizes", "size"),
        ("tabs", "tab"),  # four letters: the shortest word that folds
        ("has", "has"),  # three letters: left alone
        ("less", "less"),
        ("status", "status"),
        ("this", "this"),
        ("arm's", "arm"),
        ("players'", "player"),
        ("'quoted'", "quoted"),
    ],
)
def test_fold_takes_off_a_plural_s_and_a_possessive_and_nothing_else(word, folded) -> None:
    assert lexicon.fold(word) == folded


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sizes of the ARMS", ["size", "of", "the", "arm"]),
        (
            '(a [fault]), "in"; assignment: really!?',
            ["a", "fault", "in", "assignment", "really"],
        ),
        ("week-by-week - part-way", ["week", "by", "week", "part", "way"]),
        ("5%. min_duration_days e.g. RES-007", ["5%", "min_duration_days", "e.g", "res", "007"]),
        ("x1 a.b ?!", ["x1", "a.b"]),
        ("' ''", []),
    ],
)
def test_the_tokeniser_splits_folds_and_keeps_a_marker_whole(text, expected) -> None:
    assert lexicon.tokens(text) == expected


def test_every_entry_is_a_fixed_point_of_the_fold_and_no_word_is_listed_twice() -> None:
    loaded = [word for words in lexicon.LOADED.values() for word in words]
    for word in (*loaded, *lexicon.FUNCTION_WORDS):
        assert re.fullmatch(r"[a-z']+", word) and lexicon.fold(word) == word, word
    assert len(set(loaded)) == len(loaded)
    assert not set(loaded) & set(lexicon.FUNCTION_WORDS)


QUALIFIERS = {"negation", "condition", "limiter", "modal"}
CATEGORIES = QUALIFIERS | {"decision", "quantity", "comparison", "certainty", "cause", "verdict"}
CATEGORIES |= {"unit", "position", "arm", "ordinal"}
VIEWS = {"full": CATEGORIES, "qualifiers": QUALIFIERS, "digits": set()}


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_a_word_is_loaded_under_the_views_that_hold_its_category(view, category) -> None:
    word = lexicon.LOADED[category][0]

    assert (word in lexicon.loaded_tokens(f"the {word}", view)) == (category in VIEWS[view])


@pytest.mark.parametrize("view", list(lexicon.VIEWS))
@pytest.mark.parametrize(
    ("token", "symbol_only"),
    [("5%", False), ("x1", False), ("0", False), ("9", False), ("a.b", True), ("a_b", True)],
)
def test_a_digit_token_is_loaded_under_every_view_and_a_symbol_alone_under_the_full_list_only(
    view, token, symbol_only
) -> None:
    assert lexicon.is_free(f"purple {token}", view) == (symbol_only and view != "full")


@pytest.mark.parametrize(
    ("sentence_id", "free_under"),
    [
        ("RES-001.do.1", ["digits"]),  # Do not read the effect.
        ("RES-012.do.1", ["qualifiers", "digits"]),  # Check how exposure is triggered.
        ("RES-012.why.3", []),  # ... of DES-007.
        ("RES-008.do.1", []),  # 5% and 10%
    ],
)
def test_the_sentences_worked_by_hand(sentences, sentence_id, free_under) -> None:
    views = [v for v in lexicon.VIEWS if lexicon.is_free(sentences[sentence_id], v)]

    assert views == free_under


# --- The frozen catalogue ---------------------------------------------------------------------


def test_the_frozen_file_is_the_pinned_one_in_its_format_with_81_sentences() -> None:
    as_of, frozen = study.frozen()

    assert as_of == "8a7119b"
    kinds = [re.fullmatch(r"RES-\d{3}\.(title|why|do)(\.\d+)?", i).group(1) for i in frozen]
    assert [kinds.count(k) for k in ("title", "why", "do")] == [9, 32, 40]
    assert catalogue.FROZEN.read_text() == catalogue.frozen_text(frozen, as_of)


def test_a_changed_file_is_refused(tmp_path) -> None:
    changed = tmp_path / "catalogue.json"
    changed.write_text(catalogue.FROZEN.read_text().replace("Do not", "Do"))

    with pytest.raises(ValueError, match="SHA-256 differs"):
        catalogue.load_frozen(changed)


def test_the_live_catalogue_numbers_and_splits_sentences_as_section_24_4_does() -> None:
    rule = SimpleNamespace(
        id="XYZ-001",
        title="Title",
        why_it_matters="One. Two! Three? Four. five. x.Y Z.  Six",
        remediation="Do this. e.g. that",
    )

    assert catalogue.live_catalogue([rule]) == {
        "XYZ-001.title": "Title",
        "XYZ-001.why.1": "One.",
        "XYZ-001.why.2": "Two!",
        "XYZ-001.why.3": "Three?",
        "XYZ-001.why.4": "Four. five. x.Y Z.",
        "XYZ-001.why.5": "Six",
        "XYZ-001.do.1": "Do this. e.g. that",
    }


def test_differences_name_what_is_missing_from_a_side_or_worded_otherwise() -> None:
    same = {"a": "1", "b": "2"}
    assert catalogue.differences(same, dict(same)) == []
    assert catalogue.differences(
        {**same, "f": "x"}, {"a": "1", "b": "3", "c": "4", "d": "5", "e": "6"}
    ) == list("bcdef")
    assert catalogue.differences({"a": "1"}, {}) == ["a"]


def test_the_results_rules_have_not_moved_from_the_frozen_catalogue(sentences) -> None:
    """Informational: a rule edit skips this with a message and does not turn the job red."""
    moved = catalogue.differences(sentences, catalogue.live_catalogue())
    if moved:
        pytest.skip(
            f"the rules differ from the catalogue frozen as of {study.frozen()[0]} in "
            f"{', '.join(moved)}: run `python tests/grounding_study/run.py --refreeze AS_OF`, "
            "put the SHA-256 it prints in catalogue.FROZEN_SHA256, and run run.py again"
        )


# --- The checker ------------------------------------------------------------------------------

REJECT_CITES = "cites no sentence or more than two"


@pytest.mark.parametrize(
    ("text", "cited", "view", "reason"),
    [
        ("Exposure is triggered.", ["RES-012.do.1"], "qualifiers", None),
        ("EXPOSURES ARE TRIGGERED", ["RES-012.do.1"] * 3, "digits", None),
        ("It is the, and that.", ["RES-001.do.1"], "full", None),
        ("Exposure is triggered.", ["RES-012.do.1"], "full", "'exposure'"),
        ("Rerun the experiment.", ["RES-012.do.1"], "qualifiers", "'rerun'"),
        ("Read the effect.", ["RES-001.do.1"], "qualifiers", "'read'"),
        ("Read the effect.", ["RES-001.do.1"], "digits", None),
        (
            "Fix the cause and check how exposure is triggered.",
            ["RES-012.do.1"],
            "qualifiers",
            "'fix'",
        ),
        (
            "Fix the cause and check how exposure is triggered.",
            ["RES-012.do.1", "RES-001.do.4"],
            "qualifiers",
            None,
        ),
        ("Exposure is 5.", ["RES-012.do.1"], "qualifiers", "digit or a symbol"),
        ("Exposure_is triggered", ["RES-012.do.1"], "qualifiers", "digit or a symbol"),
        ("Exposure is triggered 5", ["RES-012.do.1"], "qualifiers", "digit or a symbol"),
        ("  .  ", ["RES-012.do.1"], "qualifiers", "holds no word"),
        ("It is the.", [], "full", REJECT_CITES),
        ("It is the.", ["RES-001.do.1", "RES-001.do.2", "RES-001.do.3"], "full", REJECT_CITES),
    ],
)
def test_the_checker_admits_function_words_and_the_words_of_cited_free_sentences_only(
    sentences, text, cited, view, reason
) -> None:
    verdict = check(text, cited, sentences, view)

    assert (verdict is None) if reason is None else (reason in verdict)


# --- The enumeration --------------------------------------------------------------------------

TOY = {
    "T.1": "Purple ducks sing.",
    "T.2": "Green frogs swim.",
    "T.3": "Red cats purr, e.g.",  # free under the view, though it holds a symbol: no word of it
    "T.4": "Do not swim.",  # not free: it holds `not`
}
VIEW = "qualifiers"
FREE = ("T.1", "T.2", "T.3")
ADDED = ["purple", "duck", "sing", "green", "frog", "swim", "red", "cat", "purr"]
SIZE = FW + len(ADDED)
PAIRS = list(combinations(FREE, 2))


def brute_force(n: int) -> dict:
    """Every text of n words, put to `check` once for each cited set of free sentences."""
    counts = {i: 0 for i in FREE} | {"any": 0, "function_words_only": 0}
    for words in product([*lexicon.FUNCTION_WORDS, *ADDED], repeat=n):
        text = " ".join(words)
        if all(word in lexicon.FUNCTION_WORDS for word in words):
            counts["function_words_only"] += 1
            continue
        for i in FREE:
            counts[i] += check(text, [i], TOY, VIEW) is None
        counts["any"] += any(check(text, pair, TOY, VIEW) is None for pair in PAIRS)
    return counts


def test_the_enumeration_counts_what_the_checker_admits_in_a_toy_catalogue() -> None:
    found = enumerate_texts(TOY, VIEW, max_texts=SIZE + SIZE**2 + SIZE**3)

    assert (found["free"], found["vocabulary"], found["max_length"]) == (list(FREE), SIZE, 3)
    assert found["texts"] == SIZE + SIZE**2 + SIZE**3
    for n in (1, 2):
        expected = brute_force(n)
        assert found["function_words_only"][n - 1] == expected["function_words_only"]
        assert found["any"][n - 1] == expected["any"]
        for i in FREE:
            assert found["alone"][i][n - 1] == expected[i]
    # By hand: each sentence adds three words, a pair six, and a text mixing the words of all
    # three sentences is admitted for no pair (inclusion and exclusion over the three pairs).
    for n in (1, 2, 3):
        assert found["function_words_only"][n - 1] == FW**n
        assert [found["alone"][i][n - 1] for i in FREE] == [(FW + 3) ** n - FW**n] * 3
        assert found["any"][n - 1] == 3 * (FW + 6) ** n - 3 * (FW + 3) ** n
    assert SIZE**3 - FW**3 - found["any"][2] == 162  # the texts that no pair admits


def test_the_length_bound_is_the_longest_that_fits_in_the_number_of_texts() -> None:
    total = SIZE + SIZE**2 + SIZE**3

    assert enumerate_texts(TOY, VIEW, max_texts=total)["max_length"] == 3
    assert enumerate_texts(TOY, VIEW, max_texts=total - 1)["max_length"] == 2


def test_with_no_free_sentence_nothing_is_enumerated() -> None:
    found = enumerate_texts({"T.4": TOY["T.4"]}, VIEW)

    assert found == {
        "free": [],
        "vocabulary": FW,
        "max_length": 0,
        "texts": 0,
        "function_words_only": [],
        "alone": {},
        "any": [],
    }


# --- The probes -------------------------------------------------------------------------------


def test_each_probe_cites_one_or_two_sentences_and_has_a_one_line_reason(sentences) -> None:
    for probe in PROBES:
        assert set(probe.cited) <= set(sentences) and 1 <= len(probe.cited) <= 2
        assert probe.text and probe.harm and "\n" not in probe.harm


# --- The documents ----------------------------------------------------------------------------


def test_the_committed_documents_are_what_the_study_makes() -> None:
    documents = study.documents()

    assert sorted(p.name for p in documents) == ["grounding-study.json", "grounding-study.md"]
    for path, text in documents.items():
        assert path.read_text(encoding="utf-8") == text
    markdown = next(t for p, t in documents.items() if p.suffix == ".md")
    assert markdown.startswith(study.PROVENANCE)


def test_the_figures_of_row_5_count_what_their_labels_say(monkeypatch) -> None:
    toy = {
        "T.1": "Purple ducks sing.",  # free under every view
        "T.2": "Blue owls hoot at dusk.",  # `at` is a position word: not free under the full list
        "T.3": "Green frogs do not swim.",  # `not`: free under digits only
        "T.4": "Red cats purr 5 times.",  # a digit: free under none
        "T.5": "Pink pigs oink, e.g. loudly.",  # a symbol, no digit: not free under the full list
    }
    probes = [
        Probe(("T.1",), "Ducks sing.", "x"),  # admitted under every view
        Probe(("T.2",), "Owls hoot at dusk.", "x"),  # not under the full list
        Probe(("T.3",), "Frogs do swim.", "x"),  # under digits only
        Probe(("T.4",), "Cats purr.", "x"),  # under none
    ]
    monkeypatch.setattr(study, "PROBES", probes)

    result = study.study(toy, "test")

    assert {v: result["free"][v]["count"] for v in lexicon.VIEWS} == {
        "full": 1,
        "qualifiers": 3,
        "digits": 4,
    }
    assert result["probes"]["admitted"] == {"full": 1, "qualifiers": 2, "digits": 3}
    assert result["fewest_loaded"] == {"count": 0, "ids": ["T.1"]}
    assert result["row5"] == (
        "1 of the 5 catalogue sentences contain none of the study's loaded words under its full "
        "list and 4 under the digits-only ablation, and the checker admitted 1 of 4 hand-written "
        "harmful probes under the full list (2 and 3 of 4 under the qualifiers-and-digits and "
        "digits-only ablations) (docs/grounding-study.md)."
    )


def test_run_py_starts_from_a_script_run_without_the_tests_directory_on_the_path() -> None:
    source = Path(referee.__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, run.__file__, "--help"],
        env=dict(os.environ, PYTHONPATH=str(source)),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage" in result.stdout


def test_run_py_writes_the_documents_it_is_given(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run, "documents", lambda: {tmp_path / "a.md": "text\n"})

    run.main([])

    assert (tmp_path / "a.md").read_text() == "text\n"


def test_refreeze_writes_the_live_sentences_and_prints_the_digest_to_pin(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(catalogue, "FROZEN", tmp_path / "catalogue.json")
    monkeypatch.setattr(catalogue, "live_catalogue", lambda: {"XYZ-001.title": "Title"})

    run.main(["--refreeze", "abc1234"])

    written = (tmp_path / "catalogue.json").read_bytes()
    assert capsys.readouterr().out == f"FROZEN_SHA256 = '{hashlib.sha256(written).hexdigest()}'\n"
    assert catalogue.load_frozen(
        tmp_path / "catalogue.json", hashlib.sha256(written).hexdigest()
    ) == (
        "abc1234",
        {"XYZ-001.title": "Title"},
    )
