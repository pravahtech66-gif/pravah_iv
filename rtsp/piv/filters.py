import numpy as np

from .job_log import _log
from .defaults import PIV_CORR_MIN, PIV_S2N_MIN


def quality_filter_piv(job_state, piv_ds, corr_min, s2n_min):
    if ("corr" not in piv_ds) or ("s2n" not in piv_ds):
        _log(job_state, "  WARNING: corr/s2n fields not found in PIV output; skipping quality mask.")
        return piv_ds
    mask = (piv_ds["corr"] >= corr_min) & (piv_ds["s2n"] >= s2n_min)
    kept = int(mask.sum().values)
    total = int(mask.size)
    frac = 100.0 * kept / max(total, 1)
    _log(job_state, f"  PIV quality mask kept {kept}/{total} cells ({frac:.1f}%) "
         f"with corr>={corr_min} and s2n>={s2n_min}")
    return piv_ds.where(mask)


def filter_velocity_field(job_state, speed, v_x, v_y):
    spd = speed.copy()
    vx = v_x.copy()
    vy = v_y.copy()

    zero_mask = (spd == 0.0)
    noise_mask = (spd < 0.001) & ~np.isnan(spd) & ~zero_mask

    valid = spd[~zero_mask & ~noise_mask & ~np.isnan(spd)]
    if len(valid) == 0:
        return spd, vx, vy

    median_speed = np.nanmedian(valid)
    if median_speed > 0.001:
        spike_mask = (spd > 5.0 * median_speed) & ~np.isnan(spd)
    else:
        spike_mask = np.zeros_like(spd, dtype=bool)

    reject_mask = zero_mask | noise_mask | spike_mask
    spd[reject_mask] = np.nan
    vx[reject_mask] = np.nan
    vy[reject_mask] = np.nan

    total = speed.size
    original_nan = int(np.count_nonzero(np.isnan(speed)))
    n_zero = int(np.count_nonzero(zero_mask))
    n_noise = int(np.count_nonzero(noise_mask))
    n_spike = int(np.count_nonzero(spike_mask))
    surviving = total - original_nan - n_zero - n_noise - n_spike

    _log(job_state, "  Safety-net velocity filtering (relaxed v3 thresholds):")
    _log(job_state, f"    Total grid cells       : {total}")
    _log(job_state, f"    Already NaN (no data)  : {original_nan}")
    _log(job_state, f"    Rejected (zero)        : {n_zero}")
    _log(job_state, f"    Rejected (noise<0.001) : {n_noise}")
    _log(job_state, f"    Rejected (spike>5xmed) : {n_spike}")
    _log(job_state, f"    Surviving valid cells  : {surviving}")

    return spd, vx, vy


def _apply_pyorc_mask(job_state, piv_ds, method_name, **kwargs):
    try:
        getattr(piv_ds.velocimetry.mask, method_name)(inplace=True, **kwargs)
        return True
    except Exception as e:
        _log(job_state, f"  WARNING: mask.{method_name}() failed: {e} -- skipping.")
        return False


def apply_spatial_coherence_filter(
    job_state: dict,
    piv_ds,
    residual_threshold: float = 2.0,
    epsilon: float = 0.1,
) -> object:
    try:
        from scipy.ndimage import generic_filter

        def _median_test_2d_fast(field: np.ndarray, threshold: float, eps: float) -> np.ndarray:
            nan_mask = np.isnan(field)
            field_filled = field.copy()
            global_med = float(np.nanmedian(field)) if not np.all(nan_mask) else 0.0
            field_filled[nan_mask] = global_med

            footprint = np.ones((3, 3), dtype=bool)

            u_med = generic_filter(field_filled, np.median, footprint=footprint, mode="nearest")

            r_i = np.abs(field_filled - u_med)

            def _residual_med(values):
                return np.median(np.abs(values - np.median(values)))

            r_med = generic_filter(field_filled, _residual_med, footprint=footprint, mode="nearest")

            r_norm = r_i / (r_med + eps)

            outlier = (r_norm > threshold) & ~nan_mask
            return outlier

        vx_vals = piv_ds["v_x"].values.copy()
        vy_vals = piv_ds["v_y"].values.copy()

        total_removed = 0
        n_times = vx_vals.shape[0] if vx_vals.ndim == 3 else 1

        for t in range(n_times):
            if vx_vals.ndim == 3:
                vx_slice = vx_vals[t]
                vy_slice = vy_vals[t]
            else:
                vx_slice = vx_vals
                vy_slice = vy_vals

            mask_x = _median_test_2d_fast(vx_slice, residual_threshold, epsilon)
            mask_y = _median_test_2d_fast(vy_slice, residual_threshold, epsilon)
            combined_mask = mask_x | mask_y

            if vx_vals.ndim == 3:
                vx_vals[t][combined_mask] = np.nan
                vy_vals[t][combined_mask] = np.nan
            else:
                vx_vals[combined_mask] = np.nan
                vy_vals[combined_mask] = np.nan

            total_removed += int(combined_mask.sum())

        piv_ds["v_x"].values[:] = vx_vals
        piv_ds["v_y"].values[:] = vy_vals

        _log(job_state, f"  [F₀] Spatial coherence (median test): removed {total_removed} vectors across {n_times} timesteps")
        return piv_ds

    except Exception as e:
        _log(job_state, f"  [F₀] Spatial coherence filter failed: {e} -- skipping")
        return piv_ds


def _compute_adaptive_quality_thresholds(piv_ds, job_state: dict,
                                          keep_fraction: float = 0.85) -> tuple:
    try:
        corr_arr = piv_ds["corr"].values.ravel() if "corr" in piv_ds else np.array([])
        s2n_arr  = piv_ds["s2n"].values.ravel()  if "s2n"  in piv_ds else np.array([])

        corr_valid = corr_arr[~np.isnan(corr_arr) & (corr_arr > 0)]
        s2n_valid  = s2n_arr[ ~np.isnan(s2n_arr)  & (s2n_arr  > 1)]

        if len(corr_valid) < 10 or len(s2n_valid) < 10:
            _log(job_state,
                 "  [Auto QT] Too few valid cells for adaptive thresholds; "
                 f"using module defaults (corr>={PIV_CORR_MIN}, s2n>={PIV_S2N_MIN}).")
            return PIV_CORR_MIN, PIV_S2N_MIN

        pct      = (1.0 - keep_fraction) * 100.0
        corr_min = float(np.percentile(corr_valid, pct))
        s2n_min  = float(np.percentile(s2n_valid,  pct))

        corr_min = max(0.05, min(0.60, corr_min))
        s2n_min  = max(1.05, min(2.00, s2n_min))

        _log(job_state,
             f"  [Auto QT] Adaptive thresholds (keep top {keep_fraction*100:.0f}% of cells): "
             f"corr_min={corr_min:.3f}, s2n_min={s2n_min:.3f}  "
             f"[{len(corr_valid)} valid correlation samples]")

        return corr_min, s2n_min

    except Exception as e:
        _log(job_state,
             f"  [Auto QT] Adaptive threshold computation failed ({e}); using defaults.")
        return PIV_CORR_MIN, PIV_S2N_MIN
