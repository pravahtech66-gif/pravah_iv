import pathlib

import numpy as np
import cv2
import pyorc

from .job_log import _log
from .defaults import RESOLUTION


def compute_auto_resolution(gcps_src: list, gcps_dst: list) -> float:
    try:
        src = np.array(gcps_src, dtype=np.float32)
        dst = np.array(gcps_dst, dtype=np.float32)
        dst_2d = np.ascontiguousarray(dst[:, :2])

        hull_src = cv2.convexHull(src.reshape(-1, 1, 2))
        A_pixel = cv2.contourArea(hull_src)

        hull_dst = cv2.convexHull(dst_2d.reshape(-1, 1, 2))
        A_m = cv2.contourArea(hull_dst)

        if A_pixel < 1 or A_m < 1e-6:
            return RESOLUTION

        r_ortho = float(np.sqrt(A_m / A_pixel))

        r_ortho = float(np.clip(r_ortho, 0.01, 0.5))
        return r_ortho
    except Exception:
        return RESOLUTION


def compute_auto_framestep(
    video_p: pathlib.Path,
    cam_config,
    h_a: float,
    job_state: dict,
    target_fraction: float = 0.50,
    min_displacement_px: float = 3.0,
    spurious_threshold_px: float = 0.75,
    max_framestep: int = 0,
    test_frames: int = 20,
    test_ia: int = 40,
    fps_override: float = None,
) -> tuple:
    fps = None
    if fps_override is not None:
        fps = float(fps_override)
    else:
        try:
            _cap = cv2.VideoCapture(str(video_p))
            fps = _cap.get(cv2.CAP_PROP_FPS) or 25.0
            _cap.release()
        except Exception:
            fps = 25.0

    if max_framestep <= 0:
        max_framestep = max(30, int(round(fps)))

    resolution = cam_config.resolution if hasattr(cam_config, "resolution") else RESOLUTION

    _log(job_state,
         f"  [P₃] Auto-framestep search  fps={fps:.1f}  max_framestep={max_framestep}"
         f"  target={target_fraction*100:.0f}% cells > {min_displacement_px}px"
         f"  (spurious pre-filter: <{spurious_threshold_px}px excluded)"
         f"  resolution={resolution:.4f} m/px")
    _log(job_state,
         f"  [P₃] Example: 0.3 m/s flow at framestep={max_framestep} → "
         f"{0.3/resolution*(max_framestep/fps):.1f}px displacement "
         f"(need >{min_displacement_px}px for {target_fraction*100:.0f}% of cells)")

    _disp_px_at_fs1 = None
    _median_speed_ms = None
    try:
        _vid = pyorc.Video(
            fn=str(video_p),
            camera_config=cam_config,
            h_a=h_a,
            start_frame=0,
            end_frame=test_frames + 1,
            stabilize=None,
            progress=False,
            **({"fps": fps} if fps_override is not None else {}),
        )
        _frames = _vid.get_frames(method="grayscale")
        _frames = _frames.frames.normalize()
        _frames_proj = _frames.frames.project()

        if _frames_proj.shape[0] > test_frames:
            _frames_proj = _frames_proj[:test_frames]

        _piv_test = _frames_proj.frames.get_piv(
            window_size=(test_ia, test_ia),
            overlap=(0, 0),
            engine="numpy",
            ensemble_corr=False,
        )
        _piv_mean = _piv_test.mean(dim="time", keep_attrs=True)
        _vx1 = _piv_mean["v_x"].values
        _vy1 = _piv_mean["v_y"].values
        _spd_ms = np.sqrt(_vx1 ** 2 + _vy1 ** 2)
        _disp_px_at_fs1 = _spd_ms / resolution * (1.0 / fps)
        _median_speed_ms = float(np.nanmedian(_spd_ms))
        _log(job_state,
             f"  [P₃] Base PIV done (fs=1): {(~np.isnan(_disp_px_at_fs1)).sum()} valid cells, "
             f"mean speed = {float(np.nanmean(_spd_ms)):.4f} m/s")
    except Exception as e:
        _log(job_state, f"  [P₃] Base PIV at fs=1 failed: {e} — falling back to max_framestep={max_framestep}")
        return max_framestep, None

    for fs in range(1, max_framestep + 1):
        _disp_px = _disp_px_at_fs1 * float(fs)

        total_cells = _disp_px.size
        n_nan = int(np.isnan(_disp_px).sum())

        real_valid = ~np.isnan(_disp_px) & (_disp_px >= spurious_threshold_px)
        n_spurious = int((~np.isnan(_disp_px) & (_disp_px < spurious_threshold_px)).sum())

        if real_valid.sum() == 0:
            fraction = 0.0
            _log(job_state,
                 f"  [P₃] framestep={fs}: 0 cells survive pre-filter "
                 f"({n_nan}/{total_cells} NaN, {n_spurious} spurious <{spurious_threshold_px}px) "
                 f"— likely correlation failure, not slow flow.")
        else:
            n_above = int(np.sum(_disp_px[real_valid] > min_displacement_px))
            fraction = float(n_above / real_valid.sum())
            mean_disp = float(np.mean(_disp_px[real_valid]))
            _log(job_state,
                 f"  [P₃] framestep={fs}: {fraction*100:.1f}% > {min_displacement_px}px "
                 f"({n_above}/{int(real_valid.sum())} surviving, mean={mean_disp:.2f}px | "
                 f"NaN={n_nan} spurious={n_spurious} total={total_cells})")

        if fraction >= target_fraction:
            _log(job_state, f"  [P₃] Selected framestep={fs} ✓")
            return fs, _median_speed_ms

    _log(job_state, f"  [P₃] No framestep met target; using max_framestep={max_framestep}")
    return max_framestep, _median_speed_ms


