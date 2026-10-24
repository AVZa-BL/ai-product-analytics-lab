"""The pooled-effect simulation measures what the rule's own functions compute (design 21.5)."""

import inspect
import json
import math

import numpy as np
import pooled_simulation as module
import pytest
from cohort_simulation import BASE, LOG_SD, PAYING, SD, SPEND_SD, TAILED, draw
from pooled_simulation import (
    ALPHA,
    BOOT_OUTCOMES,
    BOOT_SIZES,
    KOHAVI,
    KURTOSIS_THRESHOLDS,
    OUTCOMES,
    PICKS_AT_A_TIME,
    RESAMPLES,
    SIZES,
    TALLY,
    TOP_SHARE_THRESHOLDS,
    Cell,
    boot_reps_for,
    bootstrap_interval,
    chunk_size,
    criteria,
    draw_arm,
    pooled_grid,
    reps_for,
    run_cell,
    sparse_resample_means,
    study,
    wants_bootstrap,
    welch_interval,
)
from scipy import stats

from referee.methods import (
    StatsError,
    _bootstrap_means,
    bootstrap_difference,
    heavy_tail_measures,
    welch_difference,
)

pytestmark = pytest.mark.study  # re-runs simulations; run with `pytest -m study`


def _players(sample, r: int) -> np.ndarray:
    """The n values of replication r of a sparse sample (`keep=True`), zeros included."""
    assert sample.nonzero is not None
    count, values, starts = sample.nonzero
    return np.concatenate([values[starts[r] : starts[r] + count[r]], np.zeros(sample.n - count[r])])


# --- The statistics are those of the rule ------------------------------------------------------


@pytest.mark.parametrize("outcome", TAILED)
@pytest.mark.parametrize(("n_arm", "n_control"), [(700, 2100), (2100, 700), (150, 150)])
@pytest.mark.parametrize("paying", [0.03, PAYING, 0.3])
def test_the_sparse_statistics_are_the_rules_own(
    outcome: str, n_arm: int, n_control: int, paying: float
) -> None:
    rng = np.random.default_rng(3)
    control = draw_arm(outcome, 3.0, n_control, rng, 25, True, paying)
    arm = draw_arm(outcome, 3.6, n_arm, rng, 25, True, paying)

    low, high, exists = welch_interval(arm, control)

    for r in range(25):
        a, c = _players(arm, r), _players(control, r)
        if not exists[r]:  # nobody spends in either arm: the rule has no interval either
            with pytest.raises(StatsError):
                welch_difference(a.tolist(), c.tolist())
            continue
        real = welch_difference(a.tolist(), c.tolist())
        assert low[r] == pytest.approx(real.ci_low, rel=1e-9, abs=1e-9)
        assert high[r] == pytest.approx(real.ci_high, rel=1e-9, abs=1e-9)
        assert arm.mean[r] == pytest.approx(a.mean(), rel=1e-12)
        assert arm.variance[r] == pytest.approx(a.var(ddof=1), rel=1e-9)
        for sample, x in ((arm, a), (control, c)):
            if len(set(x.tolist())) == 1:
                continue
            measures = heavy_tail_measures(x.tolist())
            assert sample.skewness[r] == pytest.approx(stats.skew(x), rel=1e-9)
            assert sample.kurtosis[r] == pytest.approx(measures.excess_kurtosis, rel=1e-9)
            assert sample.top_share[r] == pytest.approx(measures.top_share, rel=1e-9)
    assert exists.sum() > 15  # the comparison has numbers in it


@pytest.mark.parametrize("outcome", ["normal", "lognormal"])
def test_the_dense_statistics_are_the_rules_own(outcome: str) -> None:
    n, size = 400, 12
    sample = draw_arm(outcome, BASE[outcome], n, np.random.default_rng(8), size)
    again = np.random.default_rng(8)  # the same stream gives the same players
    if outcome == "normal":
        x = BASE[outcome] + SD * again.standard_normal((size, n))
    else:
        mu = math.log(BASE[outcome]) - LOG_SD**2 / 2
        x = np.exp(mu + LOG_SD * again.standard_normal((size, n)))

    for r in range(size):
        assert sample.mean[r] == pytest.approx(x[r].mean(), rel=1e-12)
        assert sample.variance[r] == pytest.approx(x[r].var(ddof=1), rel=1e-12)
        assert sample.skewness[r] == pytest.approx(stats.skew(x[r]), rel=1e-9, abs=1e-12)
        assert sample.kurtosis[r] == pytest.approx(stats.kurtosis(x[r]), rel=1e-9, abs=1e-12)
    if outcome == "lognormal":
        shares = [heavy_tail_measures(x[r].tolist()).top_share for r in range(size)]
        np.testing.assert_allclose(sample.top_share, shares, rtol=1e-9)
    else:  # a normal outcome can be negative: no share of a total
        assert np.isnan(sample.top_share).all()


def test_an_arm_where_nobody_spends_has_no_interval_and_is_not_counted_as_a_miss() -> None:
    rng = np.random.default_rng(1)
    arm = draw_arm("revenue", 3.0, 2, rng, 40)  # two players: no one pays in most replications
    control = draw_arm("revenue", 3.0, 2, rng, 40)

    _, _, exists = welch_interval(arm, control)

    assert 0 < exists.sum() < 40
    row = run_cell(Cell("revenue", 2, 2, 0.0), 400, 0, 5)
    assert row["welch_undefined_n"] > 0
    assert row["welch_above_n"] + row["welch_below_n"] + row["welch_undefined_n"] <= 400


