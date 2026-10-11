"""The cohort-trigger simulation measures what the rule computes (design section 21.5)."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from cohort_simulation import (
    BASE,
    LEVEL,
    NULL_SCENARIOS,
    OUTCOMES,
    Cell,
    cell_flags,
    draw,
    flags,
    means,
    p_values,
    run_cell,
)

from referee.cohort_effects import (
    NULL_FLAG_RATE_MAX,
    NULL_FLAG_RATE_MEAN,
    CohortTest,
    _scale_test,
    trigger,
)


def _real(arm: np.ndarray, control: np.ndarray) -> dict[str, np.ndarray]:
    """The same four p values from the rule's own code, replication by replication."""
    reps, k, _ = arm.shape
    out = {name: np.full(reps, np.nan) for name in ("q_abs", "s_abs", "q_log", "s_log")}
    blocks = list(range(k))
    for r in range(reps):
        treatment = {b: list(arm[r, b]) for b in blocks}
        reference = {b: list(control[r, b]) for b in blocks}
        for scale, q, s in (("absolute", "q_abs", "s_abs"), ("log_ratio", "q_log", "s_log")):
            found = _scale_test(scale, blocks, treatment, reference).heterogeneity
            if found is not None:
                out[q][r], out[s][r] = found.q_p_value, found.slope_p_value
    return out


def _real_trigger(arm: np.ndarray, control: np.ndarray, arms: int) -> np.ndarray:
    """Whether the rule's own `trigger` flags each replication."""
    reps, k, _ = arm.shape
    blocks = list(range(k))
    flagged = np.zeros(reps, bool)
    for r in range(reps):
        treatment = {b: list(arm[r, b]) for b in blocks}
        reference = {b: list(control[r, b]) for b in blocks}
        test = CohortTest(
            arm="a",
            control="c",
            metric="m",
            block_days=7,
            absolute=_scale_test("absolute", blocks, treatment, reference),
            log_ratio=_scale_test("log_ratio", blocks, treatment, reference),
        )
        flagged[r] = trigger(test, arms - 1).flagged
    return flagged


@pytest.mark.parametrize("arms", [2, 3, 5])
@pytest.mark.parametrize("outcome", OUTCOMES)
def test_the_simulated_flags_are_the_rules_own_trigger(outcome: str, arms: int) -> None:
    cell = Cell(outcome, 6, 40, arms, "fade")
    control_mean, (arm_mean, *_) = means(cell)
    rng = np.random.default_rng(13)
    control = draw(outcome, control_mean, cell.n, rng, 150)
    arm = draw(outcome, arm_mean * 1.0, cell.n, rng, 150)

    ours = flags(p_values(arm, control), cell.level)["both"]
    real = _real_trigger(arm, control, arms)

    assert (ours == real).all()
    if outcome != "binary":  # a fade is too faint for 40 binary players a cohort
        assert 10 < real.sum() < 150  # a mixture of flagged and not, so the check bites


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize("scenario", ["zero", "relative_drift", "fade"])
def test_the_vectorised_p_values_are_the_rules_own(outcome: str, scenario: str) -> None:
    cell = Cell(outcome, 5, 40, 2, scenario)
    control_mean, (arm_mean,) = means(cell)
    rng = np.random.default_rng(7)
    control = draw(outcome, control_mean, cell.n, rng, 40)
    arm = draw(outcome, arm_mean, cell.n, rng, 40)

    ours, real = p_values(arm, control), _real(arm, control)

    for name in ours:
        np.testing.assert_allclose(ours[name], real[name], rtol=1e-9, atol=0, equal_nan=True)


def test_cohorts_that_give_no_estimate_are_left_out_exactly_as_the_rule_leaves_them_out() -> None:
    rng = np.random.default_rng(11)
    cell = Cell("binary", 6, 30, 2, "zero")
    control_mean, (arm_mean,) = means(cell)
    control = draw("binary", control_mean * 0.15, cell.n, rng, 120)  # rates near 1.5%: many zeros
    arm = draw("binary", arm_mean * 0.15, cell.n, rng, 120)
    # Force the three cases: no variation, a zero mean in one arm, and everything fine.
    control[0, 1, :], arm[0, 1, :] = 0.0, 0.0
    control[1, 2, :], arm[1, 2, :] = 0.0, rng.random(30) < 0.3
    ours, real = p_values(arm, control), _real(arm, control)

    assert np.isnan(ours["q_log"]).sum() > 5  # the cases were reached
    for name in ours:
        np.testing.assert_allclose(ours[name], real[name], rtol=1e-9, atol=0, equal_nan=True)
        assert (np.isnan(ours[name]) == np.isnan(real[name])).all()