def _print_computed_params(
    workflow: str,
    resolution: float,
    framestep: int,
    fps: float,
    alpha: float,
    piv_window: int,
    piv_overlap: int,
    corr_min: float,
    s2n_min: float,
    gcp_mode: str,
    n_pairs: int,
    h_a: float,
    z_0: float,
    speed_filt: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    discharge_result: dict,
    sa_params: dict,
    config: dict,
    is_auto: bool,
    estimated_speed_ms: float = None,
) -> None:
    W    = 72
    SEP  = "═" * W
    SEP2 = "─" * W

    def row(label: str, value, note: str = "") -> str:
        val_str  = str(value)
        note_str = f"   ({note})" if note else ""
        return f"  {label:<32} {val_str}{note_str}"

    fx_str = "N/A — auto-estimated by pyorc"
    cam_mat = config.get("camera_matrix")
    if cam_mat:
        try:
            fx_val = float(cam_mat[0][0])
            fx_str = f"{fx_val:.0f} px"
        except Exception:
            pass

    mean_spd = float(np.nanmean(speed_filt))
    max_spd  = float(np.nanmax(speed_filt))
    med_spd  = float(np.nanmedian(speed_filt))
    grid_h, grid_w = speed_filt.shape
    valid_cells = int(np.sum(~np.isnan(speed_filt)))

    lines = [
        "",
        SEP,
        "  QUASI-AUTO LSPIV  —  COMPUTED PARAMETERS SUMMARY".center(W),
        SEP,
        row("Workflow mode", workflow.upper()),
        row("Video FPS", f"{fps:.3f}"),
        SEP2,
        "  ── Auto-Computed Tools ──" if is_auto else "  ── Parameters (manual mode) ──",
        row("P₀  Resolution",
            f"{resolution:.4f} m/px",
            "auto from GCP convex-hull density" if is_auto else "from config"),
        row("P₃  Framestep",
            framestep,
            "auto: ≥75% cells > 3 px displacement" if is_auto else "from config"),
    ]

    if sa_params:
        n_spots = len(config.get("displacement_spots", []))
        lines += [
            row("P₂  SA downstream",
                f"{sa_params['sa_downstream']} px",
                f"auto from {n_spots} spotted particle{'s' if n_spots != 1 else ''}"),
            row("P₂  SA upstream",    f"{sa_params['sa_upstream']} px",  "per paper (fixed)"),
            row("P₂  SA spanwise",    f"{sa_params['sa_spanwise']} px",  "auto from spotted particles"),
        ]
    elif is_auto:
        lines.append(row("P₂  Searching Area", "default (no spots provided)"))

    if is_auto:
        lines += [
            row("F₀  Spatial coherence",  "applied", "Westerweel & Scarano 2005 median test"),
            row("F₅  Time aggregation",   "time-median", "robust to outlier frames"),
        ]

    if is_auto:
        if estimated_speed_ms is not None:
            _window_note = "auto from P₃ speed estimate"
        else:
            _window_note = "auto from resolution (no speed estimate)"
    else:
        _window_note = "from config"

    lines += [
        SEP2,
        "  ── Camera ──",
        row("Focal length (fx)",    fx_str),
        row("Frame size",           f"{config.get('frame_width','?')} × {config.get('frame_height','?')} px"),
        row("Camera model",         config.get("camera_model", "unspecified")),
        row("Zoom level",           config.get("zoom_level", "unspecified")),
        SEP2,
        "  ── GCP & Geometry ──",
        row("GCP calibration mode", f"{gcp_mode} ({n_pairs} pairs)"),
        row("h_a  (water surface)", f"{h_a:.4f} m"),
        row("z_0  (GCP reference)", f"{z_0:.4f} m"),
        SEP2,
        "  ── PIV Grid ──",
        row("Window size",   f"{piv_window} px",  _window_note),
        row("Overlap",       f"{piv_overlap} px",  "50% of window" if is_auto else "from config"),
        row("corr_min",      f"{corr_min:.3f}",   "adaptive (15th pct of PIV output)" if is_auto else "from config"),
        row("s2n_min",       f"{s2n_min:.3f}",    "adaptive (15th pct of PIV output)" if is_auto else "from config"),
        row("Grid shape",    f"{grid_h} rows × {grid_w} cols"),
        row("Valid cells",          f"{valid_cells} / {grid_h * grid_w}",
            f"{100.0 * valid_cells / max(grid_h * grid_w, 1):.1f}% coverage"),
        row("x range (along-flow)", f"{x_coords.min():.3f} → {x_coords.max():.3f} m"),
        row("y range (cross-flow)", f"{y_coords.min():.3f} → {y_coords.max():.3f} m"),
        SEP2,
        "  ── Surface Velocity Results ──",
        row("Alpha  (surface coeff)",  f"{alpha:.3f}"),
        row("Mean surface speed",      f"{mean_spd:.4f} m/s"),
        row("Max surface speed",       f"{max_spd:.4f} m/s"),
        row("Median surface speed",    f"{med_spd:.4f} m/s"),
        row("Depth-avg mean speed",    f"{alpha * mean_spd:.4f} m/s",  "= α × mean surface"),
    ]

    Q = discharge_result.get("Q_m3s")
    if Q is not None:
        t_dist  = discharge_result.get("transect_distances", [])
        t_depth = discharge_result.get("transect_depths", [])
        width   = (t_dist[-1] - t_dist[0]) if len(t_dist) >= 2 else 0.0
        mean_d  = float(np.mean(t_depth)) if t_depth else 0.0
        v_surf_tr = discharge_result.get("v_surface_transect", [])
        mean_vs = float(np.mean(v_surf_tr)) if v_surf_tr else 0.0
        lines += [
            SEP2,
            "  ── Discharge  (ISO 748:2021 velocity-area method) ──",
            row("Q  (total discharge)",   f"{Q:.4f} m³/s"),
            row("River width (transect)", f"{width:.2f} m"),
            row("Mean depth (transect)",  f"{mean_d:.3f} m"),
            row("Mean surface speed (transect)", f"{mean_vs:.4f} m/s"),
            row("Transect points",        len(t_dist)),
        ]

    lines += [SEP, ""]
    output = "\n".join(lines)
    try:
        print(output)
    except UnicodeEncodeError:
        print(output.encode("ascii", "replace").decode("ascii"))