# --- Each outcome is drawn with the mean it is asked for ---------------------------------------


@pytest.mark.parametrize("outcome", ["normal", "lognormal", *TAILED])
@pytest.mark.parametrize("factor", [1.0, 1.2, 1.5, 2.0])
def test_each_outcome_is_drawn_with_the_mean_it_is_given(outcome: str, factor: float) -> None:
    size, n = 20000, 200
    mean = BASE[outcome] * factor

    sample = draw_arm(outcome, mean, n, np.random.default_rng(6), size)

    standard_error = sample.mean.std() / math.sqrt(size)
    assert sample.mean.mean() == pytest.approx(mean, abs=4.5 * standard_error)
    if outcome in SPEND_SD:  # the share who spend is fixed, what they spend carries the effect
        paying = draw_arm(outcome, mean, n, np.random.default_rng(6), size, True)
        assert paying.nonzero is not None
        assert paying.nonzero[0].mean() == pytest.approx(PAYING * n, rel=0.01)


@pytest.mark.parametrize("outcome", TAILED)
def test_the_sparse_draw_has_the_distribution_of_the_dense_draw_of_the_first_study(
    outcome: str,
) -> None:
    n, size, mean = 300, 20000, 3.6  # a +20% arm, so that the mean given is tested too
    sparse = draw_arm(outcome, mean, n, np.random.default_rng(1), size)
    dense = draw(outcome, np.array([mean]), n, np.random.default_rng(2), 6000)[:, 0, :]

    for name, ours, theirs in [
        ("mean", sparse.mean, dense.mean(axis=1)),
        ("variance", sparse.variance, dense.var(axis=1, ddof=1)),
        ("skewness", sparse.skewness, stats.skew(dense, axis=1)),
        ("kurtosis", sparse.kurtosis, stats.kurtosis(dense, axis=1)),
    ]:
        # the same distribution: the two samples of statistics are not told apart
        assert stats.ks_2samp(ours, theirs).pvalue > 1e-4, name
    top = np.sort(dense, axis=1)[:, -3:].sum(axis=1) / dense.sum(axis=1)
    assert stats.ks_2samp(sparse.top_share, top).pvalue > 1e-4


@pytest.mark.parametrize("outcome", ["lognormal", "revenue_mild", "revenue_heavy"])
def test_the_true_difference_of_a_cell_is_the_difference_its_arms_are_drawn_with(
    outcome: str,
) -> None:
    cell = Cell(outcome, 400, 400, 0.5)
    rng = np.random.default_rng(12)
    size = 20000
    control = draw_arm(outcome, BASE[outcome], cell.control_n, rng, size)
    arm = draw_arm(outcome, cell.arm_mean, cell.arm_n, rng, size)

    gap = arm.mean - control.mean

    assert cell.truth == pytest.approx(0.5 * BASE[outcome])
    assert gap.mean() == pytest.approx(cell.truth, abs=4.5 * gap.std() / math.sqrt(size))


# --- The sparse bootstrap is the rule's bootstrap ----------------------------------------------


def _revenue(n: int, seed: int) -> np.ndarray:
    arm = draw_arm("revenue", 3.0, n, np.random.default_rng(seed), 1, True)
    return _players(arm, 0)


def test_the_sparse_resample_means_have_the_distribution_of_the_rules_resample_means() -> None:
    x = _revenue(600, 11)
    nonzero = x[x != 0]
    resamples = 200_000

    rule = _bootstrap_means(x, resamples, np.random.PCG64(np.random.SeedSequence(1)))
    mine = sparse_resample_means(nonzero, len(x), resamples, np.random.default_rng(2))

    se = x.std() / math.sqrt(len(x))  # the exact standard deviation of a resample mean
    assert rule.mean() == pytest.approx(x.mean(), abs=5 * se / math.sqrt(resamples))
    assert mine.mean() == pytest.approx(x.mean(), abs=5 * se / math.sqrt(resamples))
    assert mine.std() == pytest.approx(se, rel=0.02) and rule.std() == pytest.approx(se, rel=0.02)
    q = [0.025, 0.5, 0.975]
    np.testing.assert_allclose(np.quantile(mine, q), np.quantile(rule, q), rtol=0.01)
    far = [0.0005, 0.9995]  # 100 resamples beyond each: known to a few per cent only
    np.testing.assert_allclose(np.quantile(mine, far), np.quantile(rule, far), rtol=0.05)
    assert stats.ks_2samp(rule, mine).pvalue > 1e-4


@pytest.mark.parametrize(("n_arm", "n_control"), [(100, 900), (500, 1500)])
def test_the_sparse_bootstrap_interval_is_the_rules_interval_within_chance(
    n_arm: int, n_control: int
) -> None:
    gaps_low, gaps_high, widths = [], [], []
    for k in range(40):
        a, c = _revenue(n_arm, 100 + k), _revenue(n_control, 300 + k)
        real = bootstrap_interval_of_the_rule(a, c, seed=k)
        mine = bootstrap_interval(
            a[a != 0], n_arm, c[c != 0], n_control, np.random.default_rng(500 + k)
        )
        gaps_low.append(mine[0] - real.ci_low)
        gaps_high.append(mine[1] - real.ci_high)
        widths.append(real.ci_high - real.ci_low)

    # each endpoint is known to a few per cent of the width; the mean of 40 gaps to a fifth of that
    width = np.mean(widths)
    for gaps in (gaps_low, gaps_high):
        se = np.std(gaps, ddof=1) / math.sqrt(len(gaps))
        assert abs(np.mean(gaps)) <= 4 * se + 0.002 * width
        assert np.std(gaps, ddof=1) < 0.06 * width  # and the spread of one gap is chance