def test_the_flags_follow_the_rule_q_or_slope_on_each_scale_and_both_scales() -> None:
    p = {
        "q_abs": np.array([0.01, 0.5, 0.01, 0.5, np.nan]),
        "s_abs": np.array([0.5, 0.01, 0.5, 0.5, 0.5]),
        "q_log": np.array([0.01, 0.01, 0.5, 0.5, 0.01]),
        "s_log": np.array([0.5, 0.5, 0.5, 0.5, 0.01]),
    }

    found = flags(p, 0.025)

    assert found["absolute"].tolist() == [True, True, True, False, False]
    assert found["relative"].tolist() == [True, True, False, False, True]
    assert found["both"].tolist() == [True, True, False, False, False]
    assert found["q_both"].tolist() == [True, False, False, False, False]
    assert flags(p, 0.005)["both"].tolist() == [False] * 5  # nothing is below 0.005


def test_a_level_is_a_strict_threshold() -> None:
    p = dict.fromkeys(("q_abs", "s_abs", "q_log", "s_log"), np.array([0.025]))

    at_level, above = flags(p, 0.025), flags(p, 0.0250001)

    for name in ("q_abs", "s_abs", "q_log", "s_log", "absolute", "relative", "both", "q_both"):
        assert at_level[name].tolist() == [False], name
        assert above[name].tolist() == [True], name


# --- The streams and the scenarios ------------------------------------------------------------


def test_the_first_replications_of_a_cell_are_the_same_whatever_the_total() -> None:
    cell = Cell("poisson", 4, 30, 3, "relative_drift")

    short = cell_flags(cell, 250, seed=5)
    long = cell_flags(cell, 700, seed=5)

    for name in short:
        assert short[name].shape == (250, 2) and long[name].shape == (700, 2)
        assert (short[name] == long[name][:250]).all()


def test_a_run_is_reproducible_and_depends_on_the_seed_and_the_cell() -> None:
    cell = Cell("normal", 4, 30, 2, "zero")

    assert run_cell(cell, 500, 3) == run_cell(cell, 500, 3)
    assert run_cell(cell, 500, 3) != run_cell(cell, 500, 4)
    assert run_cell(cell, 500, 3) != run_cell(Cell("normal", 4, 30, 2, "relative"), 500, 3)


def test_the_level_is_divided_by_the_number_of_non_control_arms() -> None:
    from referee.cohort_effects import TRIGGER_LEVEL

    assert LEVEL == TRIGGER_LEVEL == 0.025
    assert Cell("normal", 4, 30, 2, "zero").level == LEVEL
    assert Cell("normal", 4, 30, 3, "zero").level == LEVEL / 2
    assert Cell("normal", 4, 30, 5, "zero").level == LEVEL / 4


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_each_outcome_is_drawn_with_the_mean_it_is_given(outcome: str) -> None:
    mean = np.array([BASE[outcome], 2 * BASE[outcome] if outcome != "binary" else 0.3])
    sample = draw(outcome, mean, 400, np.random.default_rng(1), 200)

    assert sample.shape == (200, 2, 400)
    observed = sample.mean(axis=(0, 2))
    np.testing.assert_allclose(observed, mean, rtol=0.03)


def test_the_outcomes_have_the_shapes_they_are_named_for() -> None:
    rng = np.random.default_rng(2)
    rows = {o: draw(o, np.array([BASE[o]]), 4000, rng, 50).reshape(-1) for o in OUTCOMES}

    assert rows["normal"].std() == pytest.approx(4.0, rel=0.03)
    assert rows["poisson"].var() == pytest.approx(BASE["poisson"], rel=0.05)
    assert set(np.unique(rows["binary"])) == {0.0, 1.0}
    skew = ((rows["lognormal"] - rows["lognormal"].mean()) ** 3).mean() / rows[
        "lognormal"
    ].std() ** 3
    assert skew > 3 and (rows["lognormal"] > 0).all()
    assert (rows["poisson"] == np.round(rows["poisson"])).all()