def compute_auto_piv_params(resolution: float, job_state: dict,
                             target_ia_metres: float = 0.3,
                             estimated_speed_ms: float = None,
                             framestep: int = 1,
                             fps: float = 25.0) -> dict:
    try:
        if estimated_speed_ms is not None and estimated_speed_ms > 0:
            displacement_px = estimated_speed_ms / resolution * (framestep / fps)
            window_px = displacement_px * 4
            window_px = int(2 ** np.ceil(np.log2(max(window_px, 1))))
            window_px = max(16, min(128, window_px))
            _log(job_state,
                 f"  [Auto PIV] Speed-based window (P₃ estimate={estimated_speed_ms:.4f} m/s): "
                 f"disp={displacement_px:.2f}px × 4 → window={window_px}px "
                 f"(power-of-2, clamped to [16, 128])")
        else:
            window_px = int(round(target_ia_metres / max(resolution, 1e-6)))
            window_px = max(8, min(64, window_px))
            _log(job_state,
                 f"  [Auto PIV] target_IA={target_ia_metres} m ÷ {resolution:.4f} m/px"
                 f" → window={window_px} px (clamped to [8, 64], no speed estimate)")
    except Exception as e:
        _log(job_state,
             f"  [Auto PIV] WARNING: speed-based window computation failed ({e}); "
             f"falling back to target_ia_metres path")
        window_px = int(round(target_ia_metres / max(resolution, 1e-6)))
        window_px = max(8, min(64, window_px))
        _log(job_state,
             f"  [Auto PIV] target_IA={target_ia_metres} m ÷ {resolution:.4f} m/px"
             f" → window={window_px} px, overlap fallback")

    overlap_px = int(round(window_px * 0.5))
    _log(job_state,
         f"  [Auto PIV] target_IA={target_ia_metres} m ÷ {resolution:.4f} m/px"
         f" → window={window_px} px, overlap={overlap_px} px (50%)")

    return {"piv_window": window_px, "piv_overlap": overlap_px}
