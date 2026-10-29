"""No model identifier and no key in what is committed (design section 24.11).

The user's constraint is that Referee names no model and holds no credential. A change that adds
one in a recognised shape fails here: a vendor name, a separator and a version or tier word, or a
known provider key prefix and a long token. Other spellings (`gpt4o`, `llama3`), vendors not named
here, credentials without a known prefix, symlinked directories and unlisted file types are not
caught. The guard walks the files itself, without `git`, so that it also runs in the mutation
tool's copy of the repository (which has no `.git`) and in a source archive. Its claim is only that
no recognised shape is in these roots at the commit tested. The patterns are built from fragments
so that this file does not match itself, and the test data of the narration layer has no exemption.
"""

import re
from pathlib import Path

import pytest

REFEREE = Path(__file__).resolve().parents[1]
REPO = REFEREE.parent

SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".csv"}
SKIPPED = {".venv", "venv", "site-packages", "__pycache__"}

# A vendor name, a separator, then a version number or a tier word: an identifier, not a bare name.
_VENDORS = ("cla" + "ude", "g" + "pt", "gem" + "ini", "lla" + "ma", "mis" + "tral")
_TIERS = ("op" + "us", "son" + "net", "hai" + "ku", "fa" + "ble", "tur" + "bo", "ul" + "tra")
_TIERS += ("fla" + "sh", "mi" + "ni", "pr" + "o", "na" + "no")
_TIERS += ("lar" + "ge", "sma" + "ll", "medi" + "um", "inst" + "ant")
IDENTIFIER = re.compile(
    rf"(?:{'|'.join(_VENDORS)})[-_/ ](?:v?\d|(?:{'|'.join(_TIERS)})(?![a-z]))", re.IGNORECASE
)
# Known provider key prefixes followed by a long token. A digest (hexadecimal) matches none.
_PREFIXES = ("s" + "k-", "AK" + "IA", "gh" + "p_", "github_" + "pat_", "xo" + "xb-", "AI" + "za")
KEYS = re.compile(rf"\b(?:{'|'.join(_PREFIXES)})[A-Za-z0-9_-]{{16,}}")


def roots(repo: Path) -> tuple[Path, ...]:
    referee = repo / "referee"
    return (
        *(referee / name for name in ("src", "tests", "docs", "examples")),
        referee / "README.md",
        referee / "pyproject.toml",
        repo / ".github" / "workflows",
    )


def files(root: Path):
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(part in SKIPPED or part.endswith(".egg-info") for part in parts):
            continue
        if path.is_file() and path.suffix.lower() in SUFFIXES:
            yield path


def scan(repo: Path) -> list[str]:
    """Where each identifier or key is, never what it is."""
    problems = []
    for root in roots(repo):
        if not root.exists():
            problems.append(f"{root.relative_to(repo)}: the root is missing")
            continue
        for path in files(root):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.split("\n"), 1):
                for kind, pattern in (("model identifier", IDENTIFIER), ("key", KEYS)):
                    if pattern.search(line):
                        problems.append(f"{path.relative_to(repo)}:{number}: {kind}")
    return problems


def tree(tmp_path: Path, **planted: str) -> Path:
    """An innocent copy of the layout, with `planted` (relative path -> text) written into it."""
    for root in roots(tmp_path):
        if root.suffix:
            root.parent.mkdir(parents=True, exist_ok=True)
            root.write_text("nothing here\n", encoding="utf-8")
        else:
            root.mkdir(parents=True)
            (root / "innocent.md").write_text("nothing here\n", encoding="utf-8")
    for relative, text in planted.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    return tmp_path


def found(tmp_path: Path, where: str, text: str) -> list[str]:
    return scan(tree(tmp_path, **{where: text}))


MODEL = "cla" + "ude-son" + "net-4"


def test_nothing_in_the_repository_names_a_model_or_holds_a_key() -> None:
    assert scan(REPO) == []


@pytest.mark.parametrize(
    "where",
    [
        "referee/src/referee/module.py",
        "referee/tests/data/questions.jsonl",
        "referee/docs/note.md",
        "referee/examples/spec.yaml",
        "referee/README.md",
        "referee/pyproject.toml",
        ".github/workflows/ci.yml",
    ],
)
def test_an_identifier_planted_in_any_root_fails_it(tmp_path, where) -> None:
    assert found(tmp_path, where, f"model = {MODEL}") == [f"{where}:1: model identifier"]