def bootstrap_interval_of_the_rule(a: np.ndarray, c: np.ndarray, seed: int):
    return bootstrap_difference(a.tolist(), c.tolist(), seed=seed, resamples=RESAMPLES, alpha=ALPHA)


def test_resamples_with_no_nonzero_values_are_zero_and_the_sparse_sampler_takes_the_count_out() -> (
    None
):
    zeros = sparse_resample_means(np.array([]), 50, 7, np.random.default_rng(1))
    one = sparse_resample_means(np.array([5.0]), 50, 100_000, np.random.default_rng(1))

    assert zeros.tolist() == [0.0] * 7
    # one nonzero value of 5 among 50: a resample mean is 5 * Binomial(50, 1/50) / 50
    assert one.mean() == pytest.approx(5.0 / 50, rel=0.01)
    assert one.std() == pytest.approx(5.0 / 50 * math.sqrt(50 * (1 / 50) * (49 / 50)), rel=0.02)
    assert set(np.round(one * 10).astype(int)) <= set(range(0, 12))  # whole multiples of 5 / 50


def test_the_constants_that_stand_for_the_rule_are_the_rules() -> None:
    parameters = inspect.signature(bootstrap_difference).parameters
    welch = inspect.signature(welch_difference).parameters

    assert RESAMPLES == parameters["resamples"].default == 10_000
    assert ALPHA == parameters["alpha"].default == welch["alpha"].default == 0.05
    assert KOHAVI == 355
    assert module.ERROR_PERCENTILES == (2.5, 50, 97.5) and module.SHAPE_PERCENTILES == (5, 50, 95)
    assert PICKS_AT_A_TIME == 50_000  # how the stream is cut: a different value is a new study


# --- Welch is calibrated for a normal outcome --------------------------------------------------


def test_welch_misses_five_per_cent_for_a_normal_outcome_at_every_split() -> None:
    reps = 4000
    splits = [(300, 300), (200, 1800), (1800, 200), (450, 300), (300, 750), (1000, 100)]
    z, rates = [], []
    for arm_n, control_n in splits:
        for effect in (0.0, 0.5):
            row = run_cell(Cell("normal", arm_n, control_n, effect), reps, 0, 4)
            miss = (row["welch_above_n"] + row["welch_below_n"]) / reps
            z.append((miss - 0.05) / math.sqrt(0.05 * 0.95 / reps))
            rates.append(miss)
            # and each side is a share of the nominal 2.5% (a normal outcome has no skewness)
            for side in ("above", "below"):
                p = row[f"welch_{side}_n"] / reps
                assert abs(p - 0.025) <= 4.5 * math.sqrt(0.025 * 0.975 / reps)
    assert max(abs(x) for x in z) < 3.8  # no cell is far off, with a dozen cells
    assert abs(np.mean(rates) - 0.05) < 4 * math.sqrt(0.05 * 0.95 / reps / len(rates))


# --- A row is what the rule's own functions give for the same players --------------------------


