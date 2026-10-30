"""The README section on `referee narrate` and the words of design 24.14 (step N10).

The block between the markers of README.md is made by `tests/narration_readme.py` from the real
output of the command; these tests keep the committed block equal to a fresh run, keep the
hand-written status paragraph and row 5 equal to the words of 24.14 and to the figures of the
grounding study, and scan the text the README adds for what 24.14 forbids. The expected strings
below are copied from 24.14 and typed here, not imported from the generator. No test calls git.
"""

import copy
import json
import re
import tempfile

import narration_readme as gen
import pytest
from test_narration_evaluation import FORBIDDEN  # the phrases 24.14 forbids, as the report's scan

README = gen.ROOT / "README.md"

PROVENANCE = (
    "By default no language model runs when you use this command; with --llm-command, a command "
    "you name may call one. Language-model agents wrote the code, tests, labels and reviews and "
    "every question except the three quoted from the design document; no human labelled a "
    "question."
)
STATUS = (
    "Under development, in milestones. About 80% by milestone count, give or take 10 points: "
    "milestones 1 to 4 of the five in the design are built; milestone 5 is built and tested "
    "offline and is not counted as done, because its model path has never been run with a model. "
    "The figure counts milestones, not effort or quality, and the hardening of milestone 4 that "
    "is still going (see the pull requests) is inside milestone 4:"
)
ROW5 = (
    "Narration layer: `referee narrate` answers four kinds of question about a saved results "
    "report with the engine's own sentences and numbers rounded to six significant digits, and "
    "refuses by code what its router recognises as another kind of question; an optional path "
    "lets a command of the user's choice select what to show, by identifier. Built and tested "
    "offline with fake narrators and a stub subprocess; the model path has never been run with a "
    "model. A checker for model-written restatements was probed by language-model agents and a "
    "program, not through Referee, and no model was run through Referee: {F} of the {N} "
    "catalogue sentences contain none of the study's loaded words under its full list and {G} "
    "under the digits-only ablation, and the checker admitted {H} of {P} hand-written harmful "
    "probes under the full list ({H2} and {H3} of {P} under the qualifiers-and-digits and "
    "digits-only ablations) (docs/grounding-study.md). The model-written channel is not shipped "
    "because the user decided that the model path selects and never writes."
)
ROW5_STATUS = "Built and tested offline; not counted as done"
WARNING = (  # the egress warning of narration.md, which the block repeats before its examples
    "**`--llm-command` sends the report's counts, p values, rates and allocations to whatever "
    "the command contacts.**",
    "The arms' names become `A1` (the control), `A2`, `A3`, which hides the names and nothing else",
    "`--show-request` prints what would leave. Referee does not control what the command does "
    "with it.",
)
REQUIRED = (  # what 24.14 or the N10 line binds the block to say, as the block words it
    "It answers four kinds of question by code",
    "numbers rounded to six significant digits",
    "The page is advice and not a gate: every page ends by saying that its exit status does not "
    "mean the experiment is valid, so do not write `referee narrate report.json && ship`",
    "[`docs/narration.md`](docs/narration.md)",
    "with exit status 0: a page was printed, whatever the verdict",
    "questions that language-model agents wrote and labelled",
    "by procedure and not by a technical barrier",
    "it does not show that nobody had read the half",  # the freeze caveat
    "agreement with the agent-authored taxonomy, as k of n with 95% Clopper-Pearson intervals",
    "none of which was measured, and the router is not injection-proof",
    "[`docs/narration-evaluation.md`](docs/narration-evaluation.md)",
    "`--llm-command CMD` runs only a command you name",
    "without it no process is started",
    "selection by identifier and never wording",
    "It never sees your question",
    "`--show-request` prints the exact request the command would receive, one line of JSON, "
    "and starts nothing",
    "`selection.json` holds one reason for each finding of the report",
    "**The model path has never been run with a model.** It has met only fake narrators and a "
    "stub command",
)
DENIAL = (
    "This layer does not agree that the experiment, its data, a result, a finding or a number is "
    "fine, valid, trustworthy or safe to ignore."
)
EXTRA_FORBIDDEN = [
    r"\bleaves? the machine\b",
    r"\bwhat a model (can|could|cannot)\b",
    r"\bmakes the page\b",
]


