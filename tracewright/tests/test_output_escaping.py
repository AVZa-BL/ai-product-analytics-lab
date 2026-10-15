import csv
import json
import shlex

import pytest

from tracewright.cli import main
from tracewright.loader import LoadError, parse_plan
from tracewright.report import plan_report, render_text
from tracewright.review import review_plan

# What a plan, a CSV or a Sheet may carry past the reader: CR, a line separator, and a line
# break right before text that would pass for a new line of output.
LINES = "\r\u2028\nFORGED"
# Refused in a plan, but a YAML key and a CSV type cell are shown before any such check.
ESC = "\x1b[2J"
# Ordinary text, with a full-width space, that has to come out as it went in.
ORDINARY = "Caf\u00e9\u3000\u30c1\u30a7\u30c3\u30af\u30a2\u30a6\u30c8"

PLAN = "tracewright_plan_version: 1\nid: p\ntitle: {}\nidentity_keys: [u]\nevents:\n  - name: {}\n"


def _review_text(tmp_path, capsys):
    plan = parse_plan(PLAN.format(json.dumps(ORDINARY + LINES), json.dumps("e" + LINES)))
    return render_text(plan_report(plan, review_plan(plan)))


def _yaml_key(tmp_path, capsys):
    with pytest.raises(LoadError) as error:
        parse_plan(f"!!null {json.dumps(ORDINARY + ESC + LINES)}: 1\n")
    return str(error.value)


def _import(tmp_path, capsys, *args, event="e", type_="string"):
    path = tmp_path / "plan.csv"
    with open(path, "w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerows([["event", "property", "type"], [event, "p", type_]])
    main(["import-plan", str(path), "--id", "p", "--title", "P", "--identity-key", "u", *args])
    captured = capsys.readouterr()
    return captured.out + captured.err


def _dry_run_preview(tmp_path, capsys):
    return _import(tmp_path, capsys, "--dry-run", event=ORDINARY + LINES)


def _type_cell_hint(tmp_path, capsys):
    return _import(tmp_path, capsys, type_="x<>'; id #" + ORDINARY + ESC + LINES)


@pytest.mark.parametrize(
    "shown", [_review_text, _yaml_key, _dry_run_preview, _type_cell_hint], ids=lambda f: f.__name__
)
def test_text_from_a_file_is_shown_escaped_not_raw(shown, tmp_path, capsys):
    text = shown(tmp_path, capsys)
    assert "FORGED" in text and ORDINARY in text  # escaped or kept, never dropped
    assert not set(text) & {"\x1b", "\r", "\u2028"}
    assert not [line for line in text.splitlines() if line.startswith("FORGED")]
    for line in text.splitlines():  # a pasted hint must stay one shell word
        if "--type-map 'x<>" in line:
            word = shlex.shlex(line.split("--type-map ", 1)[1], posix=True)
            word.whitespace_split = True
            assert "x<>'; id #" in word.get_token()