def _agree(a, b, path="row") -> None:
    if isinstance(a, dict):
        assert list(a) == list(b), path
        for key in a:
            _agree(a[key], b[key], f"{path}.{key}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _agree(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert a == pytest.approx(b, abs=2e-5, rel=1e-6), path
    else:
        assert a == b, path


def _all_players(cell: Cell, rng: np.random.Generator, size: int):
    """Every player of `size` replications of control and then the arm, in the order the cell
    draws them: from the sparse draw for a tailed outcome, from the definition otherwise."""
    if cell.outcome in SPEND_SD:
        control = draw_arm(
            cell.outcome, BASE[cell.outcome], cell.control_n, rng, size, True, cell.share
        )
        arm = draw_arm(cell.outcome, cell.arm_mean, cell.arm_n, rng, size, True, cell.share)
        return (
            [_players(control, r) for r in range(size)],
            [_players(arm, r) for r in range(size)],
        )

    def dense(mean: float, n: int) -> np.ndarray:
        z = rng.standard_normal((size, n))
        if cell.outcome == "normal":
            return mean + SD * z
        return np.exp(math.log(mean) - LOG_SD**2 / 2 + LOG_SD * z)

    control_x = dense(BASE[cell.outcome], cell.control_n)
    return control_x, dense(cell.arm_mean, cell.arm_n)


def _reference_row(cell: Cell, reps: int, boot_reps: int, seed: int) -> dict:
    """The row of `run_cell`, worked out one replication at a time with the rule's functions."""
    chunk = module.chunk_size(cell)  # looked up in the module: a test may have cut it shorter
    streams = cell.seed_sequence(seed).spawn((reps + chunk - 1) // chunk)
    truth = cell.truth
    ns = {"arm": cell.arm_n, "control": cell.control_n}
    done = 0
    errors, halves = [], []
    shapes: dict[str, list[float]] = {f"{w}_{s}": [] for w in ns for s in ("skew", "kurt", "share")}
    tallies: dict[str, list[int]] = {}
    boot = {"undefined": 0, "w_a": 0, "w_b": 0, "b_a": 0, "b_b": 0, "w_width": 0.0, "b_width": 0.0}
    pairs = {"above": [0, 0, 0], "below": [0, 0, 0]}
    undefined = above = below = 0
    welch_width = 0.0
    for stream in streams:
        sample_stream, boot_stream = stream.spawn(2)
        rng, boot_rng = np.random.default_rng(sample_stream), np.random.default_rng(boot_stream)
        size = min(chunk, reps - done)
        nb = max(0, min(size, boot_reps - done))
        control_x, arm_x = _all_players(cell, rng, size)
        for r in range(size):
            a, c = arm_x[r], control_x[r]
            try:
                real = welch_difference(a.tolist(), c.tolist())
            except StatsError:
                undefined += 1
                real = None
            stats_of = {}
            for who, x in (("arm", a), ("control", c)):
                try:
                    measures = heavy_tail_measures(x.tolist())
                    stats_of[who] = (stats.skew(x), measures.excess_kurtosis, measures.top_share)
                except StatsError:
                    stats_of[who] = (math.nan, math.nan, math.nan)
                for s, v in zip(("skew", "kurt", "share"), stats_of[who], strict=True):
                    shapes[f"{who}_{s}"].append(v)
            w_above = real is not None and real.ci_low > truth
            w_below = real is not None and real.ci_high < truth
            above += w_above
            below += w_below
            if real is not None:
                errors.append(a.mean() - c.mean() - truth)
                halves.append((real.ci_high - real.ci_low) / 2)
                welch_width += real.ci_high - real.ci_low
            hits = _reference_hits(stats_of, ns, cell)
            for name, hit in hits.items():
                t = tallies.setdefault(name, [0] * 5)
                t[0] += hit
                t[1 if hit else 3] += w_above
                t[2 if hit else 4] += w_below
            if r < nb:
                if real is None:
                    boot["undefined"] += 1
                    continue
                low, high = bootstrap_interval(
                    a[a != 0], cell.arm_n, c[c != 0], cell.control_n, boot_rng
                )
                b_above, b_below = low > truth, high < truth
                boot["w_a"] += w_above
                boot["w_b"] += w_below
                boot["b_a"] += b_above
                boot["b_b"] += b_below
                boot["w_width"] += real.ci_high - real.ci_low
                boot["b_width"] += high - low
                for side, wm, bm in (("above", w_above, b_above), ("below", w_below, b_below)):
                    pairs[side][0] += wm and bm
                    pairs[side][1] += wm and not bm
                    pairs[side][2] += bm and not wm
        done += size
    defined = reps - undefined
    row = {
        "welch_above_n": above,
        "welch_below_n": below,
        "welch_undefined_n": undefined,
        "welch_width": welch_width / defined,
        "error": [float(x) for x in np.percentile(errors, module.ERROR_PERCENTILES)],
        "half_width": float(np.median(halves)),
        "shape": {
            who: [
                float(x)
                for s in ("skew", "kurt", "share")
                for x in np.nanpercentile(shapes[f"{who}_{s}"], module.SHAPE_PERCENTILES)
            ]
            for who in ns
        },
        "criteria": tallies,
    }
    if boot_reps:
        usable = boot_reps - boot["undefined"]
        row["boot"] = {
            "undefined_n": boot["undefined"],
            "welch_above_n": boot["w_a"],
            "welch_below_n": boot["w_b"],
            "boot_above_n": boot["b_a"],
            "boot_below_n": boot["b_b"],
            "above": pairs["above"],
            "below": pairs["below"],
            "welch_width": boot["w_width"] / usable,
            "boot_width": boot["b_width"] / usable,
        }
    return row


def _reference_hits(stats_of: dict, ns: dict, cell: Cell) -> dict[str, bool]:
    """The warnings of one replication, written out from their definitions."""
    skew = {w: stats_of[w][0] for w in ns}
    kurt = {w: stats_of[w][1] for w in ns}
    share = {w: stats_of[w][2] for w in ns}
    kohavi = any(abs(skew[w]) > 1 and ns[w] < 355 * skew[w] ** 2 for w in ns)
    hits = {"kohavi": kohavi}
    for t in (50, 100, 200, 500, 1000):
        hits[f"kurtosis>{t}"] = any(kurt[w] > t for w in ns)
    for t in (0.3, 0.4, 0.5, 0.6, 0.7):
        hits[f"top_share>{t}"] = any(share[w] > t for w in ns)
    hits["all:kurtosis>100"] = all(kurt[w] > 100 for w in ns)
    hits["all:top_share>0.5"] = all(share[w] > 0.5 for w in ns)
    hits["kohavi|kurtosis>100"] = kohavi or hits["kurtosis>100"]
    hits["kohavi|top_share>0.5"] = kohavi or hits["top_share>0.5"]
    if cell.outcome == "normal":
        hits = {k: v for k, v in hits.items() if "top_share" not in k}
    return hits


@pytest.mark.parametrize(
    ("cell", "reps", "boot_reps"),
    [
        (Cell("revenue", 100, 300, 0.2), 45, 20),  # a bootstrap, in chunks of 7
        (Cell("revenue_heavy", 300, 100, 0.0), 30, 0),
        (Cell("revenue", 100, 100, 1.0, 0.03), 30, 12),  # few who spend
        (Cell("lognormal", 150, 150, 0.5), 21, 0),
    ],
)
def test_a_row_is_what_the_rules_functions_say_about_the_players_it_drew(
    cell: Cell, reps: int, boot_reps: int, monkeypatch
) -> None:
    monkeypatch.setattr(module, "chunk_size", lambda cell: 7)

    row = run_cell(cell, reps, boot_reps, 5)
    expected = _reference_row(cell, reps, boot_reps, 5)

    _agree({k: row[k] for k in expected}, expected)
    assert row["reps"] == reps and row["boot_reps"] == boot_reps and row["seed"] == 5
    assert row["welch_above_n"] + row["welch_below_n"] > 0  # a mixture, so the check bites
    if boot_reps:
        assert 0 < row["boot"]["boot_above_n"] + row["boot"]["boot_below_n"]


def test_replications_without_an_interval_are_left_out_of_the_widths_and_the_bootstrap() -> None:
    cell = Cell("revenue", 6, 6, 1.0, 0.05)  # most runs have nobody who spends in either arm

    row = run_cell(cell, 60, 40, 5)
    expected = _reference_row(cell, 60, 40, 5)

    _agree({k: row[k] for k in expected}, expected)
    assert 0 < row["boot"]["undefined_n"] < 40 and 0 < row["welch_undefined_n"] < 60
    assert row["boot"]["undefined_n"] <= row["welch_undefined_n"]
    assert row["welch_width"] > 0 and row["boot"]["boot_width"] > 0


def test_a_study_that_fails_cancels_the_cells_that_have_not_started(monkeypatch) -> None:
    from concurrent.futures import Future

    made: list[Future] = []

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, job):
            future: Future = Future()
            if not made:
                future.set_exception(RuntimeError("the first cell failed"))
            made.append(future)
            return future

    monkeypatch.setattr(module, "ProcessPoolExecutor", FakePool)
    cells = [Cell("normal", 10, 10, 0.0), *[Cell("normal", 10 + i, 10, 0.0) for i in range(1, 5)]]

    with pytest.raises(RuntimeError, match="the first cell failed"):
        study(cells, 4, 0, 1, workers=2)

    assert len(made) == 5 and [f.cancelled() for f in made[1:]] == [True] * 4


def test_the_bootstrap_is_taken_on_the_first_replications_of_a_cell_in_every_chunk(
    monkeypatch,
) -> None:
    cell = Cell("revenue", 100, 300, 0.2)
    monkeypatch.setattr(module, "chunk_size", lambda cell: 7)
    seen = []
    real = module.bootstrap_interval

    def counting(*args, **kwargs):
        seen.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "bootstrap_interval", counting)

    row = run_cell(cell, 30, 30, 2)

    assert len(seen) == 30 - row["boot"]["undefined_n"]
    # with a bootstrap on every replication, the paired Welch numbers are the Welch numbers
    assert row["boot"]["welch_above_n"] == row["welch_above_n"]
    assert row["boot"]["welch_below_n"] == row["welch_below_n"]
    assert row["boot"]["welch_width"] == pytest.approx(row["welch_width"], abs=2e-5)
    for side in ("above", "below"):
        both, welch_only, boot_only = row["boot"][side]
        assert both + welch_only == row[f"welch_{side}_n"]
        assert both + boot_only == row["boot"][f"boot_{side}_n"]

    again = run_cell(cell, 40, 28, 2)  # more replications, the same first four whole chunks
    first = run_cell(cell, 30, 28, 2)
    assert module.chunk_size(cell) == 7 and again["boot"] == first["boot"]


