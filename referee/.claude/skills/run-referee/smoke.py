#!/usr/bin/env python3
"""Drive Referee end to end and check what a user would see.

    .venv/bin/python .claude/skills/run-referee/smoke.py                  # every step
    .venv/bin/python .claude/skills/run-referee/smoke.py --only design    # one group (repeatable)
    .venv/bin/python .claude/skills/run-referee/smoke.py --keep /tmp/out  # and save each output

Run it with the interpreter that has Referee installed (the venv's). It can be started from any
directory: every command runs in the referee/ folder, the unit this skill belongs to.

Each step is the real command line, `python -m referee ...`, in a subprocess, against the committed
examples (examples/) and the committed lab export (tests/data/hybrid_offer_page_5000). A step checks
the exit status, the lines that matter on stdout or stderr, and for the JSON formats the fields
that matter. One step calls `referee.cli.main` in the same process, the direct path: it never
raises and returns the exit status. The groups are: design, results, errors, inprocess.

Exit status 0 when every selected step passed, 1 otherwise (the failing step is printed with the
output it got).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

UNIT = Path(__file__).resolve().parents[3]  # referee/
EXAMPLES = UNIT / "examples"
EXPORT = UNIT / "tests" / "data" / "hybrid_offer_page_5000"
RESULTS = [
    "review-results",
    str(EXAMPLES / "offer-page-results.yaml"),
    str(EXPORT),
    "--experiment-id",
    "hybrid_offer_page",
    "--as-of",
    "2026-06-30T00:00:00Z",
]
MEMO_SECTIONS = [
    "Decision",
    "Observed facts",
    "Assumptions and uncertainty",
    "Data-quality qualification",
    "Reproducibility",
]


@dataclass
class Run:
    argv: list[str]
    status: int
    out: str
    err: str


@dataclass
class Step:
    group: str
    name: str
    check: Callable[[], None]
    seconds: float = field(default=0.0)


class Failed(AssertionError):
    pass


KEEP: Path | None = None
KEPT = 0


def referee(*argv: str) -> Run:
    """`python -m referee ARGV` in the unit's folder, with the interpreter running this script."""
    global KEPT
    done = subprocess.run(
        [sys.executable, "-m", "referee", *argv],
        cwd=UNIT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    run = Run(list(argv), done.returncode, done.stdout, done.stderr)
    if KEEP is not None:
        KEPT += 1
        stem = f"{KEPT:02d}-{argv[0].lstrip('-') if argv else 'referee'}"
        (KEEP / f"{stem}.out").write_text(run.out, encoding="utf-8")
        (KEEP / f"{stem}.err").write_text(run.err, encoding="utf-8")
    return run


def expect(run: Run, status: int, *, out: list[str] = (), err: list[str] = ()) -> None:
    problems = []
    if run.status != status:
        problems.append(f"exit status {run.status}, wanted {status}")
    problems += [f"stdout lacks {text!r}" for text in out if text not in run.out]
    problems += [f"stderr lacks {text!r}" for text in err if text not in run.err]
    if problems:
        raise Failed(
            "; ".join(problems)
            + f"\n  command: python -m referee {' '.join(run.argv)}"
            + f"\n  stdout (first 600 chars): {run.out[:600]!r}"
            + f"\n  stderr (first 600 chars): {run.err[:600]!r}"
        )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- design ------------------------------------------------------------------------------------


def version() -> None:
    run = referee("--version")
    expect(run, 0)
    if not re.fullmatch(r"referee \d+\.\d+\.\d+\n", run.out):
        raise Failed(f"unexpected version line {run.out!r}")


def design_underpowered() -> None:
    run = referee("review-design", str(EXAMPLES / "offer-page-underpowered.yaml"))
    expect(
        run,
        1,  # a blocker is a finding, not a crash
        out=[
            "Recommendation: REVISE",
            "Blocking rules: DES-001, PRO-001",
            "Findings: blockers 2, warnings 3, info 2",
            "[BLOCKER] DES-001: Design cannot reach the planned power",
        ],
    )


def design_powered() -> None:
    run = referee("review-design", str(EXAMPLES / "offer-page-powered.yaml"))
    expect(run, 0, out=["Recommendation: PROCEED", "Findings: none"])


def design_json() -> None:
    run = referee("review-design", str(EXAMPLES / "offer-page-powered.yaml"), "--format", "json")
    expect(run, 0)
    report = json.loads(run.out)
    wanted = {"recommendation": "proceed", "counts": {"blocker": 0, "warning": 0, "info": 0}}
    got = {key: report[key] for key in wanted}
    if got != wanted or report["findings"] != []:
        raise Failed(f"unexpected JSON report: {got} findings={report['findings']}")


def design_same_bytes() -> None:
    spec = str(EXAMPLES / "offer-page-underpowered.yaml")
    first, second = referee("review-design", spec), referee("review-design", spec)
    expect(first, 1)
    if digest(first.out) != digest(second.out):
        raise Failed("two runs of the same spec gave different bytes")


# --- results -----------------------------------------------------------------------------------


def results_text() -> None:
    run = referee(*RESULTS)
    expect(
        run,
        1,
        out=[
            "Experiment: hybrid_offer_page",
            "Verdict: INVALID",
            "Blocking rules: data validity RES-001, RES-002",
            "Findings: blockers 2, warnings 4, info 0",
        ],
    )


def results_json() -> None:
    run = referee(*RESULTS, "--format", "json")
    expect(run, 1)
    report = json.loads(run.out)
    if report["verdict"] != "invalid" or report["blocking_rule_ids"] != ["RES-001", "RES-002"]:
        raise Failed(f"verdict {report['verdict']} blocking {report['blocking_rule_ids']}")
    if report["counts"] != {"blocker": 2, "warning": 4, "info": 0} or len(report["rules_run"]) != 9:
        raise Failed(f"counts {report['counts']} rules_run {report['rules_run']}")


def results_memo() -> None:
    run = referee(*RESULTS, "--format", "memo")
    expect(run, 1, out=["# Decision memo: "])
    sections = re.findall(r"^## (.+)$", run.out, flags=re.MULTILINE)
    if sections != MEMO_SECTIONS:
        raise Failed(f"memo sections {sections}")


def results_same_bytes() -> None:
    first, second = referee(*RESULTS), referee(*RESULTS)
    expect(first, 1)
    if digest(first.out) != digest(second.out):
        raise Failed("two runs of the same spec and data gave different bytes")


def results_needs_experiment_id() -> None:
    run = referee("review-results", str(EXAMPLES / "offer-page-results.yaml"), str(EXPORT))
    expect(run, 2, err=["--experiment-id is required; the export holds: hybrid_offer_page"])


# --- errors ------------------------------------------------------------------------------------


def error_unreadable_yaml() -> None:
    with tempfile.TemporaryDirectory() as folder:
        spec = Path(folder) / "bad.yaml"
        spec.write_text("not: [valid\n", encoding="utf-8")
        expect(referee("review-design", str(spec)), 2, err=["referee: error: ", "bad.yaml:2:1"])


def error_missing_file() -> None:
    expect(referee("review-design", "/nonexistent/spec.yaml"), 2, err=["cannot be read"])


def error_unquoted_null() -> None:
    text = (EXAMPLES / "offer-page-powered.yaml").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        spec = Path(folder) / "unquoted.yaml"
        spec.write_text(text.replace('  "null":', "  null:", 1), encoding="utf-8")
        expect(referee("review-design", str(spec)), 2, err=['quote it: "null":'])


# --- inprocess ---------------------------------------------------------------------------------


def in_process_main() -> None:
    from referee.cli import main

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        spec = str(EXAMPLES / "offer-page-underpowered.yaml")
        status = main(["review-design", spec, "--format", "json"])
    report = json.loads(buffer.getvalue())
    if status != 1 or report["recommendation"] != "revise":
        raise Failed(f"main() returned {status}, recommendation {report['recommendation']}")


STEPS = [
    Step("design", "referee --version", version),
    Step("design", "review-design, underpowered example: REVISE, exit 1", design_underpowered),
    Step("design", "review-design, powered example: PROCEED, exit 0", design_powered),
    Step("design", "review-design --format json", design_json),
    Step("design", "review-design twice gives the same bytes", design_same_bytes),
    Step("results", "review-results, lab export: INVALID, exit 1", results_text),
    Step("results", "review-results --format json", results_json),
    Step("results", "review-results --format memo: five sections", results_memo),
    Step("results", "review-results twice gives the same bytes", results_same_bytes),
    Step("errors", "review-results without --experiment-id: exit 2", results_needs_experiment_id),
    Step("errors", "unreadable YAML: exit 2 with file:line:column", error_unreadable_yaml),
    Step("errors", "missing spec file: exit 2", error_missing_file),
    Step("errors", "unquoted `null:` key: exit 2 says to quote it", error_unquoted_null),
    Step("inprocess", "referee.cli.main() returns the exit status", in_process_main),
]


def main() -> int:
    global KEEP
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--only", action="append", choices=sorted({s.group for s in STEPS}))
    parser.add_argument("--keep", type=Path, help="folder for each command's stdout and stderr")
    args = parser.parse_args()
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)
        KEEP = args.keep

    try:
        import referee  # noqa: F401
    except ImportError as error:
        print(f"cannot import referee ({error}); run this with the venv's python", file=sys.stderr)
        return 1

    chosen = [s for s in STEPS if not args.only or s.group in args.only]
    failed = 0
    started = time.perf_counter()
    for step in chosen:
        begin = time.perf_counter()
        try:
            step.check()
        except (Failed, json.JSONDecodeError, KeyError) as error:
            failed += 1
            print(f"FAIL {step.name}\n  {error}")
        else:
            print(f"ok   {step.name}  ({time.perf_counter() - begin:.1f} s)")
    took = time.perf_counter() - started
    print(f"{len(chosen) - failed}/{len(chosen)} steps passed in {took:.1f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
