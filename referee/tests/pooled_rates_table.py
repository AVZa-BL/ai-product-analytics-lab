"""Make `src/referee/pooled_rates_table.py` from the committed pooled-effect study.

    python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py

RES-008 quotes how often Welch's 95% interval missed the true difference in the cases the study
simulated (design sections 21.10 and 21.11). The package cannot read `docs/`, so the rates it
quotes are copied into the generated module, one row for each case that a reader's own
comparison can be placed against: the effects of the cases (`small`: none and +20%; `large`: +50%
and +100%), which arm was the larger (`equal`, `arm` or `control`), the split between the arms
(a fraction), the number of players who spend in the smaller arm, the lowest and highest rate
over the cells of that case, how many cells, how many tail weights, the fewest runs a cell
had, and how many of its cells have no effect with unequal arms (such a cell is a cell of both
the `arm` and the `control` case, so a range read both ways round must count it once).
Rates are whole numbers of 1/100,000 (a cell holds 20,000 or 2,000 runs, so a rate is exact in
that unit). A test runs this command and fails if the committed module differs.
"""

import json
import sys
from fractions import Fraction
from pathlib import Path

SOURCE = "docs/simulations/pooled_effect_heavy.json"
REVENUE_LIKE = ("revenue_mild", "revenue", "revenue_heavy")
SMALL_EFFECTS = (0.0, 0.2)
LARGE_EFFECTS = (0.5, 1.0)
UNIT = 100_000  # rates are whole numbers of 1/UNIT
PAYER_SHARE = 0.13  # the share of players who spend in a cell that does not say


def _rate(row: dict) -> int:
    missed = row["welch_above_n"] + row["welch_below_n"]
    scaled, remainder = divmod(missed * UNIT, row["reps"])
    if remainder:
        raise ValueError(f"a rate of {missed} in {row['reps']} is not a whole number of 1/{UNIT}")
    return scaled


def _cases(row: dict) -> list[tuple[str, str]]:
    """The (effects, larger arm) cases a cell of the study belongs to.

    With no effect the two arms are drawn alike, so a cell with the arm the larger is also a
    cell with the control the larger, seen the other way round.
    """
    arm, control, effect = row["arm_n"], row["control_n"], row["effect"]
    if effect in SMALL_EFFECTS:
        effects = "small"
    elif effect in LARGE_EFFECTS:
        effects = "large"
    else:
        raise ValueError(f"an effect of {effect} is in no case")
    if arm == control:
        return [(effects, "equal")]
    if arm > control:
        return [(effects, "arm")] + ([(effects, "control")] if effect == 0.0 else [])
    if effect == 0.0:
        raise ValueError("a cell with no effect and the control the larger arm: the study has none")
    return [(effects, "control")]


def table_rows(data: dict) -> list[tuple]:
    """One row for each case of the revenue-like cells of the study, in a fixed order."""
    found: dict[tuple, list[dict]] = {}
    for row in data["cells"]:
        if row["outcome"] not in REVENUE_LIKE:
            continue
        smaller = min(row["arm_n"], row["control_n"])
        split = Fraction(max(row["arm_n"], row["control_n"]), smaller)
        payers = round(row.get("paying", PAYER_SHARE) * smaller)
        for effects, larger in _cases(row):
            found.setdefault((effects, larger, split, payers), []).append(row)
    order = {"small": 0, "large": 1}, {"equal": 0, "arm": 1, "control": 2}
    rows = []
    for (effects, larger, split, payers), cells in sorted(
        found.items(), key=lambda kv: (order[0][kv[0][0]], order[1][kv[0][1]], kv[0][2], kv[0][3])
    ):
        rates = [_rate(cell) for cell in cells]
        rows.append(
            (
                effects,
                larger,
                split.numerator,
                split.denominator,
                payers,
                min(rates),
                max(rates),
                len(cells),
                len({cell["outcome"] for cell in cells}),
                min(cell["reps"] for cell in cells),
                sum(1 for cell in cells if cell["effect"] == 0.0 and larger != "equal"),
            )
        )
    return rows


def _literal(row: tuple) -> str:
    """A row as `ruff format` writes a tuple: double quotes, one space after each comma."""
    return "(" + ", ".join(f'"{x}"' if isinstance(x, str) else str(x) for x in row) + ")"


def render(data: dict) -> str:
    """The generated module as text, in the form `ruff format` leaves alone."""
    lines = [
        '"""Welch miss rates of the pooled-effect study, for RES-008. GENERATED: do not edit.',
        "",
        f"Made from {SOURCE} (seed {data['seed']}) by",
        "",
        "    python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py",
        "",
        "A test runs that command and fails if this file differs. `referee.pooled_rates` explains",
        "the rows and looks cases up.",
        '"""',
        "",
        f"UNIT = {UNIT}  # a rate is a whole number of 1/UNIT",
        f'SOURCE = "{SOURCE}"',
        f"SEED = {data['seed']}",
        "",
        "# (effects, larger arm, split numerator, split denominator, players who spend in the",
        "#  smaller arm, lowest rate, highest rate, cells, tail weights, fewest runs in a cell,",
        "#  cells with no effect and unequal arms, which are in both `arm` and `control` rows)",
        "ROWS = (",
    ]
    lines += [f"    {_literal(row)}," for row in table_rows(data)]
    lines += [")", ""]
    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data = json.loads((root / SOURCE).read_text(encoding="utf-8"))
    sys.stdout.write(render(data))


if __name__ == "__main__":
    main()