def test_the_first_chunk_of_a_cell_is_the_same_whatever_the_number_of_replications(
    monkeypatch,
) -> None:
    cell = Cell("revenue", 200, 200, 0.0)
    size = chunk_size(cell)
    drawn: list[np.ndarray] = []
    real = module.draw_arm

    def recording(*args, **kwargs):
        sample = real(*args, **kwargs)
        drawn.append(sample.mean.copy())
        return sample

    monkeypatch.setattr(module, "draw_arm", recording)

    run_cell(cell, size, 0, 9)
    first = list(drawn)
    drawn.clear()
    run_cell(cell, 2 * size, 0, 9)

    assert size == 5000 and len(first) == 2 and len(drawn) == 4  # control and arm, a chunk each
    for before, after in zip(first, drawn[:2], strict=True):
        np.testing.assert_array_equal(before, after)
    assert not np.array_equal(drawn[0], drawn[2])  # the next chunk is another stream


def test_the_rows_do_not_depend_on_the_number_of_workers_and_come_back_in_grid_order() -> None:
    cells = [
        Cell("revenue", 100, 300, 0.0),
        Cell("lognormal", 100, 100, 0.2),
        Cell("revenue", 300, 100, 0.2),
    ]

    in_processes = study(cells, 80, 10, 4, workers=2)

    assert in_processes == study(cells, 80, 10, 4, workers=1)
    assert [(r["outcome"], r["arm_n"], r["control_n"]) for r in in_processes] == [
        (c.outcome, c.arm_n, c.control_n) for c in cells
    ]


