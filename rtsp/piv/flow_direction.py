import numpy as np

from .job_log import _log


def compute_flow_direction_auto(job_state, v_x, v_y, corr=None):
    vx = np.asarray(v_x, dtype=np.float64).ravel()
    vy = np.asarray(v_y, dtype=np.float64).ravel()
    valid = ~np.isnan(vx) & ~np.isnan(vy)

    w = np.sqrt(vx ** 2 + vy ** 2)
    if corr is not None:
        c = np.asarray(corr, dtype=np.float64).ravel()
        c = np.where(np.isnan(c), 0.0, np.clip(c, 0.0, 1.0))
        if c.shape == w.shape:
            w = w * c
    valid &= w > 1e-9

    vx, vy, w = vx[valid], vy[valid], w[valid]
    if vx.size < 3:
        raise RuntimeError(
            f"Not enough valid vectors to estimate flow direction (n={vx.size})"
        )

    wsum = float(w.sum())
    Cxx = float(np.sum(w * vx * vx) / wsum)
    Cyy = float(np.sum(w * vy * vy) / wsum)
    Cxy = float(np.sum(w * vx * vy) / wsum)
    cov = np.array([[Cxx, Cxy], [Cxy, Cyy]], dtype=np.float64)

    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, -1]
    total = float(eigvals.sum())
    coherence = float(eigvals[-1] / total) if total > 1e-12 else 1.0

    net = np.array([np.sum(w * vx), np.sum(w * vy)], dtype=np.float64)
    if float(np.dot(axis, net)) < 0:
        axis = -axis

    dx, dy = float(axis[0]), float(axis[1])
    angle_rad = float(np.arctan2(dy, dx))

    _log(job_state, f"  [Flow dir] Auto-estimated from {vx.size} valid vectors (magnitude-weighted PCA)")
    _log(job_state, f"  [Flow dir] Flow direction angle : {np.degrees(angle_rad):.1f} deg")
    _log(job_state, f"  [Flow dir] Flow unit vector     : ({dx:.4f}, {dy:.4f})")
    _log(job_state, f"  [Flow dir] Direction coherence  : {coherence:.3f} "
                    f"({'well-defined' if coherence >= 0.7 else 'weak — interpret v_along with caution'})")

    return angle_rad, (dx, dy), coherence


def project_velocities_along_flow(v_x, v_y, flow_unit_vector):
    dx, dy = flow_unit_vector
    v_along = v_x * dx + v_y * dy
    v_cross = v_x * (-dy) + v_y * dx
    return v_along, v_cross