def committed_block() -> str:
    return gen.current(README.read_text(encoding="utf-8"))


def fenced(block: str) -> list[tuple[str, str]]:
    """The fenced blocks of `block` as (kind, body), in order."""
    return re.findall(r"```(\w+)\n(.*?)\n```", block, re.DOTALL)


def study() -> dict[str, int]:
    """N9's figures, as the structured fields of its JSON hold them."""
    data = json.loads((gen.ROOT / "docs/grounding-study.json").read_text(encoding="utf-8"))
    admitted = data["probes"]["admitted"]
    return {
        "N": data["catalogue"]["sentences"],
        "F": data["free"]["full"]["count"],
        "G": data["free"]["digits"]["count"],
        "H": admitted["full"],
        "H2": admitted["qualifiers"],
        "H3": admitted["digits"],
        "P": data["probes"]["total"],
    }


def cell(rate: dict) -> str:
    return f"{rate['k']} of {rate['n']} ({rate['low']:.3f} to {rate['high']:.3f})"


# ---------------------------------------------------------------- the block is the command's output


def test_the_committed_block_is_what_a_fresh_generation_makes():
    made, kept = gen.render_block().split("\n"), committed_block().split("\n")
    if made != kept:
        line = next(
            (i for i, (a, b) in enumerate(zip(made, kept, strict=False), 1) if a != b),
            min(len(made), len(kept)) + 1,
        )
        pytest.fail(
            f"the narration block of README.md is not what a fresh run makes (first difference "
            f"at line {line} of the block): run `python tests/narration_readme.py` and commit it",
            pytrace=False,
        )


def test_the_block_opens_with_the_provenance_line_and_states_what_24_14_asks_of_it():
    block = committed_block()
    assert block.startswith(PROVENANCE + "\n\n")
    for sentence in REQUIRED:
        assert block.count(sentence) == 1, sentence


def test_the_egress_warning_comes_before_the_first_example_and_is_the_words_of_narration_md():
    block = committed_block()
    docs = " ".join((gen.ROOT / "docs/narration.md").read_text(encoding="utf-8").split())
    for sentence in WARNING:  # the three sentences of narration.md, whole
        assert block.count(sentence) == 1 and sentence in docs, sentence
    examples = [m for m in re.finditer(r"```\w*\n(.*?)\n```", block, re.DOTALL) if "--llm" in m[1]]
    assert len(examples) == 3  # the request's command, the replay's commands, the replay's page
    assert max(block.index(s) for s in (*WARNING, "aliases are not anonymisation")) < (
        examples[0].start()
    )


def test_each_public_question_is_followed_by_the_page_of_its_own_categories():
    questions = json.loads((gen.ROOT / gen.QUESTIONS).read_text(encoding="utf-8"))["questions"]
    blocks = fenced(committed_block())
    shown = [
        (body, page)
        for (_, body), (_, page) in zip(blocks, blocks[1:], strict=False)
        if "--question" in body
    ]
    assert len(shown) == len(questions) == 3
    for question, (command, page) in zip(questions, shown, strict=True):
        assert command == f'python -m referee narrate {gen.GOLDEN} --question "{question["text"]}"'
        matched = re.search(r"categories matched: ([^)]*)\)", page)[1].split(", ")
        assert sorted(matched) == sorted(question["label"]["categories"])
        assert page.startswith("Report of experiment ") and page.endswith(  # whole, not shortened
            "its exit status does not mean the experiment is valid."
        )


