import hashlib
import json
import pathlib
import sys

import numpy as np
import cv2
import pyorc

from .job_log import _log


def _jsonable(obj):
    if hasattr(obj, "tolist"):
        return obj.tolist()
    return str(obj)


def rng_fingerprint():
    try:
        state = np.random.get_state()
        return hashlib.sha1(state[1].tobytes() + str(state[2]).encode()).hexdigest()[:12]
    except Exception:
        return "n/a"


def env_versions():
    versions = {"python": sys.version.split()[0]}
    for name, mod in (("numpy", np), ("cv2", cv2), ("pyorc", pyorc)):
        versions[name] = str(getattr(mod, "__version__", "?"))
    try:
        import scipy
        versions["scipy"] = scipy.__version__
    except Exception:
        pass
    return versions


def config_sha1(config):
    return hashlib.sha1(json.dumps(config, sort_keys=True, default=_jsonable).encode()).hexdigest()[:10]


def log_camera_model(job_state, cam_config, config, gcps, h_a):
    cam = {}
    try:
        K = np.asarray(cam_config.camera_matrix, dtype=float)
        cam.update(fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]))
        cam["dist_coeffs"] = np.asarray(cam_config.dist_coeffs, dtype=float).reshape(-1).tolist()
        _log(job_state, f"  Camera matrix : fx={cam['fx']:.2f} fy={cam['fy']:.2f} "
                        f"cx={cam['cx']:.1f} cy={cam['cy']:.1f} px")
        _log(job_state, f"  Dist coeffs   : {[f'{d:.4g}' for d in cam['dist_coeffs']]}")
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: camera matrix unavailable: {e}")

    try:
        rvec = np.asarray(cam_config.rvec, dtype=float).reshape(3, 1)
        tvec = np.asarray(cam_config.tvec, dtype=float).reshape(3, 1)
        rot = cv2.Rodrigues(rvec)[0]
        implied = (-rot.T @ tvec).flatten()
        entered = np.asarray(config["lens_position"], dtype=float)
        err = float(np.linalg.norm(implied - entered))
        cam.update(
            rvec=rvec.flatten().tolist(),
            tvec=tvec.flatten().tolist(),
            implied_lens_position=implied.tolist(),
            entered_lens_position=entered.tolist(),
            lens_position_error_m=err,
        )
        _log(job_state, f"  Camera position: entered={np.round(entered, 3).tolist()} "
                        f"solved={np.round(implied, 3).tolist()} |diff|={err:.3f} m")
        if err > 0.5:
            _log(job_state, "  WARNING: solved camera position is >0.5 m from the entered "
                            "lens_position — GCPs, lens_position or the focal-length fit disagree")
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: extrinsics unavailable: {e}")

    try:
        src = np.asarray(gcps["src"], dtype=float).reshape(-1, 2)
        dst = np.asarray(gcps["dst"], dtype=float)
        if dst.shape[1] == 2:
            dst = np.column_stack([dst, np.full(len(dst), float(gcps["z_0"]))])
        proj = np.asarray(cam_config.project_points(dst.tolist()), dtype=float).reshape(-1, 2)
        per_gcp = np.linalg.norm(proj - src, axis=1)
        cam["gcp_reprojection_px"] = per_gcp.tolist()
        cam["gcp_reprojection_mean_px"] = float(per_gcp.mean())
        _log(job_state, f"  GCP reprojection: per-point={np.round(per_gcp, 2).tolist()} px, "
                        f"mean={per_gcp.mean():.2f} px")
        if per_gcp.max() > 10.0:
            _log(job_state, "  WARNING: a GCP reprojects >10 px from where it was clicked — "
                            "GCP pixel/world pairs or lens_position are inconsistent")
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: GCP reprojection check failed: {e}")

    try:
        z_a = float(cam_config.get_z_a(h_a))
        cam["z_a"] = z_a
        _log(job_state, f"  Water plane   : z_a={z_a:.4f} m  "
                        f"(= z_0 {gcps['z_0']:.4f} + h_a {h_a:.4f} - h_ref {gcps['h_ref']:.4f})")
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: get_z_a failed: {e}")

    try:
        bbox = cam_config.bbox
        cam["bbox_wkt"] = bbox.wkt if hasattr(bbox, "wkt") else str(bbox)
    except Exception:
        pass
    return cam


