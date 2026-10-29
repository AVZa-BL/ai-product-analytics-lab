"""The covariate adjustment (CUPED, design section 29): the statistic, and what the review does."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import statsmodels.api as sm
import yaml
from scipy import stats

from referee.cli import main
from referee.data import load_export, parse_utc
from referee.methods import NoVariationError, StatsError, cuped_difference, welch_difference
from referee.monitor import monitor_report
from referee.results import ResultsContext, effect_table
from referee.review import review_context
from referee.spec import ExperimentSpec

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "tests" / "data" / "hybrid_offer_page_5000"
EXAMPLE = ROOT / "examples" / "offer-page-results.yaml"
COMMON = ("--experiment-id", "hybrid_offer_page", "--as-of", "2026-06-30T00:00:00Z")


def sample(seed: int, n1: int, n0: int, rho: float = 0.6, effect: float = 1.0):
    rng = np.random.default_rng(seed)
    x1, x0 = rng.normal(5, 2, n1), rng.normal(5, 2, n0)
    y1 = 3 + 2 * rho * (x1 - 5) + effect + rng.normal(0, 3, n1)
    y0 = 3 + 2 * rho * (x0 - 5) + rng.normal(0, 1.5, n0)
    return y1, x1, y0, x0


@pytest.mark.parametrize(("seed", "n1", "n0"), [(1, 400, 500), (2, 60, 300), (3, 25, 25)])
def test_the_estimate_and_its_robust_standard_error_are_those_of_the_regression(
    seed, n1, n0
) -> None:
    y1, x1, y0, x0 = sample(seed, n1, n0)
    got = cuped_difference(y1, x1, y0, x0)

    y, x = np.r_[y1, y0], np.r_[x1, x0]
    design = np.column_stack([np.ones(len(y)), np.r_[np.ones(n1), np.zeros(n0)], x - x.mean()])
    fit = sm.OLS(y, design).fit(cov_type="HC2")

    assert got.difference == pytest.approx(fit.params[1], rel=1e-9)
    assert got.std_error == pytest.approx(fit.bse[1], rel=1e-9)
    assert got.theta == pytest.approx(fit.params[2], rel=1e-9)
    assert got.degrees_of_freedom == n1 + n0 - 3
    margin = got.std_error * stats.t.ppf(0.975, n1 + n0 - 3)
    assert (got.ci_low, got.ci_high) == pytest.approx(
        (got.difference - margin, got.difference + margin)
    )


def test_the_difference_is_the_mean_difference_less_one_pooled_slope_times_the_covariate_gap() -> (
    None
):
    y1, x1, y0, x0 = sample(4, 300, 350)
    got = cuped_difference(y1, x1, y0, x0)

    cy = np.r_[y1 - y1.mean(), y0 - y0.mean()]
    cx = np.r_[x1 - x1.mean(), x0 - x0.mean()]
    slope = (cx @ cy) / (cx @ cx)
    assert got.theta == pytest.approx(slope, rel=1e-9)
    assert got.difference == pytest.approx(
        (y1.mean() - y0.mean()) - slope * (x1.mean() - x0.mean()), rel=1e-9
    )

    # one slope, not contaminated by the treatment: a bigger true effect moves the estimate by
    # the same amount and leaves the slope, the correlation and the standard error alone
    bigger = cuped_difference(y1 + 5.0, x1, y0, x0)
    assert bigger.difference == pytest.approx(got.difference + 5.0, rel=1e-9)
    assert (bigger.theta, bigger.correlation, bigger.std_error) == pytest.approx(
        (got.theta, got.correlation, got.std_error)
    )

    # the covariate is centred: its origin and unit change nothing that matters
    shifted = cuped_difference(y1, x1 + 100.0, y0, x0 + 100.0)
    assert shifted.difference == pytest.approx(got.difference, rel=1e-9)
    assert shifted.std_error == pytest.approx(got.std_error, rel=1e-9)
    scaled = cuped_difference(y1, x1 * 4, y0, x0 * 4)
    assert scaled.difference == pytest.approx(got.difference, rel=1e-9)
    assert scaled.theta == pytest.approx(got.theta / 4, rel=1e-9)


def test_the_variance_that_is_left_is_one_minus_rho_squared_on_a_large_sample() -> None:
    rho = 0.6
    rng = np.random.default_rng(5)
    n = 40_000
    x1, x0 = rng.standard_normal(n), rng.standard_normal(n)
    y1 = rho * x1 + np.sqrt(1 - rho**2) * rng.standard_normal(n)
    y0 = rho * x0 + np.sqrt(1 - rho**2) * rng.standard_normal(n)

    got = cuped_difference(y1, x1, y0, x0)
    welch = welch_difference(y1, y0)

    assert got.correlation == pytest.approx(rho, abs=0.01)
    assert (got.std_error / welch.std_error) ** 2 == pytest.approx(1 - rho**2, abs=0.015)


@pytest.mark.parametrize(
    ("args", "error", "fragment"),
    [
        (([1.0, 2, 3], [4.0, 4, 4], [2.0, 3, 4], [4.0, 4, 4]), NoVariationError, "does not vary"),
        (([1.0, 2, 3], [1.0, 2], [2.0, 3, 4], [1.0, 2, 3]), StatsError, "each outcome needs"),
        (([1.0], [1.0], [2.0, 3, 4], [1.0, 2, 3]), StatsError, "at least 2 players"),
        (([1.0, 2], [1.0, 2], [2.0, 3], [1.0, float("nan")]), StatsError, "finite"),
    ],
)
def test_input_that_allows_no_adjustment_is_refused_with_the_reason(args, error, fragment) -> None:
    with pytest.raises(error, match=fragment):
        cuped_difference(*args)


def test_a_covariate_the_treatment_moved_is_flagged_by_the_balance_test() -> None:
    rng = np.random.default_rng(6)
    n = 1000
    z1, z0 = rng.standard_normal(n), rng.standard_normal(n)
    y1 = 0.7 * z1 + rng.standard_normal(n) + 0.5
    y0 = 0.7 * z0 + rng.standard_normal(n)

    honest = cuped_difference(y1, z1, y0, z0)
    leaking = cuped_difference(y1, z1 + 0.5, y0, z0)

    assert honest.balance_p_value > 0.001 > leaking.balance_p_value
    # the adjusted estimate has lost about slope x shift of the real effect (here 0.5 - 0.35)
    assert leaking.difference == pytest.approx(honest.difference - 0.7 * 0.5, abs=0.1)


# --- in the review ---------------------------------------------------------------------------


def lab_spec(**design) -> ExperimentSpec:
    """The results example for sessions (a metric the lab's pre-period predicts), with a
    covariate named in `design`."""
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw["primary_metric"] = {
        "name": "sessions_7d",
        "kind": "continuous",
        "baseline": 4.5,
        "baseline_std": 3.2,
    }
    raw["guardrails"] = []
    raw["design"].update(design)
    return ExperimentSpec.from_dict(raw)


def context(spec: ExperimentSpec) -> ResultsContext:
    data = load_export(LAB, "hybrid_offer_page")
    return ResultsContext.of(spec, replace(data, exported_at=parse_utc("2026-06-30T00:00:00Z")))


def test_the_adjusted_estimate_sits_beside_the_unadjusted_one_with_the_variance_left() -> None:
    table = effect_table(context(lab_spec(pre_period_covariate="sessions_pre_7d")))

    assert table["covariate"]["applied"] and table["covariate"]["registered"]
    assert table["covariate"]["balance_flagged_arms"] == []
    for row in table["arms"]:
        adjusted = row["adjusted"]
        assert "difference" in row and "difference" in adjusted  # both are there
        # rho of the lab's sessions with their pre-period is 0.57: a third of the variance goes
        assert adjusted["correlation"] == pytest.approx(0.57, abs=0.03)
        assert adjusted["variance_ratio"] == pytest.approx(
            1 - adjusted["correlation"] ** 2, abs=0.02
        )
        assert adjusted["ci_high"] - adjusted["ci_low"] < row["ci_high"] - row["ci_low"]
        assert adjusted["balance_flagged"] is False


def test_a_covariate_that_predicts_nothing_changes_nothing_and_the_report_says_so() -> None:
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw["design"]["pre_period_covariate"] = "revenue_usd_pre_7d"  # the lab's revenue: rho -0.01
    table = effect_table(context(ExperimentSpec.from_dict(raw)))

    for row in table["arms"]:
        assert abs(row["adjusted"]["correlation"]) < 0.06
        assert row["adjusted"]["variance_ratio"] == pytest.approx(1.0, abs=0.04)
    assert table["covariate"]["metric_family"] == "revenue_like"


def test_a_spec_without_a_covariate_has_no_covariate_keys_in_its_effect() -> None:
    table = effect_table(context(lab_spec()))

    assert "covariate" not in table and all("adjusted" not in row for row in table["arms"])


@pytest.mark.parametrize(
    ("declared", "reason"),
    [
        ("the primary metric measured before exposure", "column_missing"),
        ("scenario_run_id", "column_not_numeric"),
        ("sessions_7d", "is_an_outcome"),
        ("revenue_usd_7d", "is_an_outcome"),
    ],
)
def test_a_covariate_that_cannot_be_used_is_reported_with_its_reason_and_never_refuses(
    declared: str, reason: str
) -> None:
    ctx = context(lab_spec(pre_period_covariate=declared))
    table = effect_table(ctx)

    assert table["covariate"]["applied"] is False and table["covariate"]["reason"] == reason
    assert all("adjusted" not in row for row in table["arms"])
    # the unadjusted estimate is exactly what it is without the covariate
    assert table["arms"] == effect_table(context(lab_spec()))["arms"]


def test_the_covariate_may_not_be_the_primary_metrics_own_column() -> None:
    spec = lab_spec(pre_period_covariate="sessions_pre_7d")
    raw = spec.to_dict()
    raw["primary_metric"]["column"] = "sessions_pre_7d"

    table = effect_table(context(ExperimentSpec.from_dict(raw)))

    assert table["covariate"]["reason"] == "is_the_metric_itself"


def leaking_export(tmp_path: Path) -> Path:
    """The lab export with variant_b's pre-period sessions raised by 2: a 'pre-period' measure
    that the offer moved."""
    export = tmp_path / "export"
    export.mkdir()
    for name in (
        "experiment_assignments.csv",
        "experiment_exposures.csv",
        "experiment_outcomes.csv",
    ):
        (export / name).write_bytes((LAB / name).read_bytes())
    arm = {
        r["player_id"]: r["arm"]
        for r in csv.DictReader((LAB / "experiment_assignments.csv").open())
    }
    rows = list(csv.DictReader((export / "experiment_outcomes.csv").open()))
    for row in rows:
        if arm[row["player_id"]] == "variant_b":
            row["sessions_pre_7d"] = str(int(row["sessions_pre_7d"]) + 2)
    with (export / "experiment_outcomes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return export


def test_a_covariate_the_treatment_moved_is_flagged_in_the_review_and_the_report_says_not_to_read(
    capsys, tmp_path: Path
) -> None:
    export = leaking_export(tmp_path)
    spec = lab_spec(pre_period_covariate="sessions_pre_7d")

    table = effect_table(ResultsContext.of(spec, load_export(export, "hybrid_offer_page")))
    assert table["covariate"]["balance_flagged_arms"] == ["variant_b"]
    assert table["arms"][1]["adjusted"]["balance_flagged"] is False  # variant_c is untouched

    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec.to_dict(), sort_keys=False), encoding="utf-8")
    main(["review-results", str(path), str(export), *COMMON])
    text = capsys.readouterr().out
    assert "NOT TO BE READ: the covariate's mean differs between control and variant_b" in text


def test_the_balance_level_is_shared_between_the_arms_compared_with_control(monkeypatch) -> None:
    from referee import results
    from referee.methods import CupedDifference

    def fake(*args, **kwargs):
        return CupedDifference(
            n_treatment=10,
            n_control=10,
            difference=1.0,
            std_error=1.0,
            degrees_of_freedom=17,
            t_statistic=1.0,
            p_value=0.3,
            ci_low=0.0,
            ci_high=2.0,
            confidence=0.95,
            theta=0.5,
            correlation=0.5,
            covariate_difference=0.1,
            balance_p_value=0.0007,
        )

    monkeypatch.setattr(results, "cuped_difference", fake)
    unadjusted = results._Compared(0.0, 1.0, 1.0, 0.0, 2.0, 0.95, 0.3, 1.0)

    one = results._adjusted_estimate(([0.0], [0.0]), ([0.0], [0.0]), unadjusted, 1, "bonferroni")
    two = results._adjusted_estimate(([0.0], [0.0]), ([0.0], [0.0]), unadjusted, 2, "bonferroni")

    assert (one["balance_flagged"], two["balance_flagged"]) == (True, False)  # 0.001 and 0.0005


def test_the_unadjusted_estimate_is_the_same_with_and_without_the_covariate() -> None:
    plain = effect_table(context(lab_spec()))["arms"]
    adjusted = effect_table(context(lab_spec(pre_period_covariate="sessions_pre_7d")))["arms"]

    assert [{k: v for k, v in row.items() if k != "adjusted"} for row in adjusted] == plain


def test_the_findings_and_the_verdict_do_not_depend_on_the_covariate() -> None:
    plain = review_context(context(lab_spec()))
    adjusted = review_context(context(lab_spec(pre_period_covariate="sessions_pre_7d")))

    assert (adjusted.verdict, adjusted.findings) == (plain.verdict, plain.findings)


def run_json(capsys, spec: ExperimentSpec, tmp_path: Path, *extra: str) -> tuple[int, str]:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec.to_dict(), sort_keys=False), encoding="utf-8")
    code = main(["review-results", str(path), str(LAB), *COMMON, *extra])
    return code, capsys.readouterr().out


def test_the_text_the_memo_and_the_json_show_both_estimates_and_the_caveats(
    capsys, tmp_path: Path
) -> None:
    spec = lab_spec(pre_period_covariate="sessions_pre_7d")

    _, text = run_json(capsys, spec, tmp_path)
    _, memo = run_json(capsys, spec, tmp_path, "--format", "memo")
    _, js = run_json(capsys, spec, tmp_path, "--format", "json")

    assert "Adjusted for the pre-period covariate:" in text and "variance left" in text
    assert "is the registered analysis" in text and "unadjusted one above" in text
    assert "Adjusted for the pre-period covariate:" in memo and "| variance left |" in memo
    assert json.loads(js)["effect"]["covariate"]["column"] == "sessions_pre_7d"


def test_for_revenue_the_report_says_the_simulated_error_rates_do_not_carry_over(
    capsys, tmp_path: Path
) -> None:
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw["design"]["pre_period_covariate"] = "revenue_usd_pre_7d"
    _, text = run_json(capsys, ExperimentSpec.from_dict(raw), tmp_path)

    assert "RES-008 were measured for the unadjusted interval" in text


def test_the_monitor_shows_the_adjusted_interval_and_no_p_value() -> None:
    data = replace(
        load_export(LAB, "hybrid_offer_page"),
        exported_at=parse_utc("2026-06-30T00:00:00Z"),
    )
    report = monitor_report(
        lab_spec(pre_period_covariate="sessions_pre_7d"), data, file_hashes={}, as_of_source="x"
    )

    primary = report["primary_metric"]
    assert primary["covariate"]["applied"]
    assert all({"difference", "ci_low", "ci_high"} <= set(r["adjusted"]) for r in primary["arms"])
    blob = json.dumps(primary)
    assert '"p_value"' not in blob and '"adjusted_p_value"' not in blob


def test_the_covariate_adjusts_the_primary_metric_only() -> None:
    raw = lab_spec(pre_period_covariate="sessions_pre_7d").to_dict()
    raw["secondary_metrics"] = [{"name": "purchases_7d", "kind": "continuous"}]
    spec = ExperimentSpec.from_dict(raw)

    data = replace(
        load_export(LAB, "hybrid_offer_page"), exported_at=parse_utc("2026-06-30T00:00:00Z")
    )
    report = monitor_report(spec, data, file_hashes={}, as_of_source="x")

    assert all("adjusted" in row for row in report["primary_metric"]["arms"])
    assert all("adjusted" not in row for row in report["secondary_metrics"][0]["arms"])


def test_the_narration_check_accepts_a_report_with_the_covariate_keys(
    capsys, tmp_path: Path
) -> None:
    from referee.narration.facts import check_report_consistency

    _, js = run_json(
        capsys, lab_spec(pre_period_covariate="sessions_pre_7d"), tmp_path, "--format", "json"
    )

    check_report_consistency(json.loads(js))
