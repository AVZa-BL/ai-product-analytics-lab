"""The committed pooled-effect study, and the design text written from it (design section 21.10)."""

import json
import math
import shlex
import sys
from pathlib import Path

import numpy as np
import pooled_simulation as module
import pytest
import scipy
from cohort_simulation import PAYING, SPEND_SD, render
from pooled_simulation import (
    Cell,
    boot_reps_for,
    pooled_grid,
    reps_for,
    study,
    wants_bootstrap,
)

from referee.methods import heavy_tail_measures  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"
NAME = "pooled_effect_heavy"
TEXT = (DOCS / f"simulations/{NAME}.json").read_text(encoding="utf-8")
POOLED = json.loads(TEXT)
DESIGN = (DOCS / "design/2026-09-28-referee-experiment-review-design.md").read_text(
    encoding="utf-8"
)
CELLS = POOLED["cells"]


def _key(row: dict) -> tuple:
    return (row["outcome"], row["arm_n"], row["control_n"], row["effect"], row.get("paying"))


# --- The committed file -------------------------------------------------------------------------


def test_the_file_holds_the_grid_the_module_makes_in_the_order_it_makes_it() -> None:
    assert list(POOLED) == [
        "what",
        "reps",
        "large_reps",
        "boot_reps",
        "resamples",
        "alpha",
        "seed",
        "numpy",
        "scipy",
        "command",
        "outcomes",
        "columns",
        "cells",
    ]
    assert (POOLED["reps"], POOLED["large_reps"], POOLED["boot_reps"]) == (20000, 2000, 2000)
    assert (POOLED["seed"], POOLED["resamples"], POOLED["alpha"]) == (20261212, 10000, 0.05)
    assert [_key(row) for row in CELLS] == [
        (c.outcome, c.arm_n, c.control_n, c.effect, c.paying) for c in pooled_grid()
    ]
    assert len(CELLS) == 620 and len({_key(row) for row in CELLS}) == 620
    for row, cell in zip(CELLS, pooled_grid(), strict=True):
        n = reps_for(cell, POOLED["reps"], POOLED["large_reps"])
        assert row["reps"] == n
        assert ("boot" in row) == wants_bootstrap(cell)
        assert row["boot_reps"] == boot_reps_for(cell, POOLED["boot_reps"], n)
        assert row["seed"] == POOLED["seed"]
        assert row["truth"] == pytest.approx(cell.truth, abs=1e-5)
    assert sum("boot" in row for row in CELLS) == 99
    assert {row["reps"] for row in CELLS} == {20000, 2000}


def test_the_counts_of_every_row_add_up() -> None:
    for row in CELLS:
        reps, boot = row["reps"], row["boot_reps"]
        assert row["welch_undefined_n"] == 0  # nobody in these cells has two arms of zeros
        assert 0 <= row["welch_above_n"] + row["welch_below_n"] <= reps
        low, middle, high = row["error"]
        assert low <= middle <= high and row["half_width"] > 0 and row["welch_width"] > 0
        for who in ("arm", "control"):
            skew, kurt, share = (row["shape"][who][i : i + 3] for i in (0, 3, 6))
            assert skew == sorted(skew) and kurt == sorted(kurt)
            if row["outcome"] == "normal":  # no share of a total to speak of
                assert share == [None] * 3
            else:
                assert share == sorted(share) and all(0 < x <= 1 for x in share)
        for name, tally in row["criteria"].items():
            fired, above_fired, below_fired, above_not, below_not = tally
            assert above_fired + above_not == row["welch_above_n"], (_key(row), name)
            assert below_fired + below_not == row["welch_below_n"], (_key(row), name)
            assert above_fired + below_fired <= fired <= reps
        assert row["criteria"]["kohavi"][0] <= reps
        if "boot" in row:
            b = row["boot"]
            assert 0 < boot <= reps and b["undefined_n"] == 0
            for side in ("above", "below"):
                both, welch_only, boot_only = b[side]
                assert both + welch_only == b[f"welch_{side}_n"] <= boot
                assert both + boot_only == b[f"boot_{side}_n"] <= boot
            assert 0 < b["boot_width"] <= b["welch_width"] * 1.0001
            assert b["welch_width"] == pytest.approx(
                row["welch_width"], rel=0.25
            )  # a mean of heavy-tailed widths
        else:
            assert "boot" not in row


def test_the_file_is_strict_json_that_the_module_writes_in_the_form_it_is_read() -> None:
    def refuse(constant: str) -> None:
        raise AssertionError(f"{constant} in the file")

    json.loads(TEXT, parse_constant=refuse)  # no NaN, no Infinity
    header = {k: v for k, v in POOLED.items() if k != "cells"}

    produced = render(header, {"cells": CELLS})

    if produced != TEXT:  # say where, at once: a diff of the two strings takes minutes to build
        lines = zip(produced.splitlines(), TEXT.splitlines(), strict=False)
        first = next((i for i, (a, b) in enumerate(lines, 1) if a != b), "past the end")
        pytest.fail(f"the file is not what render makes of it: first difference at line {first}")


def test_the_recorded_command_makes_the_header_and_the_table_of_the_file(
    tmp_path, monkeypatch
) -> None:
    words = shlex.split(POOLED["command"])
    arguments = module._parser().parse_args(words[2:])

    assert words[:2] == ["python", "tests/pooled_simulation.py"]
    assert (arguments.reps, arguments.large_reps, arguments.boot_reps, arguments.seed) == (
        POOLED["reps"],
        POOLED["large_reps"],
        POOLED["boot_reps"],
        POOLED["seed"],
    )
    assert arguments.out == Path(f"docs/simulations/{NAME}.json")
    assert isinstance(POOLED["numpy"], str) and isinstance(POOLED["scipy"], str)  # recorded

    monkeypatch.setattr(module, "study", lambda cells, *args, **kwargs: [{} for _ in cells])
    out = tmp_path / words[words.index("--out") + 1]  # not into the repository
    words[words.index("--out") + 1] = str(out)
    module.main(words[2:])
    made = json.loads(out.read_text(encoding="utf-8"))

    assert list(made) == list(POOLED)  # the same keys in the same order
    own = {"numpy": np.__version__, "scipy": scipy.__version__, "command": shlex.join(words)}
    for key in made:
        if key in own:
            assert made[key] == own[key]
        elif key != "cells":
            assert made[key] == POOLED[key], key
    assert len(made["cells"]) == len(CELLS)


def test_the_header_says_what_the_columns_and_the_outcomes_are() -> None:
    assert "a share 0.13 of the players spend" in POOLED["outcomes"]
    assert "mean 3.0 per player (23.08 per paying player) in all" in POOLED["outcomes"]
    assert all(f"{sd} ({name})" in POOLED["outcomes"] for name, sd in SPEND_SD.items())
    assert "a normal outcome (mean 10.0, sd 4.0)" in POOLED["outcomes"]
    assert "a lognormal one (mean 10.0, log-scale sd 1.0)" in POOLED["outcomes"]
    assert "['fired', 'above_fired', 'below_fired', 'above_not', 'below_not']" in POOLED["columns"]
    assert PAYING == 0.13


# --- The module still makes the rows of the file ------------------------------------------------

REGENERATED = [  # (outcome, arm players, control players, effect, share of payers or None)
    ("normal", 100, 100, 0.0, None),
    ("lognormal", 100, 100, 0.0, None),
    ("lognormal", 10_000, 10_000, 0.0, None),  # the large block, and its smaller number of runs
    ("revenue", 300, 300, 0.2, 0.03),  # the block of other payer shares
    ("revenue_heavy", 100, 100, 0.5, None),  # the effect ladder
    ("revenue_mild", 100, 100, 0.0, None),  # with the bootstrap, the dearest of these
]


EXACT = {"outcome", "arm_n", "control_n", "effect", "paying", "truth", "reps", "boot_reps", "seed"}
EXACT |= {"welch_undefined_n"}  # nobody lacks an interval in this study, in any stream


def _count_close(row: int, old: int, reps: int, path: str) -> None:
    spread = math.sqrt(2 * max(old, 1) * max(1 - old / reps, 0.01))
    assert abs(row - old) <= 4.5 * spread + 2, (path, row, old)