def log_time_axis(job_state, frames, label):
    try:
        t = np.asarray(frames.coords["time"].values, dtype=float)
        dt = np.diff(t)
        med = float(np.median(dt)) if dt.size else float("nan")
        info = {
            "n": int(t.size),
            "span_s": float(t[-1] - t[0]) if t.size > 1 else 0.0,
            "dt_min": float(dt.min()) if dt.size else None,
            "dt_median": med,
            "dt_max": float(dt.max()) if dt.size else None,
            "n_gaps_gt_1p5x_median": int(np.sum(dt > 1.5 * med)) if dt.size else 0,
        }
        _log(job_state, f"  Time axis [{label}]: n={info['n']} span={info['span_s']:.3f} s  "
                        f"dt min/med/max={info['dt_min']:.4f}/{info['dt_median']:.4f}/{info['dt_max']:.4f} s  "
                        f"gaps>1.5x median: {info['n_gaps_gt_1p5x_median']}")
        if info["n_gaps_gt_1p5x_median"]:
            _log(job_state, "  NOTE: irregular frame timing — dropped frames in the file. pyorc "
                            "uses per-pair dt so velocities stay correct, but pairs straddling "
                            "a gap have a larger displacement")
        return info
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: time-axis stats unavailable ({label}): {e}")
        return None


def log_piv_stats(job_state, piv, label):
    try:
        vx = np.asarray(piv["v_x"].values, dtype=float)
        vy = np.asarray(piv["v_y"].values, dtype=float)
        mag = np.sqrt(vx ** 2 + vy ** 2)
        valid = ~np.isnan(mag)
        per_cell = valid.sum(axis=0)
        n_pairs = int(mag.shape[0])
        info = {
            "shape_time_y_x": list(mag.shape),
            "n_pairs": n_pairs,
            "valid_fraction": float(valid.mean()),
            "cells_total": int(per_cell.size),
            "cells_valid_in_all_pairs": int(np.sum(per_cell == n_pairs)),
            "cells_valid_in_lt_half": int(np.sum(per_cell < np.ceil(n_pairs / 2))),
            "cells_valid_in_none": int(np.sum(per_cell == 0)),
        }
        if valid.any():
            info["mag_median"] = float(np.nanmedian(mag))
            info["mag_p90"] = float(np.nanpercentile(mag, 90))
            info["mag_max"] = float(np.nanmax(mag))
        for key in ("corr", "s2n"):
            if key in piv:
                arr = np.asarray(piv[key].values, dtype=float)
                if np.any(~np.isnan(arr)):
                    info[f"{key}_p10"] = float(np.nanpercentile(arr, 10))
                    info[f"{key}_median"] = float(np.nanmedian(arr))
        _log(job_state, f"  PIV stats [{label}]: pairs={n_pairs} cells={info['cells_total']} "
                        f"valid={info['valid_fraction'] * 100:.1f}%  all-pairs={info['cells_valid_in_all_pairs']} "
                        f"<half={info['cells_valid_in_lt_half']} none={info['cells_valid_in_none']}")
        if "mag_median" in info:
            _log(job_state, f"    |v| median={info['mag_median']:.4f} p90={info['mag_p90']:.4f} "
                            f"max={info['mag_max']:.4f} m/s"
                            + (f"  corr p10/med={info['corr_p10']:.3f}/{info['corr_median']:.3f}"
                               if "corr_median" in info else "")
                            + (f"  s2n p10/med={info['s2n_p10']:.3f}/{info['s2n_median']:.3f}"
                               if "s2n_median" in info else ""))
        if n_pairs < 10:
            _log(job_state, f"  WARNING: only {n_pairs} frame-pairs are aggregated — expect large "
                            "run-to-run scatter")
        return info
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: PIV stats unavailable ({label}): {e}")
        return None


def field_stats(arr):
    arr = np.asarray(arr, dtype=float)
    finite = arr[~np.isnan(arr)]
    if finite.size == 0:
        return {"n": 0}
    return {
        "n": int(finite.size),
        "mean": float(finite.mean()),
        "median": float(np.median(finite)),
        "max": float(finite.max()),
        "min": float(finite.min()),
    }


def write_debug_json(job_state, out_dir, stem, debug):
    path = pathlib.Path(out_dir) / f"{stem}_debug.json"
    try:
        path.write_text(json.dumps(debug, indent=2, default=_jsonable), encoding="utf-8")
        _log(job_state, f"  Debug dump    : {path.name}")
        return str(path.resolve())
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: could not write debug dump: {e}")
        return None
