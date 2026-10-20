"""The committed pooled-effect study (design section 21.10): that it is what the module makes."""

import json
import math
import shlex
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

pytestmark = pytest.mark.study  # re-runs simulations; run with `pytest -m study`

DOCS = Path(__file__).resolve().parent.parent / "docs"
NAME = "pooled_effect_heavy"
TEXT = (DOCS / f"simulations/{NAME}.json").read_text(encoding="utf-8")
POOLED = json.loads(TEXT)
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


# --- What the committed study shows --------------------------------------------------------------

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


NAMES = [f"kurtosis>{t}" for t in module.KURTOSIS_THRESHOLDS] + [
    f"top_share>{t}" for t in module.TOP_SHARE_THRESHOLDS
]
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
    """The figures of the committed study that its claims rest on, worked out from the file."""
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
