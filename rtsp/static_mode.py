from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import uuid
from typing import Any, Dict

from flask import Blueprint, Response, jsonify, render_template, request

from streaming.config import cv2

from piv import run_pipeline
from sensor_reader import read_sensor_once

BASE_DIR = pathlib.Path(__file__).resolve().parent
RESULTS_ROOT = BASE_DIR / "static" / "results"

static_bp = Blueprint("static_mode", __name__)

jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()


def _ensure_results_dir() -> None:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)


def _new_job_id() -> str:
    return uuid.uuid4().hex[:8]


def _worker_run_job(job_id: str, config_path: pathlib.Path, job_dir: pathlib.Path) -> None:
    try:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return
            job["status"] = "processing"
            job.setdefault("log", job.get("progress_log", []))
            job.setdefault("progress_log", job["log"])
            job.setdefault("cancel", False)

        cfg = json.loads(config_path.read_text())
        video_rel = cfg.get("video_file", "")
        video_abs = job_dir / video_rel
        summary = run_pipeline(cfg, str(video_abs), job, job_id, str(job_dir))
    except RuntimeError as e:
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                job["status"] = "error"
                job["error_message"] = str(e)
        return
    except Exception as e:
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                job["status"] = "error"
                job["error_message"] = f"Unexpected error in worker: {e}"
        return

    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job["status"] = "done"
            job["mean_speed"] = summary.get("mean_speed")
            job["max_speed"] = summary.get("max_speed")
            job["median_speed"] = summary.get("median_speed")
            job["vector_mean_speed"] = summary.get("vector_mean_speed")
            job["vector_median_speed"] = summary.get("vector_median_speed")
            job["result_image_url"] = None
            rip = summary.get("result_image_path")
            if rip:
                rp = pathlib.Path(rip)
                if rp.exists():
                    job["result_image_url"] = f"/static/results/{job_id}/{rp.name}"
            job["camera_overlay_url"] = None
            cop = summary.get("camera_overlay_path")
            if cop:
                cp = pathlib.Path(cop)
                if cp.exists():
                    job["camera_overlay_url"] = f"/static/results/{job_id}/{cp.name}"
            job["pyorc_camera_overlay_url"] = None
            pcop = summary.get("pyorc_camera_overlay_path")
            if pcop:
                pcp = pathlib.Path(pcop)
                if pcp.exists():
                    job["pyorc_camera_overlay_url"] = f"/static/results/{job_id}/{pcp.name}"


@static_bp.route("/static-mode", methods=["GET"])
def static_mode_index():
    try:
        return render_template("index_static.html")
    except Exception:
        return ("<h1>Pravah Static Mode</h1>"
                "<p>templates/index_static.html not found.</p>", 200)


@static_bp.route("/api/process", methods=["POST"])
def api_process():
    if "video" not in request.files or "config" not in request.form:
        return jsonify({"error": "Missing 'video' file or 'config' JSON field"}), 400

    video_file = request.files["video"]
    cfg_str = request.form["config"]

    try:
        cfg = json.loads(cfg_str)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Malformed config JSON: {e}"}), 400

    sensor_fallback = False
    sensor_fallback_reason = None
    sensor_pre_log = []
    if cfg.get("sensor_enabled") is True and isinstance(cfg.get("sensor_config"), dict) and cfg["sensor_config"]:
        try:
            distance_m, _ = read_sensor_once(cfg["sensor_config"])
            cam_z = float(cfg.get("lens_position", [0, 0, 0])[2])
            cfg["h_a"] = cam_z - distance_m
            sensor_pre_log.append(f"h_a from sensor: distance={distance_m:.4f} m, camZ={cam_z:.4f} m "
                                  f"→ h_a = {cfg['h_a']:.4f}")
        except RuntimeError as e:
            sensor_fallback = True
            sensor_fallback_reason = str(e)
            sensor_pre_log.append(f"WARNING: Sensor read failed ({e}). Using manual h_a = {cfg.get('h_a')}")

    _ensure_results_dir()
    job_id = _new_job_id()
    job_dir = RESULTS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_name = video_file.filename or "input_video"
    video_ext = os.path.splitext(video_name)[1] or ".mp4"
    video_name = f"input_video{video_ext}"
    video_path = job_dir / video_name
    video_file.save(str(video_path))

    cfg.setdefault("use_stabilization", False)
    cfg["video_file"] = video_name
    config_path = job_dir / "config.json"
    config_path.write_text(json.dumps(cfg, indent=2))

    with jobs_lock:
        log_list = [f"Job {job_id} created.", f"Video saved to {video_path}"] + sensor_pre_log
        jobs[job_id] = {
            "status": "queued",
            "log": log_list,
            "progress_log": log_list,
            "error_message": None,
            "mean_speed": None,
            "max_speed": None,
            "median_speed": None,
            "vector_mean_speed": None,
            "vector_median_speed": None,
            "result_image_url": None,
            "cancel": False,
            "video_path": str(video_path),
            "job_dir": str(job_dir),
            "cleanup_scheduled": False,
            "sensor_fallback": sensor_fallback,
            "sensor_fallback_reason": sensor_fallback_reason,
        }

    t = threading.Thread(
        target=_worker_run_job, args=(job_id, config_path, job_dir), daemon=True
    )
    t.start()

    return jsonify({"job_id": job_id, "status": "processing"})


@static_bp.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job_id"}), 404
        data = {
            "job_id": job_id,
            "status": job.get("status"),
            "progress_log": job.get("progress_log", job.get("log", [])),
            "sensor_fallback": job.get("sensor_fallback", False),
            "sensor_fallback_reason": job.get("sensor_fallback_reason", None),
        }
        if job.get("status") == "done":
            data.update({
                "mean_speed": job.get("mean_speed"),
                "max_speed": job.get("max_speed"),
                "median_speed": job.get("median_speed"),
                "vector_mean_speed": job.get("vector_mean_speed"),
                "vector_median_speed": job.get("vector_median_speed"),
                "result_image_url": job.get("result_image_url"),
                "camera_overlay_url": job.get("camera_overlay_url"),
                "pyorc_camera_overlay_url": job.get("pyorc_camera_overlay_url"),
            })
        if job.get("status") == "error":
            data["error_message"] = job.get("error_message")

    if data["status"] in ("done", "error"):
        with jobs_lock:
            job = jobs.get(job_id)
            if job and not job.get("cleanup_scheduled"):
                job["cleanup_scheduled"] = True
                video_path = job.get("video_path")

                def _cleanup(path_str: str):
                    if not path_str:
                        return
                    try:
                        p = pathlib.Path(path_str)
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass

                timer = threading.Timer(300.0, _cleanup, args=(video_path,))
                timer.daemon = True
                timer.start()

    return jsonify(data)


@static_bp.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job_id"}), 404
        job["cancel"] = True
        job.setdefault("progress_log", []).append("Cancellation requested by client.")
    return jsonify({"job_id": job_id, "status": "cancelling"})


@static_bp.route("/api/static/first_frame", methods=["POST"])
def api_first_frame():
    if "video" not in request.files:
        return jsonify({"error": "Missing 'video' file"}), 400
    video_file = request.files["video"]
    suffix = os.path.splitext(video_file.filename or "")[1] or ".mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        video_file.save(tmp.name)
        tmp.close()
        cap = cv2.VideoCapture(tmp.name)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return jsonify({"error": "Could not read first frame from video"}), 422
        ok2, buf = cv2.imencode(".png", frame)
        if not ok2:
            return jsonify({"error": "Could not encode frame"}), 500
        return Response(buf.tobytes(), mimetype="image/png")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
