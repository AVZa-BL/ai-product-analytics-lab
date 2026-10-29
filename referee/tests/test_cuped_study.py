"""The committed CUPED study (design section 29): that it is what the module makes."""

import json
from pathlib import Path

import cuped_simulation as module
import pytest

ROOT = Path(__file__).resolve().parent.parent
STORED = json.loads((ROOT / "docs" / "simulations" / "cuped.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.study


def test_a_cell_of_the_variance_study_is_made_again_exactly() -> None:
    stored = next(r for r in STORED["variance"] if (r["rho"], r["n"]) == (0.7, 200))
    index = [(r, n) for r in module.RHOS for n in module.SIZES].index((0.7, 200))

    cell = module._cell(
        lambda rng: module._normal_pair(rng, 0.7, 200, effect=module.EFFECT),
        STORED["reps"],
        module.EFFECT,
        module.SEED + index,
    )

    assert cell["variance_ratio"] == stored["variance_ratio"]
    assert cell["adjusted"] == stored["adjusted"]


def test_the_stored_study_says_what_the_design_text_relies_on() -> None:
    for row in STORED["variance"]:
        assert row["variance_ratio"] == pytest.approx(row["theory"], abs=0.05)
        assert row["adjusted"]["coverage"] == pytest.approx(0.95, abs=0.012)
    leaks = {r["shift"]: r for r in STORED["leaking"]}
    assert leaks[0.0]["balance_flag_rate"] < 0.005 and leaks[0.25]["balance_flag_rate"] > 0.95
    # a small leak hurts coverage far more often than the balance check notices it
    assert leaks[0.1]["adjusted"]["coverage"] < 0.5 and leaks[0.1]["balance_flag_rate"] < 0.15
