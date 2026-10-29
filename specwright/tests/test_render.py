"""What a document or a model writes cannot become structure in the report or the files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from specwright.cli import main
from specwright.render import code
from tests.helpers import BRIEFS, SHOP, claim, shop_draft

HOSTILE = "x`\n# Injected heading\n[click](http://evil.example)‮\x1b[31m| a |"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", "`plain`"),
        ("a`b", "``a`b``"),
        ("a``b`c", "```a``b`c```"),
        ("`edge", "`` `edge ``"),
        ("two\nlines", "`two\\u000alines`"),
        ("\x1b[31m", "`\\u001b[31m`"),
        ("‮RTL", "`\\u202eRTL`"),
        (3.5, "`3.5`"),
    ],
)
def test_a_value_is_one_line_in_a_code_span_nothing_in_it_can_close(value, expected: str) -> None:
    assert code(value) == expected


def test_hostile_text_in_a_draft_cannot_make_a_heading_a_link_or_a_new_line(
    capsys, tmp_path: Path
) -> None:
    data = shop_draft()
    claim(data, "title")["value"] = HOSTILE
    data["assumptions"] = [HOSTILE]
    data["open_questions"] = [HOSTILE]
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps(data))
    out = tmp_path / "out"

    code_ = main(
        ["draft", "--doc", str(BRIEFS / f"{SHOP}.md"), "--replay", str(replay), "--out", str(out)]
    )
    capsys.readouterr()

    assert code_ == 0
    lines = (out / "report.md").read_text(encoding="utf-8").splitlines()
    headings = [line for line in lines if line.startswith("#")]
    assert all(h.startswith(("# Specwright draft", "## ", "### ")) for h in headings)
    assert not any("Injected heading" in h for h in headings)
    assert not any(ch in "\n".join(lines) for ch in ("\x1b", "‮"))
    assert not any(line.startswith("[click]") for line in lines)


def test_a_question_with_a_newline_cannot_inject_a_line_into_the_partial_yaml(
    capsys, tmp_path: Path
) -> None:
    data = shop_draft()
    c = claim(data, "primary_metric.baseline")
    c.update(value=None)
    c["evidence"] = {"kind": "missing", "document": "", "quote": "", "note": "ask\nbaseline: 0.99"}
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps(data))

    main(
        [
            "draft",
            "--doc",
            str(BRIEFS / f"{SHOP}.md"),
            "--replay",
            str(replay),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    capsys.readouterr()

    partial = yaml.safe_load((tmp_path / "out" / "partial-draft.yaml").read_text(encoding="utf-8"))
    assert "baseline" not in partial and "baseline" not in partial["primary_metric"]


def test_the_json_report_is_ascii_and_holds_what_the_report_says(capsys, tmp_path: Path) -> None:
    data = shop_draft()
    claim(data, "title")["value"] = "Café ☃ banner"
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps(data))

    main(
        [
            "draft",
            "--doc",
            str(BRIEFS / f"{SHOP}.md"),
            "--replay",
            str(replay),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    capsys.readouterr()

    raw = (tmp_path / "out" / "draft.json").read_text(encoding="utf-8")
    report = json.loads(raw)
    assert raw.isascii() and report["status"] == "ok" and report["spec"]["title"] == "Café ☃ banner"
    assert report["spec_sha256"] and report["plan"]["is_powered"] is True