def _close_row(row: dict, old: dict) -> None:
    """Where the versions of numpy or scipy are not those that made the file (a random stream is
    not promised to stay the same), the settings and the columns are the same, counts agree
    within chance, the percentiles of the error within a third of the half-width of the interval
    and the other quantities within a fraction, wide because they are those of heavy tails.
    It notices a change of a count by more than about a fifth of a rate near 5%, not a smaller
    one: the exact comparison above, for the versions that made the file, is the sharp one."""
    assert list(row) == list(old)  # the same columns in the same order
    for key, value in old.items():
        if key in EXACT:
            assert row[key] == value, key
        elif key == "error":
            assert len(row[key]) == 3
            assert all(
                abs(a - b) <= 0.3 * old["half_width"] for a, b in zip(row[key], value, strict=True)
            )
        elif key == "shape":
            assert list(row[key]) == list(value)
            for who, numbers in value.items():
                for a, b in zip(row[key][who], numbers, strict=True):
                    assert (a is None) == (b is None)
                    assert a is None or a == pytest.approx(b, rel=0.35, abs=0.15), (who, a, b)
        elif key in ("welch_width", "half_width"):
            assert row[key] == pytest.approx(value, rel=0.25), key
        elif key == "criteria":
            assert list(row[key]) == list(value)
            for name, tally in value.items():
                for a, b in zip(row[key][name], tally, strict=True):
                    _count_close(a, b, old["reps"], name)
        elif key == "boot":
            assert list(row[key]) == list(value)
            assert row[key]["undefined_n"] == value["undefined_n"] == 0
            for name, boot_value in value.items():
                if name.endswith("_width"):
                    assert row[key][name] == pytest.approx(boot_value, rel=0.25), name
                elif name in ("above", "below"):
                    for a, b in zip(row[key][name], boot_value, strict=True):
                        _count_close(a, b, old["boot_reps"], name)
                else:
                    _count_close(row[key][name], boot_value, old["boot_reps"], name)
        else:
            _count_close(row[key], value, old["reps"], key)


def test_the_module_still_makes_cheap_rows_of_the_file() -> None:
    stored = [next(row for row in CELLS if _key(row) == key) for key in REGENERATED]
    cells = [Cell(*key) for key in REGENERATED]

    rows = study(
        cells, POOLED["reps"], POOLED["boot_reps"], POOLED["seed"], large_reps=POOLED["large_reps"]
    )

    if (np.__version__, scipy.__version__) == (POOLED["numpy"], POOLED["scipy"]):
        assert rows == stored
        assert [list(row) for row in rows] == [list(old) for old in stored]
    else:
        for row, old in zip(rows, stored, strict=True):
            _close_row(row, old)
    assert any("boot" in row for row in stored) and any("boot" not in row for row in stored)


def test_the_check_for_other_versions_accepts_chance_and_notices_a_real_change() -> None:
    import copy

    key = ("revenue", 300, 300, 0.2, 0.03)
    stored = next(row for row in CELLS if _key(row) == key)
    (rerun,) = study([Cell(*key)], stored["reps"], 0, 20261299)  # another seed: another stream
    rerun["seed"] = stored["seed"]
    boot = next(row for row in CELLS if "boot" in row)

    _close_row(rerun, stored)  # chance alone
    _close_row(copy.deepcopy(boot), boot)
    nudged = copy.deepcopy(boot)
    nudged["boot"]["boot_above_n"] += 12  # a count of 2,000 off by what chance gives
    nudged["boot"]["above"][1] += 3
    _close_row(nudged, boot)
    for change in (
        lambda r: r.__setitem__("welch_above_n", r["welch_above_n"] + 500),
        lambda r: r["criteria"]["kohavi"].__setitem__(0, r["criteria"]["kohavi"][0] - 900),
        lambda r: r["error"].__setitem__(1, r["error"][1] + 0.5 * r["half_width"]),
        lambda r: r["shape"]["arm"].__setitem__(1, r["shape"]["arm"][1] * 2),
        lambda r: r.__setitem__("half_width", r["half_width"] * 1.5),
        lambda r: r.__setitem__("reps", r["reps"] + 1),  # settings are exact
        lambda r: r.__setitem__("seed", r["seed"] + 1),
        lambda r: r.__setitem__("welch_undefined_n", 1),  # an interval that is missing
        lambda r: r["boot"].__setitem__("undefined_n", 1),
        lambda r: r.pop("criteria"),
        lambda r: r["boot"].__setitem__("boot_width", r["boot"]["boot_width"] * 2),
        lambda r: r["boot"]["below"].__setitem__(0, r["boot"]["below"][0] + 400),
        lambda r: r.__setitem__("extra", 1),
    ):
        changed, stored_row = copy.deepcopy(boot), boot
        change(changed)
        with pytest.raises(AssertionError):
            _close_row(changed, stored_row)
    changed = copy.deepcopy(stored)
    changed["criteria"]["kohavi"][0] -= 900
    with pytest.raises(AssertionError):
        _close_row(changed, stored)


def _within_chance(rate: float, other: float, reps: int, other_reps: int) -> bool:
    spread = math.sqrt(max(rate * (1 - rate), 1e-4) * (1 / reps + 1 / other_reps))
    return abs(rate - other) <= 4.5 * spread + 0.002


@pytest.mark.parametrize(
    "key",
    [
        ("revenue", 900, 100, 0.0, None),  # the larger arm looks better than it is
        ("revenue_heavy", 100, 900, 0.2, None),  # the control is larger and the effect is real
        ("revenue_mild", 300, 300, 0.2, None),
        ("revenue", 900, 300, 0.0, 0.03),
        ("revenue_heavy", 1000, 1000, 1.0, None),
        ("lognormal", 300, 100, 0.0, None),
    ],
    ids=lambda key: f"{key[0]}-{key[1]}-{key[2]}",
)
def test_a_rerun_of_a_cell_with_another_seed_agrees_with_the_file(key: tuple) -> None:
    (stored,) = [row for row in CELLS if _key(row) == key]
    reps = 6000

    (rerun,) = study([Cell(*key)], reps, 0, 20261299)

    for side in ("above", "below"):
        assert _within_chance(
            rerun[f"welch_{side}_n"] / reps,
            stored[f"welch_{side}_n"] / stored["reps"],
            reps,
            stored["reps"],
        ), side
    for name in ("kohavi", "kurtosis>100", "top_share>0.5"):
        if name in stored["criteria"]:
            assert _within_chance(
                rerun["criteria"][name][0] / reps,
                stored["criteria"][name][0] / stored["reps"],
                reps,
                stored["reps"],
            ), name
    assert rerun["half_width"] == pytest.approx(stored["half_width"], rel=0.1)
    assert rerun["shape"]["arm"][1] == pytest.approx(stored["shape"]["arm"][1], rel=0.1)  # median


# --- What the file shows of the normal outcome --------------------------------------------------


def test_welch_is_calibrated_for_a_normal_outcome_in_every_cell_of_the_file() -> None:
    cells = [row for row in CELLS if row["outcome"] == "normal"]
    spread = math.sqrt(0.05 * 0.95 / POOLED["reps"])

    assert len(cells) == 80
    for row in cells:
        missed = (row["welch_above_n"] + row["welch_below_n"]) / row["reps"]
        assert abs(missed - 0.05) <= 4 * spread, _key(row)
    total = sum(row["welch_above_n"] + row["welch_below_n"] for row in cells)
    assert total / sum(row["reps"] for row in cells) == pytest.approx(0.05, abs=0.001)


# --- The design text and the committed study -----------------------------------------------------

LABELS = {"revenue_mild": "mild", "revenue": "middle", "revenue_heavy": "heavy"}
SPLITS = (1, 1.5, 2, 2.5, 3, 4, 9)  # the columns of the table: larger arm : smaller arm
SIZES = (100, 300, 1000, 3000)
SCENARIOS = (  # (what the row says, effect, which arm is the larger)
    ("no effect", 0.0, "arm"),
    ("+20%, the arm larger", 0.2, "arm"),
    ("+20%, control larger", 0.2, "control"),
)


def _small(row: dict) -> int:
    return min(row["arm_n"], row["control_n"])


def _split(row: dict) -> float:
    return max(row["arm_n"], row["control_n"]) / _small(row)


def _block(row: dict) -> str:
    if row.get("paying") is not None:
        return "payer"
    if _small(row) >= module.LARGE_FROM:
        return "large"
    return "ladder" if row["effect"] in module.LADDER_EFFECTS else "main"


def _rate(row: dict, side: str | None = None) -> float:
    """The share of runs whose Welch interval missed the true difference (on one side, if told)."""
    missed = row["welch_above_n"] + row["welch_below_n"] if side is None else row[f"welch_{side}_n"]
    return missed / row["reps"]


def _rows(outcome=None, block=None, **match) -> list[dict]:
    chosen = [
        row
        for row in CELLS
        if (outcome is None or row["outcome"] == outcome)
        and (block is None or _block(row) == block)
        and all(row.get(key) == value for key, value in match.items())
    ]
    assert chosen, (outcome, block, match)
    return chosen


def _one(outcome: str, arm_n: int, control_n: int, effect: float, paying=None) -> dict:
    (row,) = [r for r in CELLS if _key(r) == (outcome, arm_n, control_n, effect, paying)]
    return row