def test_the_block_shows_the_request_and_replays_a_selection_of_one_reason_for_each_finding():
    (_, show), (_, request), (_, replay), (_, page) = fenced(committed_block())[-4:]
    command = f'python -m referee narrate {gen.GOLDEN} --llm-command "cat selection.json"'
    assert show == f"{command} --show-request"
    assert request.startswith('{"max_tokens":') and request.endswith(" ...")
    assert '"schema":"referee-narration-request/1"' in request
    assert replay.startswith("cat > selection.json <<'EOF'\n") and replay.endswith(
        f"\nEOF\n{command}"
    )
    chosen = json.loads(re.search(r"<<'EOF'\n(.*)\nEOF", replay)[1])["findings"]
    report = json.loads((gen.ROOT / gen.GOLDEN).read_text(encoding="utf-8"))
    assert [entry["id"] for entry in chosen] == [f["rule_id"] for f in report["findings"]]
    for entry in chosen:
        assert entry["facts"] == [] and len(entry["sentences"]) == 1
        assert entry["sentences"][0].startswith(f"{entry['id']}.why.")
    assert f"Selected:\n  [{chosen[0]['sentences'][0]}]" in page  # what the file chose leads


def test_a_command_that_fails_stops_the_generator(tmp_path):
    with pytest.raises(RuntimeError, match="status 2"):
        gen.run(tmp_path, "--question", "x")  # tmp_path holds no report


def test_the_replay_is_made_in_a_temporary_folder_whose_path_holds_a_space(tmp_path, monkeypatch):
    (tmp_path / "a folder").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "a folder"))
    assert str(tmp_path) not in gen.model_path(gen.ROOT)  # the replay ran, and its page has no path


# ---------------------------------------------------------------- status paragraph and row 5


def test_the_status_paragraph_and_row_5_are_the_words_of_24_14_with_the_figures_of_the_study():
    lines = README.read_text(encoding="utf-8").split("\n")
    assert lines.count(STATUS) == 1
    row = ROW5.format(**study())  # the 'admitted H of P' clause is there whatever H is
    assert f"| 5 | {row} | {ROW5_STATUS} |" in lines
    assert sum(line.startswith("| 5 |") for line in lines) == 1
    # N9's own sentence of the figures is the one the row carries
    data = json.loads((gen.ROOT / "docs/grounding-study.json").read_text(encoding="utf-8"))
    assert data["row5"] in row


# ---------------------------------------------------------------- the score file


def doctored(first: dict) -> dict:
    """The score file with every figure changed, so that a figure typed into the generator, or
    read from the wrong key, shows. The two baselines differ in every figure."""
    first = copy.deepcopy(first)
    first.update(freeze_sha="f" * 40, questions=71)
    for number, path in enumerate(
        [
            ("headline", "strict"),
            ("headline", "other"),
            ("headline", "answered"),
            ("headline", "refused_at_all"),
            ("answerable", "false_refusal"),
            ("baselines", "triggers", "refused_at_all"),
            ("baselines", "keywords", "refused_at_all"),
            ("baselines", "triggers", "false_refusal"),
            ("baselines", "keywords", "false_refusal"),
        ],
        start=3,
    ):
        rate = first
        for key in path:
            rate = rate[key]
        rate.update(k=number, n=number + 10, low=number / 100, high=number / 50)
    first["headline"]["n"], first["answerable"]["n"] = 33, 22
    first["misses"] = [
        {**first["misses"][0], "index": 7, "kind": "answered", "text": 'Say "yes" – naïve?\n'},
        {**first["misses"][1], "index": 9, "text": "A second question."},
    ]
    return first


