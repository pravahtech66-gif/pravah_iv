import numpy as np
import cv2

from .job_log import _log


def compute_water_mask(frames_proj_first_frame: np.ndarray) -> np.ndarray:
    if frames_proj_first_frame.ndim == 3:
        frame = frames_proj_first_frame[0]
    else:
        frame = frames_proj_first_frame
    water_mask = ~np.isnan(frame.astype(float))
    return water_mask


def restrict_grid_to_water(
    piv_ds,
    frames_proj,
    job_state: dict,
) -> object:
    try:
        first_frame = frames_proj[0].values if hasattr(frames_proj, "values") else frames_proj[0]
        water_mask = compute_water_mask(first_frame)

        piv_h = piv_ds["v_x"].shape[-2] if piv_ds["v_x"].ndim > 2 else piv_ds["v_x"].shape[0]
        piv_w = piv_ds["v_x"].shape[-1] if piv_ds["v_x"].ndim > 2 else piv_ds["v_x"].shape[1]

        water_mask_float = water_mask.astype(np.float32)
        water_mask_resized = cv2.resize(
            water_mask_float, (piv_w, piv_h),
            interpolation=cv2.INTER_NEAREST,
        )
        water_mask_bool = water_mask_resized > 0.5

        removed = int(np.sum(~water_mask_bool))
        total = water_mask_bool.size
        _log(job_state, f"  [P₁] Water-only grid: removed {removed}/{total} cells outside water area")

        import xarray as xr
        mask_da = xr.DataArray(
            water_mask_bool,
            dims=["y", "x"] if "y" in piv_ds.dims else piv_ds["v_x"].dims[-2:],
        )
        for var in ["v_x", "v_y", "corr", "s2n"]:
            if var in piv_ds:
                piv_ds[var] = piv_ds[var].where(mask_da)

        return piv_ds
    except Exception as e:
        _log(job_state, f"  [P₁] Water-only grid restriction failed: {e} -- using full AOI grid")
        return piv_ds


def compute_sa_from_spots(
    displacement_spots: list,
    fps: float,
    framestep: int,
    job_state: dict,
) -> dict:
    if not displacement_spots:
        _log(job_state, "  [P₂] No displacement spots provided; using default SA")
        return {"sa_downstream": 40, "sa_upstream": 1, "sa_spanwise": 20}

    streamwise_disps = []
    spanwise_disps = []

    for spot in displacement_spots:
        try:
            p1 = np.array(spot[0], dtype=float)
            p2 = np.array(spot[1], dtype=float)
            disp = p2 - p1
            streamwise_disps.append(abs(disp[0]))
            spanwise_disps.append(abs(disp[1]))
        except Exception:
            continue

    if not streamwise_disps:
        return {"sa_downstream": 40, "sa_upstream": 1, "sa_spanwise": 20}

    max_stream = max(streamwise_disps)
    max_span = max(spanwise_disps) if spanwise_disps else max_stream * 0.5

    sa_downstream = max(int(np.ceil(2 * max_stream)), 10)
    sa_spanwise   = max(int(np.ceil(2 * max_span)), 5)
    sa_upstream   = 1

    _log(job_state, f"  [P₂] From {len(streamwise_disps)} spotted displacements:")
    _log(job_state, f"       Max streamwise = {max_stream:.1f}px → SA_downstream = {sa_downstream}px")
    _log(job_state, f"       Max spanwise   = {max_span:.1f}px  → SA_spanwise   = {sa_spanwise}px")

    return {
        "sa_downstream": sa_downstream,
        "sa_upstream": sa_upstream,
        "sa_spanwise": sa_spanwise,
    }
