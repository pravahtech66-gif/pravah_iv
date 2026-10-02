import numpy as np

from .job_log import _log


def compute_discharge(
    v_x_mean: np.ndarray,
    v_y_mean: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    transect: dict,
    alpha: float,
    job_state: dict,
    speed_grid: np.ndarray = None,
) -> dict:
    distances = np.array(transect["distances"], dtype=float)
    depths    = np.array(transect["depths"],    dtype=float)

    if len(distances) != len(depths):
        _log(job_state, "  [Q] Transect distances and depths length mismatch — skipping discharge")
        return {}

    if len(distances) < 2:
        _log(job_state, "  [Q] Transect needs at least 2 points — skipping discharge")
        return {}

    if speed_grid is None:
        speed_grid = np.sqrt(v_x_mean**2 + v_y_mean**2)

    v_surface_at_transect = np.full(len(distances), np.nan)

    for i, d in enumerate(distances):
        if len(y_coords) == 0:
            continue
        nearest_y_idx = int(np.argmin(np.abs(y_coords - d)))
        row_speeds = speed_grid[nearest_y_idx, :]
        valid_speeds = row_speeds[~np.isnan(row_speeds)]
        if len(valid_speeds) > 0:
            v_surface_at_transect[i] = float(np.mean(valid_speeds))

    valid_mask = ~np.isnan(v_surface_at_transect)
    if valid_mask.sum() >= 2:
        v_interp = np.interp(
            distances,
            distances[valid_mask],
            v_surface_at_transect[valid_mask],
        )
    else:
        _log(job_state, "  [Q] Insufficient valid PIV cells along transect — skipping discharge")
        return {}

    v_interp[0]  = 0.0
    v_interp[-1] = 0.0

    v_depth = alpha * v_interp

    widths = np.zeros(len(distances))
    for i in range(len(distances)):
        left  = (distances[i] - distances[i - 1]) / 2 if i > 0 else 0.0
        right = (distances[i + 1] - distances[i]) / 2 if i < len(distances) - 1 else 0.0
        widths[i] = left + right

    Q_contributions = v_depth * depths * widths
    Q_total = float(np.sum(Q_contributions))

    _log(job_state, f"  [Q] Discharge computation (alpha={alpha:.2f}):")
    _log(job_state, f"      Transect points     : {len(distances)}")
    _log(job_state, f"      River width         : {distances[-1] - distances[0]:.2f} m")
    _log(job_state, f"      Mean surface speed  : {np.mean(v_interp):.4f} m/s")
    _log(job_state, f"      Mean depth          : {np.mean(depths):.3f} m")
    _log(job_state, f"      Q (discharge)       : {Q_total:.4f} m³/s")

    return {
        "Q_m3s":                Q_total,
        "alpha":                alpha,
        "v_surface_transect":   v_interp.tolist(),
        "v_depth_transect":     v_depth.tolist(),
        "transect_distances":   distances.tolist(),
        "transect_depths":      depths.tolist(),
        "Q_contributions":      Q_contributions.tolist(),
    }
