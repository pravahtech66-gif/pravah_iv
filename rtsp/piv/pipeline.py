import contextlib
import copy
import pathlib
import warnings

import numpy as np
import cv2
import pyorc

from modbus_publisher import print_modbus_registers

from .job_log import _log
from .defaults import (
    PIV_CORR_MIN,
    PIV_S2N_MIN,
    RESOLUTION,
    PIV_WINDOW_SIZE,
    PIV_OVERLAP,
    REQUIRED_KEYS,
    INTRINSICS_RNG_SEED,
)
from .geometry import normalize_aoi_corners
from .filters import (
    quality_filter_piv,
    filter_velocity_field,
    _apply_pyorc_mask,
    apply_spatial_coherence_filter,
    _compute_adaptive_quality_thresholds,
)
from .flow_direction import compute_flow_direction_auto, project_velocities_along_flow
from .visualize import save_camera_overlay, visualize
from .auto_params import (
    compute_auto_resolution,
    compute_auto_framestep,
    _print_computed_params,
    compute_auto_piv_params,
)
from .water_mask import restrict_grid_to_water, compute_sa_from_spots
from .discharge import compute_discharge
from .diagnostics import (
    config_sha1,
    env_versions,
    field_stats,
    log_camera_model,
    log_piv_stats,
    log_time_axis,
    rng_fingerprint,
    write_debug_json,
)

if not hasattr(pyorc, "CameraConfig"):
    raise ImportError(
        "Wrong 'pyorc' package installed (got Apache ORC file format library). "
        "Install pyOpenRiverCam instead:\n"
        "  pip uninstall pyorc && pip install pyopenrivercam"
    )


@contextlib.contextmanager
def _seeded_numpy_rng(seed):
    state = np.random.get_state()
    np.random.seed(seed)
    try:
        yield
    finally:
        np.random.set_state(state)


def resolve_h_ref(config, h_a):
    if config.get("h_ref") is not None:
        return float(config["h_ref"])
    gcps = config.get("gcps")
    if isinstance(gcps, dict) and gcps.get("h_ref") is not None:
        return float(gcps["h_ref"])
    return float(h_a)