def test_the_scenarios_set_the_control_and_arm_means_they_describe() -> None:
    def pair(scenario: str, outcome: str = "normal", k: int = 5):
        control, (arm,) = means(Cell(outcome, k, 30, 2, scenario))
        return control, arm

    base = BASE["normal"]
    control, arm = pair("zero")
    assert (control == base).all() and (arm == control).all()
    control, arm = pair("relative")
    assert (control == base).all() and arm == pytest.approx(base * 1.2)
    control, arm = pair("relative_drift")
    assert control[0] == pytest.approx(0.7 * base) and control[-1] == pytest.approx(1.3 * base)
    assert arm == pytest.approx(control * 1.2)
    control, arm = pair("absolute_drift")
    assert arm - control == pytest.approx(0.2 * base)
    control, arm = pair("fade")
    assert (control == base).all()
    assert arm[0] == pytest.approx(1.4 * base) and arm[-1] == pytest.approx(base)
    assert np.diff(arm / control).max() < 0
    assert means(Cell("binary", 4, 30, 3, "relative"))[1][1] == pytest.approx([0.12] * 4)
    with pytest.raises(ValueError, match="unknown scenario"):
        means(Cell("normal", 4, 30, 2, "wobble"))
    with pytest.raises(ValueError, match="unknown outcome"):
        draw("cauchy", np.array([1.0]), 5, np.random.default_rng(0), 2)


def test_every_variant_of_a_three_arm_cell_has_its_own_draws() -> None:
    cell = Cell("normal", 4, 100, 3, "zero")
    found = cell_flags(cell, 2000, seed=9)

    both = found["both"]
    assert both.shape == (2000, 2)
    assert abs(float(np.corrcoef(both[:, 0], both[:, 1])[0, 1])) < 0.3  # shared control only
    assert not math.isclose(float(both[:, 0].mean()), 0.0)


# --- The committed study, the design text, and a re-run of some of its cells ----------------------

DOCS = Path(__file__).resolve().parent.parent / "docs"
DESIGN = (DOCS / "design/2026-09-28-referee-experiment-review-design.md").read_text(
    encoding="utf-8"
)
NULL = json.loads((DOCS / "simulations/cohort_trigger_null.json").read_text(encoding="utf-8"))
FADE = json.loads((DOCS / "simulations/cohort_trigger_fade.json").read_text(encoding="utf-8"))


def _cells(study: dict, **match):
    keep = lambda value, wanted: value in wanted if isinstance(wanted, tuple) else value == wanted  # noqa: E731
    return [c for c in study["cells"] if all(keep(c[k], v) for k, v in match.items())]


def _percent(value: float) -> str:
    return f"{100 * value:.2f}%"


def test_the_study_covers_the_whole_grid_with_the_settings_it_says() -> None:
    assert (NULL["reps"], NULL["seed"], FADE["reps"], FADE["seed"]) == (5000, 20261211) * 2
    assert len(NULL["cells"]) == 4 * 4 * 3 * 2 * 4 and len(FADE["cells"]) == 4 * 4 * 3 * 2
    assert {c["scenario"] for c in NULL["cells"]} == set(NULL_SCENARIOS)
    assert {c["scenario"] for c in FADE["cells"]} == {"fade"}
    assert {c["reps"] for c in NULL["cells"] + FADE["cells"]} == {5000}
    assert (
        len({(c["outcome"], c["cohorts"], c["n"], c["arms"], c["scenario"]) for c in NULL["cells"]})
        == 384
    )


