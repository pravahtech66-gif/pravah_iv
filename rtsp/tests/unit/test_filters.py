import numpy as np
import pytest
import xarray as xr

from piv.filters import filter_velocity_field, quality_filter_piv


def test_removes_zero_noise_and_spike_cells_leaves_others_untouched():
    speed = np.array([
        [1.0, 1.1, 0.9],
        [0.0005, 50.0, 1.05],
        [np.nan, 0.0, 1.0],
    ])
    v_x = speed.copy() * 2.0
    v_y = speed.copy() * 3.0
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, v_x, v_y)

    assert np.isnan(spd[1, 0])
    assert np.isnan(spd[1, 1])
    assert np.isnan(spd[2, 1])
    assert np.isnan(spd[2, 0])
    assert spd[0, 0] == 1.0
    assert spd[0, 1] == 1.1
    assert spd[0, 2] == 0.9
    assert spd[1, 2] == 1.05
    assert spd[2, 2] == 1.0

    reject_positions = [(1, 0), (1, 1), (2, 1)]
    for i, j in reject_positions:
        assert np.isnan(vx[i, j])
        assert np.isnan(vy[i, j])
    survive_positions = [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)]
    for i, j in survive_positions:
        assert vx[i, j] == v_x[i, j]
        assert vy[i, j] == v_y[i, j]


def test_original_arrays_are_not_mutated_in_place():
    speed = np.array([[0.0, 1.0], [50.0, 1.0]])
    v_x = speed.copy()
    v_y = speed.copy()
    speed_before = speed.copy()

    filter_velocity_field({}, speed, v_x, v_y)

    np.testing.assert_array_equal(speed, speed_before)


def test_logs_exact_counts_for_total_nan_zero_noise_spike_and_surviving():
    speed = np.array([
        [1.0, 1.1, 0.9],
        [0.0005, 50.0, 1.05],
        [np.nan, 0.0, 1.0],
    ])
    job_state = {}
    filter_velocity_field(job_state, speed, speed.copy(), speed.copy())

    log = job_state["log"]
    assert "  Safety-net velocity filtering (relaxed v3 thresholds):" in log
    assert "    Total grid cells       : 9" in log
    assert "    Already NaN (no data)  : 1" in log
    assert "    Rejected (zero)        : 1" in log
    assert "    Rejected (noise<0.001) : 1" in log
    assert "    Rejected (spike>5xmed) : 1" in log
    assert "    Surviving valid cells  : 5" in log


def test_speed_exactly_at_noise_floor_is_kept():
    speed = np.array([[0.001, 1.0], [1.0, 1.0]])
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, speed.copy(), speed.copy())

    assert spd[0, 0] == 0.001


def test_all_zero_field_returns_early_with_no_log_and_all_nan_not_forced():
    speed = np.zeros((2, 2))
    v_x = np.zeros((2, 2))
    v_y = np.zeros((2, 2))
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, v_x, v_y)

    np.testing.assert_array_equal(spd, np.zeros((2, 2)))
    assert "log" not in job_state


def test_all_nan_field_returns_early_with_no_log():
    speed = np.full((2, 2), np.nan)
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, speed.copy(), speed.copy())

    assert np.all(np.isnan(spd))
    assert "log" not in job_state


def test_median_at_noise_floor_disables_spike_removal_entirely():
    speed = np.array([[0.001, 0.001], [0.001, 100.0]])
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, speed.copy(), speed.copy())

    assert not np.any(np.isnan(spd))
    assert spd[1, 1] == 100.0
    log = job_state["log"]
    assert "    Rejected (spike>5xmed) : 0" in log
    assert "    Surviving valid cells  : 4" in log


def test_median_just_above_noise_floor_enables_spike_removal():
    speed = np.array([[0.002, 0.002], [0.002, 0.002], [0.002, 1.0]])
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, speed.copy(), speed.copy())

    assert np.isnan(spd[2, 1])
    log = job_state["log"]
    assert "    Rejected (spike>5xmed) : 1" in log
    assert "    Surviving valid cells  : 5" in log


def test_spike_threshold_is_strictly_greater_than_5x_median():
    speed = np.array([[1.0, 1.0], [5.0, 1.0], [1.0, 5.01]])
    job_state = {}

    spd, vx, vy = filter_velocity_field(job_state, speed, speed.copy(), speed.copy())

    assert spd[1, 0] == 5.0
    assert np.isnan(spd[2, 1])


def _make_piv_ds(corr, s2n, v_x=None):
    corr = np.asarray(corr, dtype=float)
    s2n = np.asarray(s2n, dtype=float)
    data = {
        "corr": (("y", "x"), corr),
        "s2n": (("y", "x"), s2n),
    }
    if v_x is not None:
        data["v_x"] = (("y", "x"), np.asarray(v_x, dtype=float))
    return xr.Dataset(data)


def test_quality_mask_keeps_only_cells_meeting_both_thresholds():
    corr = [[0.9, 0.5], [0.95, 0.2]]
    s2n = [[2.0, 2.0], [1.0, 5.0]]
    v_x = [[1.0, 2.0], [3.0, 4.0]]
    ds = _make_piv_ds(corr, s2n, v_x)
    job_state = {}

    out = quality_filter_piv(job_state, ds, corr_min=0.8, s2n_min=1.5)

    result = out["v_x"].values
    assert result[0, 0] == 1.0
    assert np.isnan(result[0, 1])
    assert np.isnan(result[1, 0])
    assert np.isnan(result[1, 1])


def test_quality_mask_boundary_values_are_inclusive():
    corr = [[0.8, 0.79]]
    s2n = [[1.5, 1.5]]
    v_x = [[10.0, 20.0]]
    ds = _make_piv_ds(corr, s2n, v_x)

    out = quality_filter_piv({}, ds, corr_min=0.8, s2n_min=1.5)

    assert out["v_x"].values[0, 0] == 10.0
    assert np.isnan(out["v_x"].values[0, 1])


def test_quality_mask_logs_kept_count_and_percentage():
    corr = [[0.9, 0.5], [0.95, 0.2]]
    s2n = [[2.0, 2.0], [1.0, 5.0]]
    ds = _make_piv_ds(corr, s2n)
    job_state = {}

    quality_filter_piv(job_state, ds, corr_min=0.8, s2n_min=1.5)

    log = job_state["log"]
    assert len(log) == 1
    assert "PIV quality mask kept 1/4 cells (25.0%)" in log[0]
    assert "corr>=0.8" in log[0]
    assert "s2n>=1.5" in log[0]


def test_missing_corr_or_s2n_returns_dataset_unchanged_and_warns():
    ds = xr.Dataset({"v_x": (("y", "x"), np.array([[1.0, 2.0]]))})
    job_state = {}

    out = quality_filter_piv(job_state, ds, corr_min=0.8, s2n_min=1.5)

    assert out is ds
    assert job_state["log"] == [
        "  WARNING: corr/s2n fields not found in PIV output; skipping quality mask."
    ]


def test_missing_only_s2n_also_skips_masking():
    ds = xr.Dataset({
        "corr": (("y", "x"), np.array([[0.9, 0.9]])),
        "v_x": (("y", "x"), np.array([[1.0, 2.0]])),
    })
    job_state = {}

    out = quality_filter_piv(job_state, ds, corr_min=0.8, s2n_min=1.5)

    assert out is ds
    assert "skipping quality mask" in job_state["log"][0]