def test_a_study_says_how_far_it_has_got(capsys) -> None:
    cells = [Cell("normal", 50, 50, 0.0), Cell("normal", 60, 60, 0.0)]

    study(cells, 20, 0, 1, workers=2, progress=True)

    assert "pooled: 2 of 2 cells" in capsys.readouterr().err


def test_the_bootstrap_does_not_change_the_welch_numbers_of_a_cell() -> None:
    cell = Cell("revenue", 100, 100, 0.0)

    without = run_cell(cell, 120, 0, 3)
    with_boot = run_cell(cell, 120, 30, 3)

    for key in ("welch_above_n", "welch_below_n", "welch_undefined_n", "welch_width", "shape"):
        assert without[key] == with_boot[key], key
    assert without["criteria"] == with_boot["criteria"] and "boot" not in without


# --- Seeds -------------------------------------------------------------------------------------


def test_every_cell_has_its_own_stream_and_each_part_of_its_key_matters() -> None:
    cells = pooled_grid()
    keys = {tuple(c.seed_sequence(7).generate_state(2)) for c in cells}
    base = Cell("revenue", 100, 300, 0.2)
    others = [
        Cell("revenue_heavy", 100, 300, 0.2),
        Cell("revenue", 300, 100, 0.2),
        Cell("revenue", 100, 301, 0.2),
        Cell("revenue", 100, 300, 0.5),
        Cell("revenue", 100, 300, 0.2, 0.03),
    ]

    assert len(keys) == len(cells)
    draws = [
        draw_arm(c.outcome, c.arm_mean, c.arm_n, np.random.default_rng(c.seed_sequence(7)), 5).mean
        for c in (base, *others)
    ]
    assert len({tuple(d) for d in draws}) == len(draws)
    assert base.seed_sequence(7).generate_state(1) != base.seed_sequence(8).generate_state(1)


# --- The grid ----------------------------------------------------------------------------------


def test_the_grid_covers_each_block_once_and_keeps_the_directions_it_needs() -> None:
    cells = pooled_grid()

    assert len(cells) == len(set(cells)) == 620
    main = [c for c in cells if c.paying is None and min(c.arm_n, c.control_n) < 10_000]
    main = [c for c in main if c.effect in module.EFFECTS and c.outcome in OUTCOMES]
    assert len(main) == 400 and all(sum(c.outcome == o for c in main) == 80 for o in OUTCOMES)
    # no effect: only the arm at least as large as control (the draws are exchangeable)
    assert all(c.arm_n >= c.control_n for c in cells if c.effect == 0.0)
    # an effect: both directions of every split
    for c in cells:
        if c.effect > 0 and c.arm_n != c.control_n:
            twin = Cell(c.outcome, c.control_n, c.arm_n, c.effect, c.paying)
            assert twin in cells, c
    assert {min(c.arm_n, c.control_n) for c in cells} == {
        *SIZES,
        *module.LARGE_SIZES,
        *module.PAYER_SIZES,
        *module.LADDER_SIZES,
    }
    assert {c.paying for c in cells} == {None, *module.PAYER_SHARES}
    assert {c.effect for c in cells} == {0.0, 0.2, 0.5, 1.0}
    ratios = {round(c.ratio, 3) for c in cells}
    assert ratios >= {1, 1.5, 2, 2.5, 3, 4, 9}
    # nine to one is not run beyond 30,000 players in the smaller arm
    assert not any(c.ratio == 9 and min(c.arm_n, c.control_n) > 30_000 for c in cells)


def test_the_bootstrap_runs_on_a_subset_and_halves_for_the_larger_cells() -> None:
    cells = pooled_grid()
    boot = [c for c in cells if wants_bootstrap(c)]

    assert len(boot) == 99
    assert {c.outcome for c in boot} == set(BOOT_OUTCOMES)
    assert {min(c.arm_n, c.control_n) for c in boot} == set(BOOT_SIZES)
    assert {round(c.ratio, 3) for c in boot} == set(module.BOOT_RATIOS)
    assert all(c.paying is None and c.effect in (0.0, 0.2) for c in boot)
    small, large = Cell("revenue", 100, 300, 0.2), Cell("revenue", 1000, 9000, 0.2)
    assert boot_reps_for(small, 2000, 20000) == 2000
    assert boot_reps_for(large, 2000, 20000) == 1000
    assert boot_reps_for(small, 2000, 500) == 500  # never more than the replications
    assert boot_reps_for(Cell("normal", 100, 100, 0.0), 2000, 20000) == 0
    assert boot_reps_for(Cell("revenue", 150, 100, 0.0), 2000, 20000) == 0  # 1.5 to 1: not run
    assert boot_reps_for(Cell("revenue", 100, 300, 0.0), 2000, 20000) == 0  # no effect: arm larger
    assert reps_for(Cell("revenue", 10_000, 10_000, 0.0), 20000, 2000) == 2000
    assert reps_for(Cell("revenue", 3_000, 9_000, 0.0), 20000, 2000) == 20000


def test_the_chunks_are_cut_from_the_sizes_of_the_cell_alone() -> None:
    assert chunk_size(Cell("revenue", 100, 100, 0.0)) == 5000
    assert chunk_size(Cell("revenue", 3000, 27000, 0.0)) == 133
    assert chunk_size(Cell("lognormal", 100_000, 100_000, 0.0)) == 20