@pytest.mark.parametrize(
    "suffix", [".py", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".csv", ".MD"]
)
def test_the_text_suffixes_are_read_in_any_case(tmp_path, suffix) -> None:
    assert len(found(tmp_path, f"referee/docs/note{suffix}", MODEL)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "cla" + "ude-3",
        "cla" + "ude_3",
        "CLA" + "UDE_SON" + "NET_4",
        "cla" + "ude-v2.1",
        "cla" + "ude/3",
        "cla" + "ude 3.5",
        "G" + "PT-4",
        "Gem" + "ini 1.5",
        "lla" + "ma-3",
        "mis" + "tral-7b",
        "cha" + "tg" + "pt-4",
        "Cla" + "ude-Fa" + "ble-5",
    ],
)
def test_the_shapes_of_an_identifier_fail_it(tmp_path, text) -> None:
    assert found(tmp_path, "referee/docs/note.md", text) == [
        "referee/docs/note.md:1: model identifier"
    ]


@pytest.mark.parametrize("tier", ["op" + "us", "hai" + "ku", "fa" + "ble", "inst" + "ant"])
def test_the_tier_words_of_a_vendor_fail_it(tmp_path, tier) -> None:
    assert len(found(tmp_path, "referee/docs/note.md", "cla" + "ude " + tier)) == 1


@pytest.mark.parametrize(
    "tier",
    ["tur" + "bo", "ul" + "tra", "fla" + "sh", "mi" + "ni", "pr" + "o", "na" + "no"]
    + ["lar" + "ge", "sma" + "ll", "medi" + "um"],
)
def test_the_tier_words_of_other_vendors_fail_it(tmp_path, tier) -> None:
    assert len(found(tmp_path, "referee/docs/note.md", "gem" + "ini " + tier)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "s" + "k-" + "an" + "t-" + "a1" * 10,
        "AK" + "IA" + "B2" * 8,
        "gh" + "p_" + "c3" * 18,
        "github_" + "pat_" + "d4" * 12,
        "xo" + "xb-" + "e5" * 8,
        "AI" + "za" + "f6" * 18,
    ],
)
def test_a_key_shaped_string_fails_it(tmp_path, text) -> None:
    assert found(tmp_path, "referee/src/referee/module.py", f"KEY = '{text}'") == [
        "referee/src/referee/module.py:1: key"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Cla" + "ude Code",
        "a g" + "pt model and a fa" + "ble",
        "the risk-assessment-of-the-whole-experiment-design",
        "a gem" + "ini process",
        "s" + "k-" + "a1" * 7 + "b",
        "AK" + "IA" + "B2" * 7 + "c",
        "digest = " + "9f" * 32,
    ],
)
def test_a_bare_family_name_ordinary_words_a_short_token_and_a_digest_pass(tmp_path, text) -> None:
    assert found(tmp_path, "referee/docs/note.md", text) == []


@pytest.mark.parametrize(
    "where",
    [
        "referee/src/.venv/lib/module.py",
        "referee/src/venv/module.py",
        "referee/src/referee/__pycache__/module.py",
        "referee/tests/site-packages/module.py",
        "referee/src/referee.egg-info/notes.txt",
        "referee/docs/figure.png",
    ],
)
def test_environments_caches_and_binary_files_are_not_read(tmp_path, where) -> None:
    assert found(tmp_path, where, MODEL) == []


def test_a_checkout_under_an_environment_named_directory_is_still_read(tmp_path) -> None:
    root = tree(tmp_path / "venv", **{"referee/docs/note.md": MODEL})

    assert scan(root) == ["referee/docs/note.md:1: model identifier"]


def test_every_hit_is_reported_with_its_line(tmp_path) -> None:
    text = f"fine\x0c\u2028 still line one\n{MODEL} {'s' + 'k-' + 'a1' * 10}\nfine\n{MODEL}"

    assert found(tmp_path, "referee/docs/note.md", text) == [
        "referee/docs/note.md:2: model identifier",
        "referee/docs/note.md:2: key",
        "referee/docs/note.md:4: model identifier",
    ]


def test_a_missing_root_fails_it_and_does_not_skip(tmp_path) -> None:
    (tree(tmp_path) / ".github" / "workflows" / "innocent.md").unlink()
    (tmp_path / ".github" / "workflows").rmdir()

    assert scan(tmp_path) == [".github/workflows: the root is missing"]