def _cell_of(outcome: str, effect: float, larger: str, split: float, size: int) -> dict | None:
    """The cell of the main block with the larger arm `split` times `size`; None where the
    control cannot be the larger arm because the two are of one size."""
    found = [
        row
        for row in _rows(outcome, "main", effect=effect)
        if _small(row) == size
        and math.isclose(_split(row), split)
        and (row["arm_n"] >= row["control_n"]) == (larger == "arm")
    ]
    assert len(found) <= 1
    return found[0] if found else None


def _pct(value: float, places: int = 1) -> str:
    return f"{100 * value:.{places}f}%"


def _span(values, places: int = 1) -> str:
    values = list(values)
    return f"{_pct(min(values), places)} to {_pct(max(values), places)}"


def _both_ways(low: float, high: float) -> str:
    """The rate with the smallest arm first and the largest last: 'a → b'."""
    return f"{100 * low:.1f} → {100 * high:.1f}"


def _mc(rate: float, reps: int) -> float:
    return 100 * math.sqrt(rate * (1 - rate) / reps)


def _welch_table() -> str:
    caption = (
        "Share of runs (%) in which Welch's interval missed the true difference, with "
        f"{SIZES[0]} \u2192 {SIZES[-1]:,} players in the smaller arm, by the split between the "
        "arms:"
    )
    head = "| Outcome, effect | " + " | ".join(f"{s:g} to 1" for s in SPLITS) + " |"
    lines = [caption, "", head, "|---|" + "---|" * len(SPLITS)]
    for outcome, label in LABELS.items():
        for name, effect, larger in SCENARIOS:
            cells = []
            for split in SPLITS:
                low = _cell_of(outcome, effect, larger, split, SIZES[0])
                high = _cell_of(outcome, effect, larger, split, SIZES[-1])
                cells.append("same cell" if low is None else _both_ways(_rate(low), _rate(high)))
            lines.append(f"| {label}, {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _list(values, last: str = "and") -> str:
    texts = [
        v if isinstance(v, str) else f"{v:,}" if isinstance(v, int) else f"{v:g}" for v in values
    ]
    if len(texts) == 1:
        return texts[0]
    return ", ".join(texts[:-1]) + f" {last} {texts[-1]}"


def _paired(row: dict) -> tuple[int, int, int, int]:
    """Of the replications the bootstrap ran on: both missed, only Welch's, only the bootstrap's
    (above and below together), and the replications."""
    boot = row["boot"]
    both, welch_only, boot_only = (boot["above"][i] + boot["below"][i] for i in range(3))
    return both, welch_only, boot_only, row["boot_reps"]


def _bootstrap_figures() -> dict:
    rows = [row for row in CELLS if "boot" in row]
    worse = better = worse_two = better_two = 0
    for row in rows:
        _, welch_only, boot_only, _ = _paired(row)
        z = (boot_only - welch_only) / math.sqrt(welch_only + boot_only)
        worse += boot_only > welch_only
        better += boot_only < welch_only
        worse_two += z > 2
        better_two += z < -2
    both, welch_only, boot_only = (sum(_paired(row)[i] for row in rows) for i in range(3))
    widths = [row["boot"]["boot_width"] / row["boot"]["welch_width"] for row in rows]
    gap = max(
        (row["boot"]["welch_above_n"] + row["boot"]["welch_below_n"]) / row["boot_reps"]
        - (row["boot"]["boot_above_n"] + row["boot"]["boot_below_n"]) / row["boot_reps"]
        for row in rows
    )
    return {
        "cells": len(rows),
        "worse": worse,
        "better": better,
        "worse two": worse_two,
        "better two": better_two,
        "equal": len(rows) - worse - better,
        "also": both / (both + welch_only),
        "widths": (min(widths), max(widths)),
        "best gap": gap,
    }


def _boot_rates(outcome: str, arm_n: int, control_n: int, effect: float) -> tuple[float, float]:
    row = _one(outcome, arm_n, control_n, effect)
    n = row["boot_reps"]
    boot = row["boot"]
    welch = (boot["welch_above_n"] + boot["welch_below_n"]) / n
    return welch, (boot["boot_above_n"] + boot["boot_below_n"]) / n


def _stratified(row: dict, name: str) -> tuple[float, float, int, int] | None:
    """The rate of misses among the runs a warning fired in and among those it did not, and the
    number of runs in each; None where the warning does not apply to the outcome."""
    tally = row["criteria"].get(name)
    if tally is None:
        return None
    fired, above_fired, below_fired, above_not, below_not = tally
    quiet = row["reps"] - fired
    if fired == 0 or quiet == 0:
        return (math.nan, math.nan, fired, quiet)
    return ((above_fired + below_fired) / fired, (above_not + below_not) / quiet, fired, quiet)


def _adverse(name: str) -> dict:
    """Over the cells of the main block with a revenue-like outcome in which the warning fired in
    at least 200 runs and was quiet in at least 200, how often the quiet runs missed more."""
    found = higher = higher_two = lower_two = 0
    for row in CELLS:
        if _block(row) != "main" or row["outcome"] not in LABELS:
            continue
        got = _stratified(row, name)
        if got is None or min(got[2], got[3]) < 200:
            continue
        fired_rate, quiet_rate, fired, quiet = got
        p = (rate := row["welch_above_n"] + row["welch_below_n"]) / row["reps"]
        assert rate > 0
        error = math.sqrt(p * (1 - p) * (1 / fired + 1 / quiet))
        found += 1
        higher += quiet_rate > fired_rate
        higher_two += (quiet_rate - fired_rate) > 2 * error
        lower_two += (fired_rate - quiet_rate) > 2 * error
    return {"cells": found, "quiet higher": higher, "by two": higher_two, "fired by two": lower_two}


def _fired(rows: list[dict], name: str) -> float:
    return sum(r["criteria"][name][0] for r in rows) / sum(r["reps"] for r in rows)


def _pct_ceil(value: float, places: int = 1) -> str:
    """For 'at most': rounded up, so that the figure is a bound and not only a near value."""
    scale = 10**places
    return f"{math.ceil(round(100 * value * scale, 6)) / scale:.{places}f}%"


def _pct_floor(value: float, places: int = 1) -> str:
    """For 'at least': rounded down."""
    scale = 10**places
    return f"{math.floor(round(100 * value * scale, 6)) / scale:.{places}f}%"


def _percents(values, last: str = "and", sign: str = "") -> str:
    return _list([f"{sign}{round(100 * v)}%" for v in values], last)


NAMES = [f"kurtosis>{t}" for t in module.KURTOSIS_THRESHOLDS] + [
    f"top_share>{t}" for t in module.TOP_SHARE_THRESHOLDS
]
D2 = {6: 2.534, 15: 3.472}  # the mean range of that many normal draws, in standard deviations
PAYER_COMBOS = (  # (share of payers or None for the main grid's, players in the smaller arm)
    *((0.03, size) for size in (300, 1000)),
    *((None, size) for size in SIZES),
    *((0.30, size) for size in (300, 1000)),
)


def _payer_counts(outcome: str) -> list[tuple[int, float]]:
    """Players who spend in the smaller arm, and the rate, at 9 to 1 with no effect."""
    found = [
        (
            round((PAYING if share is None else share) * size),
            _rate(_one(outcome, 9 * size, size, 0.0, share)),
        )
        for share, size in PAYER_COMBOS
    ]
    return sorted(found)


def _sided_cells():
    """The cells from 3 to 1 up that the one-sided shares are worked out from, with the share
    of their misses on the side that is expected: above for no effect and for the arm the
    larger, below for the control the larger."""
    for o in LABELS:
        for effect, larger in ((0.0, "arm"), (0.2, "arm"), (0.2, "control")):
            for r in _rows(o, "main", effect=effect):
                if _split(r) < 3 or (r["arm_n"] > r["control_n"]) != (larger == "arm"):
                    continue
                missed = r["welch_above_n"] + r["welch_below_n"]
                one_side = r["welch_below_n"] if larger == "control" else r["welch_above_n"]
                yield r, one_side / missed


def _figures() -> dict:
    """Every figure the design text quotes from the committed study, worked out from the file."""
    f: dict = {}
    normal = _rows("normal")
    f["normal"] = [_rate(r) for r in normal]
    f["normal total"] = sum(r["welch_above_n"] + r["welch_below_n"] for r in normal) / sum(
        r["reps"] for r in normal
    )
    f["lognormal main"] = [_rate(r) for r in _rows("lognormal", "main")]
    f["lognormal large"] = [_rate(r) for r in _rows("lognormal", "large")]
    f["equal"] = {o: [_rate(r) for r in _rows(o, "main") if _split(r) == 1] for o in LABELS}
    equal_20 = [r for o in LABELS for r in _rows(o, "main", effect=0.2) if _split(r) == 1]
    f["equal below"] = [_rate(r, "below") for r in equal_20]
    f["equal above"] = [_rate(r, "above") for r in equal_20]
    ladder = {}
    for o in ("revenue", "revenue_heavy"):
        for effect in module.LADDER_EFFECTS:
            for size in module.LADDER_SIZES:
                ladder[o, effect, size] = _rate(_one(o, size, size, effect))
    f["ladder"] = ladder
    equal_ladder = [r for r in _rows(block="ladder") if r["arm_n"] == r["control_n"]]
    f["ladder below"] = [
        r["welch_below_n"] / (r["welch_above_n"] + r["welch_below_n"]) for r in equal_ladder
    ]
    side, cells_side = {}, []
    for o in LABELS:
        rows = [r for r in _rows(o, "main") if _split(r) >= 3]
        for key, effect, larger in (
            ("none", 0.0, "arm"),
            ("arm", 0.2, "arm"),
            ("control", 0.2, "control"),
        ):
            chosen = [
                r
                for r in rows
                if r["effect"] == effect and (r["arm_n"] > r["control_n"]) == (larger == "arm")
            ]
            above = sum(r["welch_above_n"] for r in chosen)
            below = sum(r["welch_below_n"] for r in chosen)
            side[o, key] = above / (above + below) if key != "control" else below / (above + below)
            for r in chosen:
                one_side = r["welch_below_n"] if key == "control" else r["welch_above_n"]
                cells_side.append(one_side / (r["welch_above_n"] + r["welch_below_n"]))
    f["side"] = side
    f["side cells"] = (min(cells_side), max(cells_side))
    assert sorted(share for _, share in _sided_cells()) == sorted(cells_side)
    lower = rows_3 = 0
    exceptions = []
    for o in LABELS:
        for _, effect, larger in SCENARIOS:
            for split in (3, 4, 9):
                low = _cell_of(o, effect, larger, split, SIZES[0])
                high = _cell_of(o, effect, larger, split, SIZES[-1])
                rows_3 += 1
                if _rate(high) < _rate(low):
                    lower += 1
                else:
                    exceptions.append(
                        max(_rate(_cell_of(o, effect, larger, split, size)) for size in SIZES)
                    )
    f["size"] = (lower, rows_3, max(exceptions), len(exceptions))
    f["highest"] = {o: max(_rate(r) for r in _rows(o, "main")) for o in LABELS}
    f["highest cell"] = {o: max(_rows(o, "main"), key=_rate) for o in LABELS}
    f["other highest cell"] = {
        (b, o): max(_rows(o, b), key=_rate)
        for b in ("ladder", "payer")
        for o in ("revenue", "revenue_heavy")
    }
    f["to two"] = {
        (o, larger): max(
            _rate(r)
            for r in _rows(o, "main")
            if _split(r) <= 2
            and (r["arm_n"] >= r["control_n"]) == (larger == "arm")
            and (larger == "arm" or r["effect"] == 0.2)
        )
        for o in LABELS
        for larger in ("arm", "control")
    }
    f["large 3"] = {o: [_rate(r) for r in _rows(o, "large") if _split(r) <= 3] for o in LABELS}
    f["large 9"] = {o: [_rate(r) for r in _rows(o, "large") if _split(r) == 9] for o in LABELS}
    f["payer counts"] = {o: _payer_counts(o) for o in ("revenue", "revenue_heavy")}
    f["payer large"] = {
        o: (
            _rate(_one(o, 90000, 10000, 0.0, 0.03)),  # 300 who spend among 10,000 players
            _rate(_one(o, 9000, 1000, 0.0, 0.30)),  # 300 who spend among 1,000 players
        )
        for o in ("revenue", "revenue_heavy")
    }
    f["one spender"] = heavy_tail_measures([1.0] + [0.0] * (SIZES[0] - 1)).excess_kurtosis
    near_level, high_rate = [], []
    for row, share in _sided_cells():
        (near_level if _rate(row) < 0.055 else high_rate if _rate(row) > 0.07 else []).append(share)
    f["weaker near level"] = (min(near_level), min(high_rate))
    return f


def _sentences() -> dict[str, str]:
    """The sentences of the design text that carry figures, made from the committed file.

    The design text is written around these sentences; `test_the_design_text_has_no_figure...`
    checks that it holds no figure outside them.
    """
    f, b = _figures(), _bootstrap_figures()
    reps, large, boot = POOLED["reps"], POOLED["large_reps"], POOLED["boot_reps"]
    count = {
        name: sum(_block(r) == name for r in CELLS) for name in ("main", "large", "ladder", "payer")
    }
    mild, middle, heavy = LABELS
    ladder, o3, o9 = f["ladder"], f["large 3"], f["large 9"]
    per_outcome = {sum(r["outcome"] == o for r in _rows(block="main")) for o in module.OUTCOMES}
    assert len(per_outcome) == 1
    (per_outcome,) = per_outcome
    side = lambda outcome, key: _pct(f["side"][outcome, key], 0)  # noqa: E731
    equal = {o: _span(v) for o, v in f["equal"].items()}

    def nine_to_one(outcome: str, size: int, share=None) -> str:
        return _pct(_rate(_one(outcome, 9 * size, size, 0.0, share)))

    def payers(size: int) -> str:
        shares = (module.PAYER_SHARES[0], None, module.PAYER_SHARES[1])  # None: the main grid's
        by = [_list([nine_to_one(o, size, share) for share in shares]) for o in (middle, heavy)]
        return f"{size:,} against {9 * size:,} players: {by[0]} (middle) and {by[1]} (heavy)"

    def bootstrap(outcome: str, arm_n: int, control_n: int) -> tuple[str, str]:
        welch, percentile = _boot_rates(outcome, arm_n, control_n, 0.0)
        return _pct(welch), _pct(percentile)

    def fired_share(outcome: str, size: int, name: str) -> str:
        rows = [r for r in _rows(outcome, "main", effect=0.0) if _small(r) == size]
        return _pct(_fired(rows, name))

    def by_size(outcome: str, name: str) -> str:
        return _list([fired_share(outcome, size, name) for size in SIZES])

    def kohavi_in_large(outcome: str) -> str:
        return _span(r["criteria"]["kohavi"][0] / r["reps"] for r in _rows(outcome, "large"))

    boot_rows = [r for r in CELLS if "boot" in r]
    full = [r for r in boot_rows if r["boot_reps"] == boot]
    half = [r for r in boot_rows if r["boot_reps"] != boot]
    assert {r["boot_reps"] for r in half} == {boot // 2} and len(full) + len(half) == b["cells"]
    nine_row = _one(middle, 9000, 1000, 0.0)
    nine_error = max(
        _mc(rate, nine_row["boot_reps"])
        for o in (middle, heavy)
        for rate in _boot_rates(o, 9000, 1000, 0.0)
    )
    equal_error = max(
        _mc(rate, _one(middle, 100, 100, 0.0)["boot_reps"])
        for o in (middle, heavy)
        for rate in _boot_rates(o, 100, 100, 0.0)
    )
    adverse = {name: _adverse(name) for name in NAMES}
    every_arm = {name: _adverse(name) for name in ("all:kurtosis>100", "all:top_share>0.5")}
    kk, tt = adverse["kurtosis>100"], adverse["top_share>0.5"]
    example = _one(middle, 300, 100, 0.0)
    strat = {name: _stratified(example, name) for name in ("kurtosis>100", "top_share>0.5")}
    top = {k: v for k, v in strat.items() if v is not None}
    assert len(top) == 2
    always = [r for o in (middle, heavy) for r in _rows(o)]
    lognormal_least = min(
        r["criteria"]["kohavi"][0] / r["reps"] for r in _rows("lognormal", "main")
    )
    normal_most = max(r["criteria"]["kohavi"][0] / r["reps"] for r in _rows("normal"))
    hundred_k = {o: _one(o, 100_000, 100_000, 0.0) for o in (mild, middle)}
    other = f["other highest cell"]
    ladder_top, payer_top = other["ladder", middle], other["payer", middle]
    assert _key(other["ladder", heavy])[1:4] == _key(ladder_top)[1:4]  # the same cell for both
    assert _key(other["payer", heavy])[1:4] == _key(payer_top)[1:4]
    assert _key(other["payer", heavy])[4] == _key(payer_top)[4]
    sd_3 = 3 * math.sqrt(0.05 * 0.95 / large)
    above_5 = {o: sum(rate > 0.05 + sd_3 for rate in o9[o]) for o in LABELS}
    n3, n9 = len(o3[mild]), len(o9[mild])
    noise = _mc(0.05, large)
    counts = {o: [c for c, _ in f["payer counts"][o]] for o in f["payer counts"]}
    shares_text = _percents((*module.PAYER_SHARES[:1], PAYING, *module.PAYER_SHARES[1:]))
    assert counts[middle] == counts[heavy]
    return {
        "settings": (
            f"{len(CELLS)} cells, {reps:,} replications a cell ({large:,} where the smaller arm "
            f"has {module.LARGE_FROM:,} players or more), seed {POOLED['seed']}, Monte Carlo error "
            f"{_mc(0.05, reps):.2f} points at 5% ({_mc(0.05, large):.2f} with {large:,})"
        ),
        "level": (
            f"the intervals are two-sided {100 * (1 - POOLED['alpha']):.0f}% intervals, so a run "
            f"should miss in {100 * POOLED['alpha']:.0f}% of runs"
        ),
        "bootstrap run": (
            f"its {POOLED['resamples']:,} resamples were drawn for the first {boot:,} "
            f"replications of {len(full)} cells and for the first {boot // 2:,} of the other "
            f"{len(half)}, which have more than {module.BOOT_MOST_PLAYERS:,} players in the "
            f"larger arm; the {b['cells']} cells are those of the three revenue-like outcomes "
            f"with {_list(module.BOOT_SIZES)} players in the smaller arm, at "
            f"{_list(module.BOOT_RATIOS)} to 1"
        ),
        "main grid": (
            f"a smaller arm of {_list(SIZES)} players and a larger arm "
            f"{_list(module.RATIOS, 'or')} times as large, with no effect (the arm the larger) and "
            f"with +20% (either arm the larger): {count['main']} cells, "
            f"{per_outcome} for each of the five outcomes"
        ),
        "other grids": (
            f"{count['large']} cells with {_list(module.LARGE_SIZES)} players in the smaller arm "
            f"at {_list(module.LARGE_RATIOS)} to 1 (9 to 1 only up to {module.LARGE_SIZES[1]:,}), "
            f"{count['ladder']} cells with an effect of "
            f"{_percents(module.LADDER_EFFECTS, sign='+')} (the middle and heavy outcome, "
            f"{_list(module.LADDER_SIZES)} players, {_list(module.LADDER_RATIOS)} to 1, either "
            f"arm the larger) and {count['payer']} cells in which "
            f"{_percents(module.PAYER_SHARES, 'or')} of the players spend (the middle and heavy "
            f"outcome, {_list(module.PAYER_SIZES)} players, {_list(module.PAYER_RATIOS)} to 1)"
        ),
        "normal": (
            f"{_span(f['normal'])} of runs in each of its {len(f['normal'])} cells, "
            f"{_pct(f['normal total'], 2)} over all of them"
        ),
        "lognormal": (
            f"{_span(f['lognormal main'])} of runs in the cells of the main block and "
            f"{_span(f['lognormal large'])} with {module.LARGE_FROM:,} players or more in the "
            "smaller arm"
        ),
        "equal": (
            f"{equal[mild]} of runs for the mild outcome, {equal[middle]} for the middle one and "
            f"{equal[heavy]} for the heavy one, over the {len(f['equal'][middle])} cells of each "
            f"(no effect and +20%, {_list(SIZES)} players an arm)"
        ),
        "equal below": (
            "with +20% and equal arms the misses are mostly intervals wholly below the true "
            f"difference, {_span(f['equal below'])} of runs against {_span(f['equal above'])} "
            f"wholly above (each side of an interval of this level should hold "
            f"{100 * POOLED['alpha'] / 2:.1f}%)"
        ),
        "ladder": (
            f"with {_percents(module.LADDER_EFFECTS, sign='+')} and 100 players an arm it missed "
            f"in {_pct(ladder[middle, 0.5, 100])} and {_pct(ladder[middle, 1.0, 100])} of runs for "
            f"the middle outcome and {_pct(ladder[heavy, 0.5, 100])} and "
            f"{_pct(ladder[heavy, 1.0, 100])} for the heavy one, and with 1,000 players an arm "
            f"{_pct(ladder[middle, 0.5, 1000])} and {_pct(ladder[middle, 1.0, 1000])} for the "
            f"middle outcome and {_pct(ladder[heavy, 0.5, 1000])} and "
            f"{_pct(ladder[heavy, 1.0, 1000])} for the heavy one"
        ),
        "ladder side": (
            f"{_span(f['ladder below'], 0)} of those misses are intervals wholly below the true "
            "difference"
        ),
        "table": _welch_table(),
        "rises": (
            "with no effect, and with +20% and the control the larger arm, the rate with "
            f"{SIZES[0]} players in the smaller arm rises with the split in every row of the "
            "table that has them"
        ),
        "one-sided": (
            "at 3 to 1 and beyond, with no effect "
            f"{side(mild, 'none')}, {side(middle, 'none')} and "
            f"{side(heavy, 'none')} of the misses for the mild, middle and heavy outcome lie above "
            "the true difference (the larger arm looks better than it is); with +20% and the "
            f"control the larger arm {side(mild, 'control')}, {side(middle, 'control')} and "
            f"{side(heavy, 'control')} lie below it (the arm looks worse than it is) and with the "
            f"arm the larger {side(mild, 'arm')}, {side(middle, 'arm')} and {side(heavy, 'arm')} "
            "lie above it"
        ),
        "one-sided cells": (
            "cell by cell, at 3 to 1 and beyond, the share on that side is "
            f"{_pct(f['side cells'][0], 0)} to {_pct(f['side cells'][1], 0)}"
        ),
        "to two": (
            "at 2 to 1 or less, in the main block, over no effect and +20% and the four sizes of "
            f"{SIZES[0]} to {SIZES[-1]:,} players, the rate is at most "
            f"{_pct_ceil(f['to two'][mild, 'arm'])}, {_pct_ceil(f['to two'][middle, 'arm'])} and "
            f"{_pct_ceil(f['to two'][heavy, 'arm'])} for the mild, middle and heavy outcome with "
            f"the arm the larger, and {_pct_ceil(f['to two'][mild, 'control'])}, "
            f"{_pct_ceil(f['to two'][middle, 'control'])} and "
            f"{_pct_ceil(f['to two'][heavy, 'control'])} with +20% and the control the larger"
        ),
        "size": (
            f"in {f['size'][0]} of the {f['size'][1]} entries of the table with a split of 3 to 1 "
            f"or more the rate with {SIZES[-1]:,} players in the smaller arm is below the rate "
            f"with {SIZES[0]}; in the other {f['size'][3]}, all with +20% and the arm the larger, "
            f"it is at most {_pct_ceil(f['size'][2])} at any of the four sizes"
        ),
        "highest": (
            f"{_pct(f['highest'][mild])}, {_pct(f['highest'][middle])} and "
            f"{_pct(f['highest'][heavy])} for the mild, middle and heavy outcome, in each case "
            f"with {SIZES[0]} players against {SIZES[0] * 9}, an effect of +20% and the control "
            "the larger arm"
        ),
        "other highest": (
            f"{_pct(_rate(ladder_top))} and {_pct(_rate(other['ladder', heavy]))} for the middle "
            f"and heavy outcome with an effect of +{round(100 * ladder_top['effect'])}% "
            f"({ladder_top['arm_n']} players against {ladder_top['control_n']}, the control the "
            f"larger arm; the other effect of the block gives less), and "
            f"{_pct(_rate(payer_top))} and {_pct(_rate(other['payer', heavy]))} with "
            f"{_percents((payer_top['paying'],))} of the players spending (+20%, "
            f"{payer_top['arm_n']} players against {payer_top['control_n']:,}, the control the "
            "larger arm)"
        ),
        "large": (
            f"with {module.LARGE_FROM:,} players or more in the smaller arm Welch's interval "
            f"missed in {_span(o3[mild])}, {_span(o3[middle])} and {_span(o3[heavy])} of runs for "
            f"the mild, middle and heavy outcome at 1 and 3 to 1, and {_span(o9[mild])}, "
            f"{_span(o9[middle])} and {_span(o9[heavy])} at 9 to 1 (each range is over {n3} or "
            f"{n9} cells of {large:,} runs, so that chance alone spreads it by about "
            f"{D2[n3] * noise:.1f} or {D2[n9] * noise:.1f} points; at 9 to 1 the rate is more than "
            f"three standard errors above 5% in {above_5[heavy]} of the {n9} cells of the heavy "
            f"outcome, {above_5[middle]} of the middle one and {above_5[mild]} of the mild one)"
        ),
        "payers": (
            f"with {shares_text} of the players spending and no effect, "
            + "; ".join(payers(size) for size in (300, 1000))
        ),
        "payers equal": (
            "with equal arms the rate stays within "
            f"{_span(_rate(r) for r in _rows(block='payer') if r['arm_n'] == r['control_n'])} for "
            "these shares"
        ),
        "payer counts": (
            f"at 9 to 1 with no effect and {_list(counts[middle])} players who spend in the "
            f"smaller arm (the eight cells of {reps:,} runs with the shares of {shares_text}) the "
            "interval missed in "
            f"{_list([_pct(rate) for _, rate in f['payer counts'][middle]])} of runs for the "
            f"middle outcome and {_list([_pct(rate) for _, rate in f['payer counts'][heavy]])} "
            "for the heavy one"
        ),
        "payer large": (
            "with ten times the players and a tenth of the share, the same 300 players who spend "
            f"gave similar rates: {_pct(f['payer large']['revenue'][0])} and "
            f"{_pct(f['payer large']['revenue_heavy'][0])} for the middle and heavy outcome with "
            f"{_percents((module.PAYER_SHARES[0],))} of {module.PAYER_SIZES[2]:,} players spending "
            f"({large:,} runs), against {_pct(f['payer large']['revenue'][1])} and "
            f"{_pct(f['payer large']['revenue_heavy'][1])} with "
            f"{_percents((module.PAYER_SHARES[1],))} of {module.PAYER_SIZES[1]:,}"
        ),
        "bootstrap more": (
            f"in {b['worse']} of the {b['cells']} cells with a bootstrap the percentile interval "
            f"missed in more of the replications than Welch's did, in {b['worse two']} of them by "
            "more than two standard errors (of the difference of the numbers of replications in "
            f"which only one of the two missed), in {b['better']} it missed in fewer, in "
            f"{b['better two']} of them by more than two standard errors, and in {b['equal']} "
            "equally often; in no cell did it miss less often than Welch's by more than "
            f"{100 * b['best gap']:.1f} points"
        ),
        "bootstrap nested": (
            f"{_pct(b['also'])} of the replications in which Welch's interval missed were "
            "replications in which the bootstrap's missed too"
        ),
        "bootstrap width": (
            f"its interval was {_pct(b['widths'][0], 0)} to {_pct(b['widths'][1], 0)} of the width "
            "of Welch's"
        ),
        "bootstrap equal": (
            "for the middle outcome with 100 players an arm and no effect, on the "
            f"{_one(middle, 100, 100, 0.0)['boot_reps']:,} replications that got a bootstrap "
            f"(Monte Carlo error up to {equal_error:.1f} points), Welch's interval missed in "
            f"{bootstrap(middle, 100, 100)[0]} of the replications and the bootstrap's in "
            f"{bootstrap(middle, 100, 100)[1]}; for the heavy outcome in "
            f"{bootstrap(heavy, 100, 100)[0]} and {bootstrap(heavy, 100, 100)[1]}"
        ),
        "bootstrap unequal": (
            f"with 9,000 players against 1,000 and no effect, on {nine_row['boot_reps']:,} "
            f"replications (Monte Carlo error up to {nine_error:.1f} points), the two intervals "
            f"missed in {bootstrap(middle, 9000, 1000)[0]} and {bootstrap(middle, 9000, 1000)[1]} "
            f"of the replications for the middle outcome and {bootstrap(heavy, 9000, 1000)[0]} "
            f"and {bootstrap(heavy, 9000, 1000)[1]} for the heavy one"
        ),
        "kohavi def": (
            f"|s| > 1 and n < {module.KOHAVI} s² in some arm, s being the skewness of the "
            "sample of n players (Kohavi, Deng, Longbotham and Xu, 2014)"
        ),
        "warnings tried": (
            f"excess kurtosis above {_list(module.KURTOSIS_THRESHOLDS, 'or')} and a top-1% share "
            f"above {_percents(module.TOP_SHARE_THRESHOLDS, 'or')} in either arm"
        ),
        "kohavi": (
            "Kohavi's rule fired in every run of every cell of the middle and the heavy outcome "
            f"({len(always)} cells, up to "
            f"{max(max(r['arm_n'], r['control_n']) for r in always):,} players in an arm) and of "
            "the mild outcome in the main block, in at least "
            f"{_pct_floor(lognormal_least, 2)} of the runs of the lognormal outcome's cells "
            f"there, in {kohavi_in_large(mild)} of the runs of the mild outcome's cells with "
            f"{module.LARGE_FROM:,} players or more in the smaller arm and "
            f"{kohavi_in_large('lognormal')} of the lognormal outcome's, and in at most "
            f"{_pct_ceil(normal_most)} of the runs for the normal outcome"
        ),
        "kohavi large": (
            f"with {hundred_k[mild]['arm_n']:,} players in each arm and no effect it fired in "
            f"{_pct(hundred_k[middle]['criteria']['kohavi'][0] / hundred_k[middle]['reps'], 0)} of "
            "the runs for the middle outcome, in which Welch's interval missed in "
            f"{_pct(_rate(hundred_k[middle]))}, and in "
            f"{_pct(hundred_k[mild]['criteria']['kohavi'][0] / hundred_k[mild]['reps'])} of the "
            f"runs for the mild outcome, in which it missed in {_pct(_rate(hundred_k[mild]))}"
        ),
        "by size": (
            "with no effect, all splits together, and "
            f"{_list(SIZES)} players in the smaller arm, excess kurtosis above 100 in either arm "
            f"was seen in {by_size(middle, 'kurtosis>100')} of the runs of the middle outcome and "
            f"a top-1% share above 50% in {by_size(middle, 'top_share>0.5')}; for the mild "
            f"outcome the shares are {by_size(mild, 'kurtosis>100')} for the kurtosis and "
            f"{by_size(mild, 'top_share>0.5')} for the share of the total"
        ),
        "adverse": (
            f"in the {kk['cells']} cells of the main block in which excess kurtosis above 100 in "
            "either arm fired in at least 200 runs and was quiet in at least 200, the runs "
            f"without the warning missed more often than those with it in {kk['quiet higher']} "
            f"cells, in {kk['by two']} of them by more than two standard errors, and less often "
            f"by more than two standard errors in {kk['fired by two']}; for a top-1% share above "
            f"50% the same four counts are {tt['cells']}, {tt['quiet higher']}, {tt['by two']} "
            f"and {tt['fired by two']}"
        ),
        "adverse all arms": (
            "required in all arms instead of either, the runs without the warning missed more "
            f"often than those with it in {every_arm['all:kurtosis>100']['quiet higher']} of "
            f"{every_arm['all:kurtosis>100']['cells']} cells for the kurtosis and "
            f"{every_arm['all:top_share>0.5']['quiet higher']} of "
            f"{every_arm['all:top_share>0.5']['cells']} for the share"
        ),
        "one spender": (
            f"an arm of {SIZES[0]} players of whom one spends has an excess kurtosis of "
            f"{f['one spender']:.1f}, the most an arm of that size can show (the tests search for "
            "more and find none)"
        ),
        "adverse levels": (
            f"at each of the {len(NAMES)} levels tried the runs without the warning missed more "
            f"often than those with it in "
            f"{_pct(min(a['quiet higher'] / a['cells'] for a in adverse.values()), 0)} to "
            f"{_pct(max(a['quiet higher'] / a['cells'] for a in adverse.values()), 0)} of the "
            "cells that had at least 200 runs with the warning and 200 without it "
            f"({min(a['cells'] for a in adverse.values())} to "
            f"{max(a['cells'] for a in adverse.values())} cells)"
        ),
        "example": (
            "for the middle outcome with 300 players against 100 and no effect the interval "
            f"missed in {_pct(_rate(example))} of runs; excess kurtosis above 100 in either arm "
            f"was seen in {_pct(top['kurtosis>100'][2] / example['reps'])} of all runs, and the "
            f"interval missed in {_pct(top['kurtosis>100'][0])} of the runs with that warning and "
            f"{_pct(top['kurtosis>100'][1])} of the others; for a top-1% share above 50% the "
            f"figures are {_pct(top['top_share>0.5'][2] / example['reps'])}, "
            f"{_pct(top['top_share>0.5'][0])} and {_pct(top['top_share>0.5'][1])}"
        ),
    }


def _section() -> str:
    parts = DESIGN.split("\n### 21.10 ")
    assert len(parts) == 2, "section 21.10 is not there exactly once"
    text = parts[1].split("\nDelivered in:")[0]
    assert DESIGN.index("### 21.9 ") < DESIGN.index("### 21.10 ")
    return text


def _figures_outside(text: str, phrases: list[str]) -> list[str]:
    """The figures left in the text once each sentence has been taken out of it, once."""
    import re

    for phrase in sorted(phrases, key=len, reverse=True):
        assert text.count(phrase) == 1, phrase
        text = text.replace(phrase, " ", 1)
    text = text.replace("4b-2", " ").replace("RES-008", " ").replace("top-1%", " ")
    text = re.sub(r"(?<![\d.])21\.(?:[5-9]|10)(?![\d%])", " ", text)  # a reference to a section
    text = re.sub(r"(?<!\d)(5|95)th\b", " ", text)  # the ordinal of a percentile
    return re.findall(r"\d[\d,.]*%?", text)


def test_the_design_text_holds_every_sentence_the_pooled_study_makes() -> None:
    section = _section()

    for label, phrase in _sentences().items():
        assert section.count(phrase) == 1, (label, phrase)


def test_the_design_text_has_no_figure_outside_those_sentences() -> None:
    assert _figures_outside(_section(), list(_sentences().values())) == []


def test_the_check_for_figures_outside_the_sentences_finds_a_figure_that_is_there() -> None:
    sentences = ["missed in 12.5% of runs", "the top-1% share above 50%"]
    text = f"A: {sentences[0]}. See 21.10 and 4b-2 (RES-008), 21.9. B: {sentences[1]}."

    assert _figures_outside(text, sentences) == []
    for extra, found in [
        (" It flags 80% of runs.", ["80%"]),
        (" It is 0.35 times that.", ["0.35"]),
        (" See 21.75 now.", ["21.75"]),
        (" See 21.101 now.", ["21.101"]),
        (" In 12 cases.", ["12"]),
        (" Section 21.7 of 3 now.", ["3"]),
        (" The 50th percentile.", ["50"]),
        (" Kohavi et al. (2014).", ["2014"]),
    ]:
        assert _figures_outside(text + extra, sentences) == found, extra
    with pytest.raises(AssertionError):  # a sentence that is not there, or is there twice
        _figures_outside(text, [*sentences, "not in the text"])
    with pytest.raises(AssertionError):
        _figures_outside(text + " " + sentences[0], sentences)


def test_the_sentences_are_made_from_the_file_and_change_with_it(monkeypatch) -> None:
    before = _sentences()
    moved = [dict(row) for row in CELLS]
    row = next(r for r in moved if _key(r) == ("revenue", 900, 100, 0.0, None))
    row["welch_above_n"] += 500  # 2.5 points more misses in one cell of the table
    monkeypatch.setattr(sys.modules[__name__], "CELLS", moved)

    after = _sentences()

    assert after["table"] != before["table"] and after["settings"] == before["settings"]
    assert set(after) == set(before) and len(before) >= 30


def test_the_claims_that_join_the_sentences_follow_from_the_study() -> None:
    mild, middle, heavy = LABELS
    f, b = _figures(), _bootstrap_figures()

    # the outcomes: the lognormal one has no player at zero and a skewness of about six
    skewness = (math.e**module.LOG_SD**2 + 2) * math.sqrt(math.e**module.LOG_SD**2 - 1)
    assert 5.9 < skewness < 6.5

    # equal arms with a small effect: close to or below the level, below it for the heavier tails
    assert all(max(f["equal"][o]) <= 0.052 for o in LABELS)
    assert max(f["equal"][middle]) < 0.05 and min(f["equal"][heavy]) < 0.02
    # a large effect takes that away, and the arm looks worse than it is
    assert all(rate > 0.055 for rate in f["ladder"].values()) and len(f["ladder"]) == 8
    assert min(f["ladder below"]) >= 0.8

    # the rate rises with the split, with 100 players in the smaller arm, in six rows
    rows = 0
    for outcome in LABELS:
        for _, effect, larger in (SCENARIOS[0], SCENARIOS[2]):
            rates = [
                _rate(cell)
                for split in SPLITS
                if (cell := _cell_of(outcome, effect, larger, split, SIZES[0])) is not None
            ]
            assert rates == sorted(rates) and len(set(rates)) == len(rates) >= 6
            rows += 1
    assert rows == 6

    # the misses are on one side, from three to one
    assert min(f["side"].values()) >= 0.8
    # up to two to one: close to the level with the arm the larger, a few points beyond without
    assert all(f["to two"][o, "arm"] <= 0.055 for o in LABELS)
    assert all(0.06 < f["to two"][o, "control"] <= 0.10 for o in LABELS)
    # from three to one the rate falls with size, but not in the rows with +20% and the arm larger
    exceptions = []
    for o in LABELS:
        for _, effect, larger in SCENARIOS:
            for split in (3, 4, 9):
                low = _cell_of(o, effect, larger, split, SIZES[0])
                high = _cell_of(o, effect, larger, split, SIZES[-1])
                if not _rate(high) < _rate(low):
                    exceptions.append((effect, larger))
    assert exceptions == [(0.2, "arm")] * 3
    # the highest cell of each outcome is 100 against 900, +20%, the control the larger
    for outcome, cell in f["highest cell"].items():
        assert (cell["arm_n"], cell["control_n"], cell["effect"]) == (100, 900, 0.2), outcome
        assert _rate(cell) == max(_rate(r) for r in _rows(outcome, "main"))

    # the fewer players spend, the worse the interval, in the four comparisons of the sentence
    for outcome in (middle, heavy):
        for size in (300, 1000):
            few, usual, many = (
                _rate(_one(outcome, 9 * size, size, 0.0, share)) for share in (0.03, None, 0.30)
            )
            assert few > usual > many, (outcome, size)

    # the bootstrap's interval is the narrower one in every cell, and nearly all that Welch's
    # misses it misses too; it misses more in most cells and less in none by a point
    assert b["widths"][1] < 1 <= 1.0000001 and b["widths"][0] > 0.85
    assert b["also"] > 0.95 and b["worse"] > 5 * b["better"] and b["best gap"] < 0.01

    # Kohavi's rule fired in every run of the cells the sentence says, and it fires where Welch's
    # interval is right as much as where it is not
    for outcome in (middle, heavy):
        assert all(r["criteria"]["kohavi"][0] == r["reps"] for r in _rows(outcome))
    assert all(r["criteria"]["kohavi"][0] == r["reps"] for r in _rows(mild, "main"))
    assert all(r["criteria"]["kohavi"][0] >= 0.999 * r["reps"] for r in _rows("lognormal", "main"))
    always = [r for o in (middle, heavy) for r in _rows(o)]
    assert min(_rate(r) for r in always) < 0.02 and max(_rate(r) for r in always) > 0.2
    assert any(_rate(r) < 0.055 and r["arm_n"] >= 100_000 for r in always)

    # the kurtosis and share warnings move with the size of the sample, and with the tail
    for outcome in (mild, middle):
        for name in ("kurtosis>100", "top_share>0.5"):
            shares = [
                _fired([r for r in _rows(outcome, "main", effect=0.0) if _small(r) == size], name)
                for size in SIZES
            ]
            assert max(shares) - min(shares) >= 0.05, (outcome, name)
    for name in ("kurtosis>100", "top_share>0.5"):
        by_tail = [
            _fired([r for r in _rows(o, "main", effect=0.0) if _small(r) == 300], name)
            for o in LABELS
        ]
        assert max(by_tail) - min(by_tail) >= 0.3, name

    # the bootstrap ran on half the replications exactly where the larger arm is beyond the limit
    for row in (r for r in CELLS if "boot" in r):
        beyond = max(row["arm_n"], row["control_n"]) > module.BOOT_MOST_PLAYERS
        assert row["boot_reps"] == (POOLED["boot_reps"] // 2 if beyond else POOLED["boot_reps"])
    assert sum(r["boot_reps"] < POOLED["boot_reps"] for r in CELLS if "boot" in r) == 9

    # the rate falls with the number of players who spend in the smaller arm, and not with the
    # number of players: the same eight combinations ordered by players are not in order of rate
    for outcome in (middle, heavy):
        by_payers = f["payer counts"][outcome]
        assert len(by_payers) == 8 and len({count for count, _ in by_payers}) == 8
        assert all(by_payers[i][1] > by_payers[i + 1][1] for i in range(7)), outcome
    rate = lambda share, size: _rate(_one(middle, 9 * size, size, 0.0, share))  # noqa: E731
    assert rate(0.03, 1000) > rate(None, 300) and rate(0.30, 300) > rate(None, 1000)  # not players

    # the worst cells of the other blocks are worse than those of the main block, in the cells named
    for outcome in (middle, heavy):
        top_main = max(_rate(r) for r in _rows(outcome, "main"))
        for block in ("ladder", "payer"):
            cell = f["other highest cell"][block, outcome]
            assert _rate(cell) > top_main and cell["control_n"] > cell["arm_n"]
    assert f["other highest cell"]["ladder", heavy]["effect"] == max(module.LADDER_EFFECTS)

    # cell by cell, from three to one, the misses are mostly on that side
    assert f["side cells"][0] >= 0.6
    # with +20% and equal arms the misses are mostly wholly below the true difference
    assert all(
        below > above for below, above in zip(f["equal below"], f["equal above"], strict=True)
    )
    # the warnings select the runs in which the interval is the better one, at every level tried
    for name in NAMES:
        got = _adverse(name)
        assert got["quiet higher"] >= 0.85 * got["cells"] >= 50, name
    # large arms: the mild outcome is within chance of its level, the heavy one at 9 to 1 is not
    limit = 0.05 + 3 * math.sqrt(0.05 * 0.95 / POOLED["large_reps"])
    assert all(rate < limit for rate in f["large 9"][mild] + f["large 3"][mild])
    assert all(rate > limit for rate in f["large 9"][heavy])
    # Kohavi's rule moves with the size of the sample where it moves at all
    ten_k = _one(mild, 10_000, 10_000, 0.0)["criteria"]["kohavi"][0] / 2000
    hundred_k = _one(mild, 100_000, 100_000, 0.0)["criteria"]["kohavi"][0] / 2000
    assert ten_k == 1.0 and hundred_k < 0.15

    # from three to one on, above the level for no effect and for the control the larger arm,
    # and near or below it for the treated arm the larger up to three to one (middle and heavy)
    for outcome in LABELS:
        for _, effect, larger in (SCENARIOS[0], SCENARIOS[2]):
            for split in (3, 4, 9):
                for size in SIZES:
                    assert _rate(_cell_of(outcome, effect, larger, split, size)) > 0.05
    for outcome in (middle, heavy):
        for split in (1.5, 2, 2.5, 3):
            for size in SIZES:
                assert _rate(_cell_of(outcome, 0.2, "arm", split, size)) <= 0.052
    # the same 300 who spend among ten times the players: within chance of one another
    for outcome, (many, few) in f["payer large"].items():
        error = math.sqrt(many * (1 - many) / 2000 + few * (1 - few) / 20000)
        assert abs(many - few) < 3 * error, outcome
    # one spender among 100 players is the most extreme sample of that size: a search finds none
    assert f["one spender"] == pytest.approx(SIZES[0] ** 2 / (SIZES[0] - 1) - 6)
    rng = np.random.default_rng(3)
    most = 0.0
    for _ in range(3000):
        spenders = int(rng.integers(1, 30))
        x = np.zeros(SIZES[0])
        x[:spenders] = np.exp(rng.normal(0, rng.uniform(0.1, 4), spenders))
        most = max(most, heavy_tail_measures(x.tolist()).excess_kurtosis)
    assert most <= f["one spender"] + 1e-9
    # the one-sided shares are weaker where the rate is near its level
    assert f["weaker near level"][0] < f["weaker near level"][1]
    # the same warnings in all arms: the runs without the warning missed more, in every cell
    for name in ("all:kurtosis>100", "all:top_share>0.5"):
        got = _adverse(name)
        assert got["quiet higher"] == got["cells"] >= 100 and got["fired by two"] == 0, name

    # the warnings select the runs in which the interval is the better one, in most cells
    for name in ("kurtosis>100", "top_share>0.5"):
        got = _adverse(name)
        assert got["quiet higher"] > 0.9 * got["cells"] and got["fired by two"] <= 1, name
    example = _stratified(_one(middle, 300, 100, 0.0), "kurtosis>100")
    assert example is not None and example[1] > 1.5 * example[0]


def test_an_effect_scales_the_spread_of_a_revenue_arm_and_not_that_of_a_normal_one() -> None:
    def variance(outcome: str, factor: float) -> float:
        rng = np.random.default_rng(11)
        mean = module.BASE[outcome] * factor
        return float(module.draw_arm(outcome, mean, 500, rng, 20000).variance.mean())

    assert variance("revenue_mild", 1.2) / variance("revenue_mild", 1.0) == pytest.approx(
        1.44, rel=0.1
    )
    assert variance("normal", 1.2) / variance("normal", 1.0) == pytest.approx(1.0, rel=0.03)


def test_the_readme_and_the_design_text_name_the_command_that_makes_the_file() -> None:
    command = f"python tests/pooled_simulation.py --out docs/simulations/{NAME}.json"
    in_readme = f"python tests/pooled_simulation.py --workers 4 --out docs/simulations/{NAME}.json"
    readme = (DOCS.parent / "README.md").read_text(encoding="utf-8")
    arguments = module._parser().parse_args(shlex.split(command)[2:])

    assert in_readme in readme and "design section 21.10" in readme
    assert module._parser().parse_args(shlex.split(in_readme)[2:]).workers == 4
    assert command in _section() and f"`referee/docs/simulations/{NAME}.json`" in _section()
    # the defaults of the command line are the settings of the file
    assert (arguments.reps, arguments.large_reps, arguments.boot_reps, arguments.seed) == (
        POOLED["reps"],
        POOLED["large_reps"],
        POOLED["boot_reps"],
        POOLED["seed"],
    )
    assert POOLED["command"].endswith(f"--out docs/simulations/{NAME}.json")
    nine = DESIGN.split("### 21.9 ")[1].split("### 21.10 ")[0]
    assert "Open for 4b-2, with RES-008, after the pooled study (21.10)" in nine
    assert "the gaps of the pooled study are listed in 21.10" in nine.lower()
    assert "whether the size that the rule reads is the number of players or the number of" in nine
    assert "players who spend, which the rates followed better" in nine


def test_each_interpretation_in_the_design_text_says_that_it_was_not_tested() -> None:
    section = _section()

    assert section.count("not tested separately") == 3
    assert section.count("plausible reason") == 2 and section.count("an interpretation") == 1
    assert "were not tried" in section


CLAIMS = [  # what the text says in its own words; the test of the claims makes each true
    "conservative in the total, though with a moderate effect the misses that remain are mostly "
    "on the side where the arm looks worse than it is",
    "with a large effect and equal arms it is above its level, again on that side",
    "it is above its level from three to one on when there is no effect or when the control is "
    "the larger arm, and the larger arm then looks better than it is",
    "with the treated arm the larger it stays near or below its level up to three to one for the "
    "middle and heavy outcome",
    "At nine to one with no effect the fewer players spend, the worse it is, and the number of "
    "players who spend in the smaller arm followed the rate there",
    "In the cells it was run on, the percentile bootstrap interval missed more often than "
    "Welch's and did not repair it",
    "the runs without a warning were the worse ones; Kohavi's rule fired in every run on the "
    "middle and heavy outcome",
    "so the simulation and the interval are right when the outcome is normal",
    "Welch's interval is conservative for the revenue-like outcomes when the effect is small",
    "close to or below its level in the total",
    "A large effect takes that away",
    "the arm looks worse than it is. A plausible reason",
    "Where the interval misses, it misses on one side",
    "These shares are pooled over the four sizes and weighted by the number of misses",
    "the weaker where the rate is near its level",
    "close to its level when the arm is the larger and a few points beyond it when the control is",
    "From three to one the rate falls with the size of the smaller arm, slowly",
    "The highest rates of any cell of the main block are",
    "the fewer players spend, the worse the interval is in each of these comparisons",
    "The share is observable in the export",
    "is a candidate size for RES-008 in place of the number of players",
    "The percentile interval is a slightly narrower interval that misses more often, on this "
    "family, and not a better one",
    "whether the gap between the two intervals says anything about a run was not tested",
    "On the middle and heavy outcome the rule is therefore a statement about the metric and not "
    "about the sample",
    "where it varies, with the mild and lognormal outcomes and many players, it moves with the "
    "size of the sample",
    "depend on the size of the sample as well as on the tail",
    "the absence of a warning does not say that the interval is reliable",
    "What a rule knows before it looks at the shape is the split, the sizes of the arms and the "
    "number of players who spend",
    "the rate among the runs in which a kurtosis or share warning fires is lower in nearly all of "
    "the cells counted above",
    "no range of rates is supported as the rate",
    "a mixture and metrics that are not revenue were not tried",
    "(the share of players who spend is the same in both arms)",
    "a normal outcome, for which Welch's interval is known to be nearly exact",
    "an effect that goes through the share of players who spend (conversion) and one that adds "
    "the same amount to every player were not simulated for the revenue-like outcomes",
    "An effect that lowers the arm's mean was not run",
]


def test_the_design_text_says_what_the_claims_of_the_study_are_in_these_words() -> None:
    section = " ".join(_section().split())

    for claim in CLAIMS:
        assert section.count(claim) == 1, claim
    assert "the runs without the warning missed more often" in section  # the counts behind it


def test_an_effect_goes_through_what_the_players_who_spend_spend_and_the_share_is_the_same(
    monkeypatch,
) -> None:
    calls = []
    real = module.draw_arm

    def spy(outcome, mean, n, rng, size, keep=False, paying=PAYING):
        calls.append((mean, n, paying))
        return real(outcome, mean, n, rng, size, keep, paying)

    monkeypatch.setattr(module, "draw_arm", spy)

    module.run_cell(Cell("revenue", 40, 30, 0.5, 0.05), 4, 0, 1)

    (control, arm) = calls  # control is drawn first
    assert control[1:] == (30, 0.05) and arm[1:] == (40, 0.05)  # one share for both arms
    assert control[0] == module.BASE["revenue"] and arm[0] == pytest.approx(1.5 * control[0])