def test_the_true_difference_is_zero_with_no_effect_and_the_effect_times_the_mean_with_one() -> (
    None
):
    assert Cell("revenue", 10, 10, 0.0).truth == 0.0
    assert Cell("revenue", 10, 10, 0.2).truth == pytest.approx(0.6)
    assert Cell("lognormal", 10, 10, 0.2).truth == pytest.approx(2.0)
    assert Cell("revenue", 10, 10, 1.0).arm_mean == pytest.approx(6.0)
    assert Cell("revenue", 10, 30, 0.0).ratio == 3 and Cell("revenue", 30, 10, 0.0).ratio == 3


# --- The candidate warnings --------------------------------------------------------------------


def _sample(n: int, skew: float, kurt: float, share: float) -> module.ArmSample:
    one = np.array([1.0])
    return module.ArmSample(n, one, one, np.array([skew]), np.array([kurt]), np.array([share]))


def test_the_warnings_fire_when_any_arm_is_beyond_the_threshold_and_all_when_all_are() -> None:
    quiet, heavy = _sample(1000, 0.2, 1.0, 0.05), _sample(1000, 3.0, 600.0, 0.65)
    short = _sample(300, 3.0, 2.0, 0.05)  # n < 355 * 9
    long_ = _sample(5000, 3.0, 2.0, 0.05)  # n >= 355 * 9 = 3195

    assert not any(v[0] for v in criteria(quiet, quiet).values())
    found = {k: bool(v[0]) for k, v in criteria(quiet, heavy).items()}
    assert found["kohavi"] and found["kurtosis>500"] and not found["kurtosis>1000"]
    assert found["top_share>0.6"] and not found["top_share>0.7"]
    assert not found["all:kurtosis>100"] and not found["all:top_share>0.5"]
    both = {k: bool(v[0]) for k, v in criteria(heavy, heavy).items()}
    assert both["all:kurtosis>100"] and both["all:top_share>0.5"]
    assert criteria(heavy, quiet)["kurtosis>500"][0]  # either arm
    assert criteria(short, quiet)["kohavi"][0] and not criteria(long_, quiet)["kohavi"][0]
    assert not criteria(_sample(300, -0.9, 0, 0), quiet)["kohavi"][0]  # |s| must exceed 1
    assert criteria(_sample(300, -3.0, 0, 0), quiet)["kohavi"][0]  # and the sign does not matter
    # the OR with Kohavi's rule is true where either is, and only there
    assert criteria(long_, quiet)["kohavi|kurtosis>100"][0] == False  # noqa: E712
    assert criteria(short, quiet)["kohavi|kurtosis>100"][0]
    assert criteria(_sample(5000, 3.0, 150.0, 0.0), quiet)["kohavi|kurtosis>100"][0]
    assert criteria(_sample(5000, 3.0, 0.0, 0.8), quiet)["kohavi|top_share>0.5"][0]
    assert set(criteria(quiet, quiet)) == {
        "kohavi",
        *(f"kurtosis>{t}" for t in KURTOSIS_THRESHOLDS),
        *(f"top_share>{t}" for t in TOP_SHARE_THRESHOLDS),
        "all:kurtosis>100",
        "all:top_share>0.5",
        "kohavi|kurtosis>100",
        "kohavi|top_share>0.5",
    }


def test_kohavis_rule_is_n_below_355_times_the_squared_skewness_and_nothing_near_it() -> None:
    quiet = _sample(1000, 0.2, 1.0, 0.05)
    for skew, below, above in [
        (3.0, 3190, 3200),
        (1.5, 798, 800),
        (-1.5, 798, 800),
        (1.01, 360, 363),
    ]:
        edge = 355 * skew**2
        assert below < edge <= above, (skew, edge)
        assert criteria(_sample(below, skew, 0, 0), quiet)["kohavi"][0], (skew, below)
        assert not criteria(_sample(above, skew, 0, 0), quiet)["kohavi"][0], (skew, above)
    assert not criteria(_sample(10, 1.0, 0, 0), quiet)["kohavi"][0]  # |s| = 1 is not beyond 1


def test_a_normal_outcome_has_no_share_of_a_total_to_warn_by() -> None:
    normal = run_cell(Cell("normal", 100, 100, 0.0), 50, 0, 1)["criteria"]
    revenue = run_cell(Cell("revenue", 100, 100, 0.0), 50, 0, 1)["criteria"]

    assert not any("top_share" in name for name in normal)
    assert len(revenue) - len(normal) == len(TOP_SHARE_THRESHOLDS) + 2  # and the two beside it
    assert all(len(t) == len(TALLY) for t in revenue.values())


def test_the_counts_of_a_warning_add_up_to_the_misses_of_the_cell() -> None:
    row = run_cell(Cell("revenue", 100, 300, 0.2), 400, 0, 6)

    for name, (fired, above_fired, below_fired, above_not, below_not) in row["criteria"].items():
        assert above_fired + above_not == row["welch_above_n"], name
        assert below_fired + below_not == row["welch_below_n"], name
        assert 0 <= fired <= row["reps"] and above_fired + below_fired <= fired, name