def test_the_design_text_quotes_the_figures_the_committed_study_holds() -> None:
    amendment = DESIGN.split("\n## 21. Amendment")[1]
    stable = _cells(NULL, arms=2, scenario=("zero", "relative"))
    normal_poisson = [c for c in stable if c["outcome"] in ("normal", "poisson")]
    drift_relative = _cells(NULL, arms=2, scenario="relative_drift")
    drift_absolute = _cells(NULL, arms=2, scenario="absolute_drift")
    three = _cells(NULL, arms=3)
    lognormal = _cells(NULL, arms=2, scenario="zero", outcome="lognormal")
    binary_small = [c for c in stable if c["outcome"] == "binary" and c["n"] == 30]
    mean = lambda cells, key: sum(c[key] for c in cells) / len(cells)  # noqa: E731

    quoted = {
        "mean": _percent(mean(stable, "both")),
        "max": _percent(max(c["both"] for c in stable)),
        "mean of normal and Poisson": _percent(mean(normal_poisson, "both")),
        "absolute alone under drift": f"{100 * max(c['absolute'] for c in drift_relative):.1f}%",
        "relative alone under drift": f"{100 * max(c['relative'] for c in drift_absolute):.1f}%",
        "three arms, an arm": _percent(max(c["both"] for c in three)),
        "three arms, any arm": _percent(max(c["any_arm_both"] for c in three)),
        "three arms, mean": _percent(mean(three, "any_arm_both")),
        "relative alone, lognormal": f"{100 * max(c['relative'] for c in lognormal):.1f}%",
        "binary, small cohorts": _percent(mean(binary_small, "both")),
    }
    for label, text in quoted.items():
        assert text.replace(".00%", "%") in amendment or text in amendment, (label, text)
    assert sum(c["both"] <= 0.05 for c in stable) == 95 and len(stable) == 96
    assert max(c["both"] for c in drift_relative) == pytest.approx(0.04, abs=5e-5)
    assert max(c["both"] for c in drift_absolute) == pytest.approx(0.035, abs=5e-5)
    assert "holds the trigger to 4.0% and 3.5% at most" in amendment
    assert max(c["both"] for c in lognormal) < 0.0475


def test_the_null_flag_rates_the_findings_quote_are_the_mean_and_maximum_of_the_study() -> None:
    stable = _cells(NULL, arms=2, scenario=("zero", "relative"))
    rates = [c["both"] for c in stable]

    assert len(rates) == 96
    assert NULL_FLAG_RATE_MEAN == round(sum(rates) / len(rates), 4)
    assert NULL_FLAG_RATE_MAX == max(rates)


def test_the_design_text_quotes_the_power_figures_the_committed_study_holds() -> None:
    amendment = DESIGN.split("\n## 21. Amendment")[1]
    row = {
        o: _cells(FADE, arms=2, outcome=o, cohorts=8, n=100)[0]
        for o in ("normal", "poisson", "lognormal", "binary")
    }
    both = [f"{100 * row[o]['both']:.1f}%".replace("100.0%", "100%") for o in row]
    q_only = [f"{100 * row[o]['q_both']:.1f}%" for o in row]
    absolute = [f"{100 * row[o]['absolute']:.1f}%".replace("100.0%", "100%") for o in row]

    assert both == ["100%", "95.8%", "34.6%", "6.1%"]
    wording = (
        "flags 100% of runs for the normal outcome, 95.8% for the Poisson, "
        "34.6% for the lognormal and 6.1% for the binary"
    )
    assert wording in amendment
    assert q_only == ["99.5%", "75.9%", "13.4%", "1.6%"]
    assert "Q alone on both scales would flag 99.5%, 75.9%, 13.4% and 1.6%" in amendment
    assert absolute == ["100%", "98.3%", "37.3%", "11.0%"]
    assert "the absolute scale alone would flag 100%, 98.3%, 37.3% and 11.0%" in amendment


CHECKED = [
    (Cell("normal", 4, 100, 2, "zero"), ("both", "absolute", "relative")),
    (Cell("poisson", 8, 100, 2, "zero"), ("both", "q_both")),
    (Cell("normal", 8, 100, 3, "zero"), ("both", "any_arm_both")),
    (Cell("lognormal", 8, 30, 2, "zero"), ("both", "relative")),
    (Cell("normal", 8, 100, 2, "relative_drift"), ("both", "absolute")),
    (Cell("normal", 8, 100, 2, "absolute_drift"), ("both", "relative")),
    (Cell("poisson", 8, 100, 2, "fade"), ("both", "q_both", "absolute")),
]


@pytest.mark.parametrize(("cell", "names"), CHECKED, ids=lambda x: getattr(x, "scenario", ""))
def test_a_rerun_of_a_cell_agrees_with_the_committed_study(
    cell: Cell, names: tuple[str, ...]
) -> None:
    study = FADE if cell.scenario == "fade" else NULL
    (stored,) = _cells(
        study,
        outcome=cell.outcome,
        cohorts=cell.cohorts,
        n=cell.n,
        arms=cell.arms,
        scenario=cell.scenario,
    )
    reps = 2000
    rerun = run_cell(cell, reps, seed=20261299)  # another seed: an independent sample

    for name in names:
        p = stored[name]
        spread = math.sqrt(max(p * (1 - p), 1e-4) * (1 / reps + 1 / stored["reps"]))
        assert abs(rerun[name] - p) <= 4.5 * spread + 0.002, (name, rerun[name], p)