def run_pipeline(config: dict, video_path: str, job_state: dict, job_id: str, output_dir: str) -> dict:
    job_state.setdefault("log", [])
    job_state.setdefault("cancel", False)

    for key in REQUIRED_KEYS:
        if key not in config:
            raise RuntimeError(f"Missing required config key: {key}")

    video_p = pathlib.Path(video_path)
    if not video_p.exists():
        raise RuntimeError(f"Video file not found: {video_path}")

    workflow = config.get(
        "lspiv_workflow", config.get("workflow", "quasi_automated")
    ).strip().lower()
    is_quasi = workflow == "quasi_automated"
    is_auto  = is_quasi or (workflow == "assisted")

    _log(job_state, f"[quasi_auto pipeline] Workflow: {workflow.upper()}")
    _log(job_state, f"[quasi_auto pipeline] Video  : {video_path}")

    cap = cv2.VideoCapture(str(video_p))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_px = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_raw = cap.get(cv2.CAP_PROP_FPS)
    tot  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    fps = float(fps_raw)
    fps_forced = not (1.0 <= fps <= 240.0)
    if fps_forced:
        fps = 25.0
        _log(job_state, f"  WARNING: CAP_PROP_FPS returned {fps_raw!r} — using {fps} and forcing it "
                        "on pyorc.Video. Velocities are only correct if the file really is 25 fps.")
    _log(job_state, f"  Resolution : {w}×{h_px}px | FPS: {fps:.1f} | Frames: {tot}")

    env = env_versions()
    _log(job_state, "  Environment   : " + ", ".join(f"{k}={v}" for k, v in env.items()))
    debug = {
        "job_id": job_id,
        "workflow": workflow,
        "env": env,
        "video": {"path": str(video_p), "width": w, "height": h_px,
                  "fps_from_file": float(fps_raw), "fps_used": fps, "fps_forced": fps_forced,
                  "total_frames": tot},
        "config_echo": {k: config.get(k) for k in (
            "frames", "framestep", "piv_window_size", "piv_overlap", "piv_corr_min",
            "piv_s2n_min", "resolution", "use_stabilization", "h_a", "h_ref",
            "lens_position", "frame_width", "frame_height")},
        "config_sha1": config_sha1(config),
    }
    _log(job_state, f"  Config sha1   : {debug['config_sha1']}  (same hash => same inputs to this run)")

    water_height_method = config.get("water_height_method", "manual").strip().lower()

    if water_height_method == "staff_gauge":
        try:
            from staff_gauge_reader.staff_gauge_estimator import StaffGaugeEstimator
            _sg_cfg = config.get("water_height_config", {})
            _sg_estimator = StaffGaugeEstimator(_sg_cfg)
            h_a, _sg_conf = _sg_estimator.estimate(video_path)
            print(f"[StaffGauge] h_a estimated: {h_a:.4f} m (confidence: {_sg_conf:.2f})")
            _log(job_state, f"[StaffGauge] h_a estimated: {h_a:.4f} m (confidence: {_sg_conf:.2f})")
            if _sg_conf < 0.4:
                _fallback = config.get("h_a")
                if _fallback is not None:
                    _log(job_state,
                         f"[StaffGauge] Low confidence ({_sg_conf:.2f}) — "
                         f"falling back to config h_a={_fallback}")
                    h_a = float(_fallback)
                else:
                    raise ValueError(
                        f"[StaffGauge] h_a confidence too low ({_sg_conf:.2f} < 0.4) "
                        "and no fallback 'h_a' key found in config. "
                        "Provide a manual h_a or improve gauge visibility."
                    )
        except ImportError as _e:
            _log(job_state,
                 f"[StaffGauge] staff_gauge_reader not available ({_e}); "
                 "falling back to manual h_a.")
            if "h_a" not in config:
                raise ValueError(
                    "water_height_method='staff_gauge' but staff_gauge_reader "
                    "could not be imported, and no fallback 'h_a' in config."
                ) from _e
            h_a = float(config["h_a"])
    else:
        h_a = float(config["h_a"])

    h_ref = resolve_h_ref(config, h_a)
    if h_ref != h_a:
        _log(job_state, f"  Water level differs from GCP survey: h_a - h_ref = {h_a - h_ref:+.4f} m "
                        "(the water plane moves by this amount)")

    src_pts  = config["gcps"]["src"]
    dst_pts  = config["gcps"]["dst"]
    n_pairs  = len(src_pts)
    dst_dims = len(dst_pts[0]) if len(dst_pts) > 0 else 0

    if n_pairs != len(dst_pts):
        raise RuntimeError(f"GCP src/dst length mismatch ({n_pairs} vs {len(dst_pts)}).")
    if n_pairs < 4:
        raise RuntimeError("At least 4 GCP pairs are required.")
    if dst_dims not in (2, 3):
        raise RuntimeError(f"GCP destination points must be 2D or 3D; found {dst_dims}D.")

    if dst_dims == 3 and n_pairs >= 6:
        gcp_mode = "3D"
    else:
        if dst_dims == 3 and n_pairs < 6:
            _log(job_state, "  NOTE: 3D GCP calibration needs >=6 pairs in pyorc.")
            _log(job_state, f"  Found {n_pairs} pairs -> auto-switching to 2D GCP mode.")
            dst_pts = [[float(p[0]), float(p[1])] for p in dst_pts]
        gcp_mode = "2D"
        dst_dims = 2

    gcps = {
        "src":   src_pts,
        "dst":   dst_pts,
        "z_0":   float(config["gcps"]["z_0"]),
        "h_ref": h_ref,
    }

    if is_auto:
        resolution = compute_auto_resolution(
            config["gcps"]["src"],
            config["gcps"]["dst"],
        )
        _log(job_state, f"  [P₀] Auto resolution: {resolution:.4f} m/px (from GCP density)")
    else:
        resolution = float(config.get("resolution", RESOLUTION))
        _log(job_state, f"  Resolution (manual): {resolution:.4f} m/px")

    alpha = float(config.get("surface_coefficient", config.get("alpha", 0.85)))

    if is_auto and "piv_window_size" not in config:
        _prelim_window = int(round(0.3 / max(resolution, 1e-6)))
        _prelim_window = max(8, min(64, _prelim_window))
    else:
        _prelim_window = int(config.get("piv_window_size", PIV_WINDOW_SIZE))

    corr_min = float(config.get("piv_corr_min", PIV_CORR_MIN))
    s2n_min  = float(config.get("piv_s2n_min",  PIV_S2N_MIN))

    _log(job_state, f"  Alpha (surface coeff): {alpha:.2f}")
    _log(job_state, f"  GCP mode: {gcp_mode} ({n_pairs} pairs)")
    _log(job_state, f"  Water level: z_0={gcps['z_0']:.4f}, h_ref={gcps['h_ref']:.4f}, h_a={h_a:.4f}")

    cam_kwargs = dict(
        height=config["frame_height"],
        width=config["frame_width"],
        gcps=gcps,
        lens_position=list(config["lens_position"]),
        resolution=resolution,
        window_size=int(_prelim_window),
    )
    rng_fp = rng_fingerprint()
    debug["numpy_rng_fingerprint_before_cameraconfig"] = rng_fp
    debug["intrinsics_rng_seed"] = INTRINSICS_RNG_SEED
    _log(job_state, f"  numpy RNG fingerprint before CameraConfig: {rng_fp}"
                    f"  (fit runs under fixed seed {INTRINSICS_RNG_SEED}, so fx does not depend on it)")
    try:
        with _seeded_numpy_rng(INTRINSICS_RNG_SEED):
            cam_config = pyorc.CameraConfig(**cam_kwargs)
    except Exception as e:
        raise RuntimeError(f"ERROR building CameraConfig: {e}")
    try:
        cam_config.set_lens_position(*config["lens_position"])
    except Exception as e:
        raise RuntimeError(f"ERROR setting lens position: {e}")
    try:
        aoi_corners = normalize_aoi_corners(config["aoi_corners"])
        cam_config.set_bbox_from_corners(aoi_corners)
    except Exception as e:
        raise RuntimeError(f"ERROR setting AOI corners: {e}")

    _log(job_state, "CameraConfig built OK.")
    _log(job_state, "  --- Camera model diagnostics ---")
    debug["camera"] = log_camera_model(job_state, cam_config, config, gcps, h_a)
    debug["camera"]["gcp_mode"] = gcp_mode
    debug["camera"]["n_gcps"] = n_pairs

    sa_params = None
    if is_quasi and config.get("displacement_spots"):
        sa_params = compute_sa_from_spots(
            config["displacement_spots"],
            fps=fps,
            framestep=1,
            job_state=job_state,
        )

    if is_auto:
        framestep, estimated_speed_ms = compute_auto_framestep(
            video_p=video_p,
            cam_config=cam_config,
            h_a=h_a,
            job_state=job_state,
            fps_override=fps if fps_forced else None,
        )
    else:
        framestep = int(config.get("framestep", 1))
        estimated_speed_ms = None
    _log(job_state, f"  Framestep: {framestep}")

    if is_auto and "piv_window_size" not in config:
        _auto = compute_auto_piv_params(
            resolution, job_state,
            estimated_speed_ms=estimated_speed_ms,
            framestep=framestep,
            fps=fps,
        )
        piv_window  = _auto["piv_window"]
        piv_overlap = _auto["piv_overlap"]
    else:
        piv_window  = int(config.get("piv_window_size", PIV_WINDOW_SIZE))
        piv_overlap = int(config.get("piv_overlap", PIV_OVERLAP))
        _log(job_state,
             f"  PIV window/overlap from config: window={piv_window}px, overlap={piv_overlap}px")

    _log(job_state, f"  PIV initial params: window={piv_window}, overlap={piv_overlap}, "
         f"corr_min={corr_min} (adaptive), s2n_min={s2n_min} (adaptive)")

    if is_quasi and config.get("displacement_spots"):
        sa_params = compute_sa_from_spots(
            config["displacement_spots"],
            fps=fps,
            framestep=framestep,
            job_state=job_state,
        )
        if sa_params:
            sa_down = sa_params["sa_downstream"]
            piv_overlap = max(0, piv_window - sa_down // 2)
            _log(job_state, f"  [P₂] piv_overlap adjusted to {piv_overlap}px based on SA_downstream={sa_down}px")

    flow_direction_angle = None
    flow_unit_vector     = None
    flow_coherence       = None

    stabilize_polygon = aoi_corners if config.get("use_stabilization", False) else None
    if stabilize_polygon is not None:
        _log(job_state, "  WARNING: use_stabilization=true with the AOI as the polygon — pyorc treats "
                        "everything OUTSIDE it as rigid land, including open water outside the AOI")

    _log(job_state, "=" * 56)
    _log(job_state, f"  Running quasi-automated LSPIV pipeline ({workflow.upper()})")
    _log(job_state, "=" * 56)

    if job_state.get("cancel"):
        raise RuntimeError("Job cancelled")

    n_frames  = int(config.get("frames", 100))
    end_frame = min(n_frames * framestep, tot)

    achievable_pairs = max(0, end_frame // max(framestep, 1) - 1)
    if achievable_pairs < 25:
        _log(job_state,
             f"  WARNING [frame budget]: only ~{achievable_pairs} frame-pairs at "
             f"framestep={framestep} (clip has {tot} frames) — time aggregate may be "
             f"noisy; use a longer clip for ≥25 pairs.")

    _log(job_state, f"STEP 1/6: Opening video (frames 0–{end_frame}, every {framestep}th)...")
    if stabilize_polygon is not None:
        _log(job_state, f"  Stabilization polygon enabled with {len(stabilize_polygon)} AOI corners")
    video_kwargs = dict(
        fn=str(video_p),
        camera_config=cam_config,
        h_a=h_a,
        start_frame=0,
        end_frame=end_frame,
        stabilize=stabilize_polygon,
        progress=True,
    )
    if fps_forced:
        video_kwargs["fps"] = fps
    try:
        video = pyorc.Video(**video_kwargs)
    except Exception as e:
        raise RuntimeError(f"ERROR opening pyorc Video: {e}")

    if job_state.get("cancel"):
        raise RuntimeError("Job cancelled")
    _log(job_state, "STEP 2/6: Reading frames as grayscale...")
    try:
        frames = video.get_frames(method="grayscale")
        debug["time_axis_all_frames"] = log_time_axis(job_state, frames, "all frames")
        if framestep > 1:
            frames = frames[::framestep]
            debug["time_axis_subsampled"] = log_time_axis(job_state, frames, f"framestep={framestep}")
    except Exception as e:
        raise RuntimeError(f"ERROR in video.get_frames(): {e}")
    try:
        _log(job_state, f"  pyorc Video: fps={float(video.fps):.3f} start={video.start_frame} "
                        f"end={video.end_frame} stabilize={'on' if stabilize_polygon is not None else 'off'}")
        debug["pyorc_video"] = {"fps": float(video.fps), "start_frame": int(video.start_frame),
                                "end_frame": int(video.end_frame)}
    except Exception as e:
        _log(job_state, f"  WARNING [debug]: pyorc Video attributes unavailable: {e}")

    if job_state.get("cancel"):
        raise RuntimeError("Job cancelled")
    _log(job_state, "STEP 3/6: Normalizing frames (removing static background)...")
    try:
        frames = frames.frames.normalize()
    except Exception as e:
        _log(job_state, f"WARNING: normalize() failed ({e}) -- continuing without normalization.")

    if job_state.get("cancel"):
        raise RuntimeError("Job cancelled")
    _log(job_state, "STEP 4/6: Projecting frames to real-world coordinates...")
    try:
        frames_proj = frames.frames.project()
        _log(job_state, f"  Projected frames shape : {frames_proj.shape}")
        x_vals = frames_proj.coords["x"].values
        y_vals = frames_proj.coords["y"].values
        _log(job_state, f"  x coords range : {x_vals.min():.3f} -> {x_vals.max():.3f} m")
        _log(job_state, f"  y coords range : {y_vals.min():.3f} -> {y_vals.max():.3f} m")
    except Exception as e:
        raise RuntimeError(f"ERROR in frames.project(): {e}")

    if job_state.get("cancel"):
        raise RuntimeError("Job cancelled")
    _log(job_state, "STEP 5/6: Running PIV (engine=numpy)...")
    try:
        piv = frames_proj.frames.get_piv(
            window_size=(int(piv_window), int(piv_window)),
            overlap=(int(piv_overlap), int(piv_overlap)),
            engine="numpy",
            ensemble_corr=False,
        )
    except Exception as e:
        raise RuntimeError(f"ERROR in frames.get_piv(): {e}")
    debug["piv_raw"] = log_piv_stats(job_state, piv, "raw")

    if is_auto:
        corr_min, s2n_min = _compute_adaptive_quality_thresholds(piv, job_state)

    if job_state.get("cancel"):
        raise RuntimeError("Job cancelled")
    _log(job_state, "STEP 6/6: Filtering and computing velocity field...")

    piv_ds = copy.deepcopy(piv)

    if is_auto:
        piv_ds = restrict_grid_to_water(piv_ds, frames_proj, job_state)

    if is_auto:
        piv_ds = apply_spatial_coherence_filter(job_state, piv_ds)

    try:
        _ = piv_ds.velocimetry
        has_velocimetry = True
    except Exception:
        has_velocimetry = False

    if has_velocimetry:
        _log(job_state, "  Applying pyorc mask chain...")
        total_cells = piv_ds["v_x"].size
        nan_before  = int(np.isnan(piv_ds["v_x"].values).sum())

        _apply_pyorc_mask(job_state, piv_ds, "corr")
        _apply_pyorc_mask(job_state, piv_ds, "minmax")
        _apply_pyorc_mask(job_state, piv_ds, "rolling")
        _apply_pyorc_mask(job_state, piv_ds, "outliers")
        _apply_pyorc_mask(job_state, piv_ds, "variance")
        _apply_pyorc_mask(job_state, piv_ds, "count")
        if flow_direction_angle is not None:
            _apply_pyorc_mask(
                job_state, piv_ds, "angle",
                angle_expected=flow_direction_angle,
                angle_tolerance=0.5 * np.pi,
            )

        nan_after = int(np.isnan(piv_ds["v_x"].values).sum())
        kept      = total_cells - nan_after
        removed   = nan_after - nan_before
        _log(job_state, f"  Pyorc mask chain: {kept}/{total_cells} cells surviving "
             f"({removed} removed by filters, {nan_before} were already NaN)")
    else:
        _log(job_state, "  WARNING: pyorc velocimetry accessor not available -- using v2 fallback filters.")
        piv_ds = quality_filter_piv(job_state, piv_ds, corr_min=corr_min, s2n_min=s2n_min)

    try:
        if is_auto:
            _log(job_state, "  [F₅] Time-median aggregation (robust to outliers)")
            piv_mean = piv_ds.median(dim="time", keep_attrs=True)
        else:
            piv_mean = piv_ds.mean(dim="time", keep_attrs=True)
    except Exception as e:
        raise RuntimeError(f"ERROR aggregating PIV results: {e}")

    try:
        piv_mean.velocimetry.mask.window_mean(wdw=2, tolerance=0.5, inplace=True, reduce_time=True)
        _log(job_state, "  Applied window_mean spatial filter (reduce_time=True)")
    except Exception:
        try:
            piv_mean.velocimetry.mask.window_mean(wdw=2, tolerance=0.5, inplace=True)
            _log(job_state, "  Applied window_mean spatial filter")
        except Exception as e2:
            _log(job_state, f"  WARNING: window_mean failed: {e2}")

    v_x      = piv_mean["v_x"].values
    v_y      = piv_mean["v_y"].values
    speed    = np.sqrt(v_x**2 + v_y**2)
    x_coords = piv_mean.coords["x"].values
    y_coords = piv_mean.coords["y"].values

    speed_raw = speed.copy()
    speed_filt, v_x_filt, v_y_filt = filter_velocity_field(job_state, speed, v_x, v_y)
    debug["piv_masked"] = log_piv_stats(job_state, piv_ds, "masked")
    debug["result_raw"] = field_stats(speed_raw)
    debug["result_filtered"] = field_stats(speed_filt)

    corr_field = piv_mean["corr"].values if "corr" in piv_mean else None
    try:
        flow_direction_angle, flow_unit_vector, flow_coherence = compute_flow_direction_auto(
            job_state, v_x_filt, v_y_filt, corr=corr_field,
        )
    except Exception as e:
        _log(job_state, f"  WARNING: automatic flow-direction estimation failed ({e}) — skipping along-stream projection.")
        flow_direction_angle = flow_unit_vector = flow_coherence = None

    v_along = v_cross = None
    vector_mean_speed   = None
    vector_median_speed = None
    if flow_unit_vector is not None:
        dx, dy = flow_unit_vector
        vx_t = piv_ds["v_x"].values
        vy_t = piv_ds["v_y"].values
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mag_t    = np.sqrt(vx_t ** 2 + vy_t ** 2)
            dot_t    = vx_t * dx + vy_t * dy
            signed_t = np.where(dot_t >= 0, mag_t, -mag_t)
            speed_signed = (np.nanmedian(signed_t, axis=0)
                            if is_auto else np.nanmean(signed_t, axis=0))
        speed_signed = np.where(np.isnan(v_x_filt), np.nan, speed_signed)
        surface_speed_grid = speed_signed
        speed_basis = "signed-magnitude along flow (auto direction)"

        v_along, v_cross = project_velocities_along_flow(v_x_filt, v_y_filt, flow_unit_vector)

        vx_mean  = float(np.nanmean(v_x_filt))
        vy_mean  = float(np.nanmean(v_y_filt))
        vector_mean_speed   = float(np.sqrt(vx_mean**2 + vy_mean**2))
        vx_med   = float(np.nanmedian(v_x_filt))
        vy_med   = float(np.nanmedian(v_y_filt))
        vector_median_speed = float(np.sqrt(vx_med**2 + vy_med**2))
    else:
        surface_speed_grid = speed_filt
        speed_basis = "vector magnitude (flow direction unavailable)"

    mean_surface   = float(np.nanmean(surface_speed_grid))
    median_surface = float(np.nanmedian(surface_speed_grid))
    max_surface    = float(np.nanmax(surface_speed_grid))

    _log(job_state, "=" * 56)
    _log(job_state, f"  [QUASI AUTO] Workflow: {workflow.upper()} | alpha={alpha:.2f}")
    _log(job_state, f"  PIV grid size       : {speed_filt.shape[0]} x {speed_filt.shape[1]} windows")
    _log(job_state, f"  x range             : {x_coords.min():.3f} -> {x_coords.max():.3f} m")
    _log(job_state, f"  y range             : {y_coords.min():.3f} -> {y_coords.max():.3f} m")
    _log(job_state, "")
    _log(job_state, "  --- Surface velocity (before alpha correction) ---")
    _log(job_state, f"  Speed basis         : {speed_basis}")
    _log(job_state, f"  Mean surface speed  : {mean_surface:.4f} m/s")
    _log(job_state, f"  Max surface speed   : {max_surface:.4f} m/s")
    _log(job_state, f"  Median surface speed: {median_surface:.4f} m/s")
    _log(job_state, f"  Depth-avg mean speed: {alpha * mean_surface:.4f} m/s  (alpha×surface)")
    if vector_mean_speed is not None:
        n_upstream = int(np.nansum(surface_speed_grid < 0))
        _log(job_state, f"  (ref) |mean vector| : {vector_mean_speed:.4f} m/s  (magnitude method — under-reads when noisy)")
        _log(job_state, f"  (ref) |median vector|: {vector_median_speed:.4f} m/s")
        _log(job_state, f"  Upstream cells      : {n_upstream} (v_along < 0, likely noise)")

    viz_results = {
        "speed":     speed_filt,
        "speed_raw": speed_raw,
        "v_x":       v_x_filt,
        "v_y":       v_y_filt,
        "x_coords":  x_coords,
        "y_coords":  y_coords,
    }

    if flow_unit_vector is not None:
        viz_results.update({
            "v_along":          v_along,
            "v_cross":          v_cross,
            "flow_unit_vector": flow_unit_vector,
            "flow_angle_deg":   np.degrees(flow_direction_angle),
            "flow_coherence":   flow_coherence,
        })

    _log(job_state, "=" * 56)

    discharge_result = {}
    if config.get("transect"):
        discharge_result = compute_discharge(
            v_x_filt, v_y_filt, x_coords, y_coords,
            config["transect"], alpha, job_state,
            speed_grid=surface_speed_grid,
        )
        if discharge_result.get("Q_m3s") is not None:
            _log(job_state, f"  DISCHARGE Q : {discharge_result['Q_m3s']:.4f} m³/s")

    out_dir     = pathlib.Path(output_dir)
    stem        = video_p.stem
    out_png     = out_dir / f"{stem}_piv_quasi_auto_{workflow}.png"
    out_overlay = out_dir / f"{stem}_camera_overlay_quasi.png"

    try:
        visualize(job_state, viz_results, video_path, out_png)
    except Exception as e:
        _log(job_state, f"WARNING: Visualization failed: {e}")
    save_camera_overlay(job_state, video, piv_mean, out_overlay)

    if not np.isfinite(mean_surface):
        write_debug_json(job_state, out_dir, stem, debug)
        raise RuntimeError(
            "No valid velocity vectors survived filtering, so this clip has no measurement. "
            "The log above shows which filter removed them."
        )

    print_modbus_registers({
        "mean_speed":   mean_surface,
        "max_speed":    max_surface,
        "median_speed": median_surface,
    })

    _print_computed_params(
        workflow=workflow,
        resolution=resolution,
        framestep=framestep,
        fps=fps,
        alpha=alpha,
        piv_window=piv_window,
        piv_overlap=piv_overlap,
        corr_min=corr_min,
        s2n_min=s2n_min,
        gcp_mode=gcp_mode,
        n_pairs=n_pairs,
        h_a=h_a,
        z_0=float(gcps["z_0"]),
        speed_filt=surface_speed_grid,
        x_coords=x_coords,
        y_coords=y_coords,
        discharge_result=discharge_result,
        sa_params=sa_params,
        config=config,
        is_auto=is_auto,
        estimated_speed_ms=estimated_speed_ms,
    )

    debug["summary"] = {
        "mean_speed": mean_surface,
        "max_speed": max_surface,
        "median_speed": median_surface,
        "speed_basis": speed_basis,
        "framestep": framestep,
        "resolution": resolution,
        "piv_window": piv_window,
        "piv_overlap": piv_overlap,
        "corr_min": corr_min,
        "s2n_min": s2n_min,
        "grid_shape": list(speed_filt.shape),
    }
    debug_json_path = write_debug_json(job_state, out_dir, stem, debug)

    return {
        "workflow":              workflow,
        "framestep_used":        framestep,
        "resolution_used":       resolution,
        "alpha":                 alpha,
        "mean_speed":            mean_surface,
        "max_speed":             max_surface,
        "median_speed":          median_surface,
        "mean_depth_avg_speed":  float(alpha * mean_surface),
        "speed_basis":           speed_basis,
        **({"vector_mean_speed":   vector_mean_speed,
            "vector_median_speed": vector_median_speed}
           if vector_mean_speed is not None else {}),
        **discharge_result,
        "result_image_path":    str(out_png.resolve()) if out_png.exists() else None,
        "camera_overlay_path":  str(out_overlay.resolve()) if out_overlay.exists() else None,
        "debug_json_path":      debug_json_path,
        "grid_shape":           list(speed_filt.shape),
        "x_range":              [float(x_coords.min()), float(x_coords.max())],
        "y_range":              [float(y_coords.min()), float(y_coords.max())],
    }