def test_a_row_is_strict_json_and_has_the_columns_of_its_kind() -> None:
    rows = [
        run_cell(Cell("revenue", 100, 300, 0.2), 60, 20, 1),
        run_cell(Cell("normal", 100, 100, 0.0), 60, 0, 1),
        run_cell(Cell("lognormal", 100, 100, 0.2, None), 60, 0, 1),
    ]
    for row in rows:
        json.dumps(row, allow_nan=False)  # no NaN, no infinity
    plain = ["outcome", "arm_n", "control_n", "effect", "truth", "reps", "boot_reps", "seed"]
    plain += ["welch_above_n", "welch_below_n", "welch_undefined_n", "welch_width", "error"]
    plain += ["half_width", "shape", "criteria"]
    assert list(rows[1]) == plain and list(rows[2]) == plain
    assert list(rows[0]) == [*plain, "boot"]
    assert rows[1]["shape"]["arm"][6:] == [None, None, None]  # a normal outcome: no share
    payer = run_cell(Cell("revenue", 100, 100, 0.0, 0.3), 20, 0, 1)
    assert payer["paying"] == 0.3 and "paying" not in rows[0]


# --- The command line --------------------------------------------------------------------------


def test_the_defaults_of_the_command_line_are_pinned() -> None:
    arguments = module._parser().parse_args([])

    assert (arguments.reps, arguments.large_reps, arguments.boot_reps) == (20000, 2000, 2000)
    assert arguments.seed == 20261212 and arguments.workers == 1 and arguments.out is None


def test_the_command_line_writes_the_study_it_describes(tmp_path, monkeypatch, capsys) -> None:
    cheap = [Cell("revenue", 100, 300, 0.2), Cell("normal", 100, 100, 0.0)]
    monkeypatch.setattr(module, "pooled_grid", lambda: cheap)
    out = tmp_path / "a" / "b" / "pooled.json"  # directories that do not exist yet

    module.main(
        ["--reps", "40", "--large-reps", "20", "--boot-reps", "8", "--seed", "4", "--out", str(out)]
    )
    made = json.loads(out.read_text(encoding="utf-8"))

    assert list(made)[-1] == "cells"
    assert made["command"] == (
        "python tests/pooled_simulation.py --reps 40 --large-reps 20 --boot-reps 8 --seed 4 "
        f"--out {out}"
    )
    assert (made["reps"], made["large_reps"], made["boot_reps"], made["seed"]) == (40, 20, 8, 4)
    assert (made["resamples"], made["alpha"]) == (RESAMPLES, ALPHA)
    assert "a share 0.13 of the players spend" in made["outcomes"]
    assert all(f"{sd} ({name})" in made["outcomes"] for name, sd in SPEND_SD.items())
    assert made["cells"] == study(cheap, 40, 8, 4, large_reps=20)

    module.main(["--reps", "10", "--boot-reps", "0"])  # to the screen
    screen = json.loads(capsys.readouterr().out)
    assert screen["command"].endswith("--large-reps 2000 --boot-reps 0 --seed 20261212")
    assert all("boot" not in row for row in screen["cells"])


def test_the_recorded_command_can_be_read_back_even_for_a_path_with_a_space(tmp_path) -> None:
    import shlex

    out = tmp_path / "a folder" / "pooled study.json"

    module.main(["--reps", "5", "--large-reps", "5", "--boot-reps", "0", "--out", str(out)])
    made = json.loads(out.read_text(encoding="utf-8"))
    arguments = module._parser().parse_args(shlex.split(made["command"])[2:])

    assert arguments.out == out and (arguments.reps, arguments.boot_reps) == (5, 0)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--reps", "0"],
        ["--large-reps", "0"],
        ["--workers", "0"],
        ["--boot-reps", "-1"],
        ["--reps", "10", "--boot-reps", "11"],
        ["--large-reps", "10", "--boot-reps", "11"],
        ["--seed", "-1"],
    ],
)
def test_the_command_line_refuses_arguments_that_would_give_a_wrong_or_empty_study(
    arguments: list[str], monkeypatch
) -> None:
    monkeypatch.setattr(module, "study", lambda *a, **k: pytest.fail("the study ran"))

    with pytest.raises(SystemExit) as stopped:
        module.main(arguments)

    assert stopped.value.code == 2


def test_the_command_line_finds_out_that_it_cannot_write_before_it_computes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(module, "study", lambda *a, **k: pytest.fail("the study ran"))
    blocker = tmp_path / "a file"
    blocker.write_text("not a directory", encoding="utf-8")

    for out in (blocker / "study.json", tmp_path):  # a directory below a file; a directory
        with pytest.raises(SystemExit) as stopped:
            module.main(["--reps", "5", "--large-reps", "5", "--boot-reps", "0", "--out", str(out)])
        assert stopped.value.code == 2
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_a_study_that_fails_leaves_no_new_file_and_does_not_empty_an_old_one(
    tmp_path, monkeypatch
) -> None:
    def failing(*args, **kwargs):
        raise RuntimeError("the study failed")

    monkeypatch.setattr(module, "study", failing)
    new, old = tmp_path / "x" / "new.json", tmp_path / "old.json"
    old.write_text("the last study", encoding="utf-8")

    for out in (new, old):
        with pytest.raises(RuntimeError, match="the study failed"):
            module.main(["--reps", "5", "--large-reps", "5", "--boot-reps", "0", "--out", str(out)])

    assert not new.exists()
    assert old.read_text(encoding="utf-8") == "the last study"