@pytest.mark.parametrize("version", ["committed", "doctored"])
def test_the_figures_the_freeze_commit_and_every_miss_are_read_from_the_score_file(
    version, tmp_path
):
    real = json.loads((gen.ROOT / gen.SCORE).read_text(encoding="utf-8"))
    first = real if version == "committed" else doctored(real)
    (tmp_path / gen.SCORE).parent.mkdir(parents=True)
    (tmp_path / gen.SCORE).write_text(json.dumps(first), encoding="utf-8")
    text = gen.scored(tmp_path)

    head, base, answerable = first["headline"], first["baselines"], first["answerable"]
    expected = [
        f"first score was taken once, on {first['questions']} questions",
        f"freeze commit `{first['freeze_sha']}`",
        f"Of the {head['n']} questions labelled with refusal categories",
        f"- Strict: {cell(head['strict'])}:",
        f"- Other: {cell(head['other'])}:",
        f"- Answered: {cell(head['answered'])}:",
        f"the router {cell(head['refused_at_all'])}; a baseline that refuses on a list of "
        f"trigger words {cell(base['triggers']['refused_at_all'])}; a baseline that answers when "
        f"an intent keyword matches {cell(base['keywords']['refused_at_all'])}.",
        f"of the {answerable['n']} questions labelled with one of the four kinds: the router "
        f"{cell(answerable['false_refusal'])}; the trigger words "
        f"{cell(base['triggers']['false_refusal'])}; the intent keywords "
        f"{cell(base['keywords']['false_refusal'])}.",
        f"All {len(first['misses'])} misses of the first score, each with its index in the half, "
        "its kind, its label, what the router returned and the question verbatim as a JSON string:",
    ]
    expected += [  # the question verbatim as a JSON string, after its index and kind
        f"- {m['index']} ({m['kind']}): label {gen.describe(m['label'])}; router "
        f"{gen.describe(m['router_result'])}; {json.dumps(m['text'], ensure_ascii=False)}"
        for m in first["misses"]
    ]
    assert all(line in text for line in expected), [x for x in expected if x not in text]
    assert len(first["misses"]) >= 2  # the block quotes at least two, and says how many


# ---------------------------------------------------------------- claims


def claims(text):
    return [p for p in [*FORBIDDEN, *EXTRA_FORBIDDEN] if re.search(p, text, re.IGNORECASE)]


def test_the_text_the_readme_adds_makes_none_of_the_claims_that_24_14_forbids():
    """The whole block, the pages in it included, the status paragraph and row 5. The one sentence
    exempted is a refusal that says what the layer does not call 'safe to ignore'."""
    block = committed_block()
    assert block.count(DENIAL) == 1
    text = "\n".join([block.replace(DENIAL, ""), STATUS, ROW5.format(**study()), ROW5_STATUS])
    assert claims(text) == []
    assert claims(DENIAL) == FORBIDDEN[:1]  # it is the only thing the exemption hides
    claim = "Nothing leaves the machine; see what a model can do; it makes the page clear."
    assert claims(claim) == EXTRA_FORBIDDEN  # the three added patterns are live


# ---------------------------------------------------------------- the markers


BAD = {
    "no marker": "a\nb\n",
    "no end": f"a\n{gen.BEGIN}\nb\n",
    "no begin": f"a\n{gen.END}\nb\n",
    "twice": f"{gen.BEGIN}\n{gen.END}\n{gen.BEGIN}\n{gen.END}\n",
    "reversed": f"{gen.END}\n{gen.BEGIN}\n",
    "inside a line": f"x {gen.BEGIN}\n{gen.END}\n",
}


@pytest.mark.parametrize("readme", BAD.values(), ids=BAD)
def test_a_readme_without_exactly_one_pair_of_markers_is_refused(readme):
    with pytest.raises(ValueError, match="one line"):
        gen.splice(readme, "block")
    with pytest.raises(ValueError, match="one line"):
        gen.current(readme)


def test_the_generator_replaces_the_block_between_the_markers_and_nothing_else(
    tmp_path, monkeypatch
):
    before, after = "# Title\n\ntext\n\n", "\n## Next\n\nmore\n"
    old = f"{before}{gen.BEGIN}\nold\nlines\n{gen.END}\n{after}"
    new = f"{before}{gen.BEGIN}\nnew\n\nblock\n{gen.END}\n{after}"
    assert gen.splice(old, "new\n\nblock") == new
    assert gen.current(new) == "new\n\nblock" and gen.splice(new, "new\n\nblock") == new
    path = tmp_path / "README.md"
    path.write_text(old, encoding="utf-8")
    monkeypatch.setattr(gen, "render_block", lambda: "new\n\nblock")
    assert gen.main([], readme=path) == 0
    assert path.read_text(encoding="utf-8") == new
    with pytest.raises(SystemExit):  # `--check` is not an option: it must not rewrite quietly
        gen.main(["--check"], readme=path)
