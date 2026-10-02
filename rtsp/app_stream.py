from streaming.config import (
    RESULTS_ROOT,
    STREAM_TMP,
    DESKTOP,
    SENSOR_CONFIG_PATH,
    BUFFER_DIR,
    PREVIEW_PATH,
    GCP_REFERENCE_PATH,
    SNAPSHOT_CLIP_COUNT,
    ensure_dirs,
    _check_ffmpeg,
    _check_desktop_writable,
)

import dataclasses
import json
import threading
import time
import uuid
from fractions import Fraction

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from sensor_reader import list_com_ports, read_sensor_once
from streaming.session import (
    session,
    session_lock,
    _snapshot_rec,
    _snapshot_rec_lock,
    _reset_session,
    _slog,
    _session_snapshot,
)
from streaming.recorder import get_camera_recorder
from streaming.clip_manifest import mask_url_password, read_video_stream_info
from streaming.snapshot_recorder import _run_snapshot_recording
from streaming.batch_recorder import _recorder_thread
from streaming.processor import _processor_thread
from streaming.clip_queue import discard_queued_clips
from streaming.manual_recorder import _start_manual_recording, _stop_manual_recording

PREVIEW_FRESH_S = 5
PROBE_WAIT_S = 20

app = Flask(__name__, static_folder="static", template_folder="templates")

from static_mode import static_bp
app.register_blueprint(static_bp)

from camera_routes import camera_bp
app.register_blueprint(camera_bp)


@app.after_request
def add_cors_headers(resp):
    origin = request.headers.get("Origin", "")
    allowed = {
        "http://localhost:5001", "http://127.0.0.1:5001",
        "http://localhost:5002", "http://127.0.0.1:5002",
    }
    if origin in allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/")
def index():
    try:
        return render_template("index_stream.html")
    except Exception:
        return "<h1>Pravah Stream</h1><p>templates/index_stream.html not found.</p>", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/stream/start", methods=["POST"])
def api_stream_start():
    if request.content_type and "multipart" in request.content_type:
        rtsp_url = request.form.get("rtsp_url", "").strip()
        batch_duration_s = int(request.form.get("batch_duration_s", 60))
        try:
            config = json.loads(request.form.get("config", "{}"))
        except json.JSONDecodeError:
            return jsonify({"error": "Malformed config JSON"}), 400
        sensor_enabled = request.form.get("sensor_enabled") == "true"
        try:
            sensor_config = json.loads(request.form.get("sensor_config", "null"))
        except json.JSONDecodeError:
            sensor_config = None
    else:
        body = request.get_json(force=True) or {}
        rtsp_url = body.get("rtsp_url", "").strip()
        batch_duration_s = int(body.get("batch_duration_s", 60))
        config = body.get("config", {})
        sensor_enabled = body.get("sensor_enabled") is True
        sensor_config = body.get("sensor_config")

    with session_lock:
        current_status = session["status"]

    if current_status in ("running", "stopping"):
        return jsonify({"error": "Session already running"}), 409

    if not rtsp_url:
        return jsonify({"error": "rtsp_url is required"}), 400

    batch_duration_s = max(30, min(batch_duration_s, 600))

    if not isinstance(config, dict):
        return jsonify({"error": "config must be a JSON object"}), 400

    if not _check_ffmpeg():
        return jsonify({"error": "ffmpeg not found. Install ffmpeg and add it to PATH."}), 500

    sensor_fallback = False
    sensor_fallback_reason = None
    if sensor_enabled and isinstance(sensor_config, dict) and sensor_config:
        try:
            distance_m, _ = read_sensor_once(sensor_config)
            cam_z = config.get("lens_position", [0, 0, 0])[2]
            config["h_a"] = cam_z - distance_m
            _slog(f"Sensor: distance={distance_m:.4f} m, camZ={cam_z:.4f} m → h_a={config['h_a']:.4f}")
        except RuntimeError as e:
            sensor_fallback = True
            sensor_fallback_reason = str(e)
            _slog(f"Sensor fallback ({e}), using manual h_a={config.get('h_a')}")

    config.setdefault("use_stabilization", False)

    session_id = uuid.uuid4().hex[:8]
    output_dir = RESULTS_ROOT / f"stream_{session_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_name = time.strftime("%Y-%m-%d_%H-%M-%S") + "_processed_video"
    audit_dir = DESKTOP / audit_name
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        _slog(f"Audit folder created: Desktop/{audit_name}/")
    except Exception as e:
        _slog(f"⚠ Could not create audit folder: {e} — continuing without audit saves")
        audit_dir = None

    stale = discard_queued_clips()
    if stale:
        _slog(f"Discarded {stale} queued clip(s) left from an earlier session")

    stop_event = threading.Event()
    batch_ready_event = threading.Event()

    with session_lock:
        _reset_session()
        session.update({
            "status": "running",
            "rtsp_url": rtsp_url,
            "batch_duration_s": batch_duration_s,
            "sensor_fallback": sensor_fallback,
            "sensor_fallback_reason": sensor_fallback_reason,
            "_stop_event": stop_event,
            "_batch_ready_event": batch_ready_event,
            "_output_dir": output_dir,
            "_audit_dir": audit_dir,
            "_pipeline_config": config,
        })

    recorder = threading.Thread(
        target=_recorder_thread, args=(rtsp_url, stop_event), daemon=True
    )
    processor = threading.Thread(
        target=_processor_thread, args=(stop_event, batch_ready_event), daemon=True
    )
    recorder.start()
    processor.start()

    _slog(f"Session {session_id} started — batch_duration={batch_duration_s}s")
    return jsonify({"ok": True, "session_id": session_id})


@app.route("/api/stream/stop", methods=["POST"])
def api_stream_stop():
    with session_lock:
        if session["status"] not in ("running",):
            return jsonify({"error": "No active session"}), 400
        session["status"] = "stopping"
        stop_event = session["_stop_event"]
        is_rec = session.get("is_recording", False)

    if is_rec:
        _stop_manual_recording()

    if stop_event is not None:
        stop_event.set()

    _slog("Stop requested by client")
    return jsonify({"ok": True})


@app.route("/api/stream/record_snapshot", methods=["POST"])
def api_record_snapshot():
    body = request.get_json(force=True) or {}
    rtsp_url = body.get("rtsp_url", "").strip()
    if not rtsp_url:
        return jsonify({"error": "rtsp_url required"}), 400
    snapshot_duration = int(body.get("duration_s", 60))
    if not _check_ffmpeg():
        return jsonify({"error": "ffmpeg not found"}), 500

    ok, derr = _check_desktop_writable()
    if not ok:
        return jsonify({"error": f"Desktop not writable: {derr}"}), 500

    with _snapshot_rec_lock:
        if _snapshot_rec["status"] in ("recording", "saving"):
            return jsonify({"error": "Snapshot recording already in progress"}), 409
        _snapshot_rec.update({"status": "recording", "path": None, "error": None,
                              "clip_index": 0, "total_clips": SNAPSHOT_CLIP_COUNT,
                              "saved_paths": [], "folder": None, "attempt": None})

    STREAM_TMP.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(target=_run_snapshot_recording, args=(rtsp_url, snapshot_duration), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/stream/snapshot_status", methods=["GET"])
def api_snapshot_status():
    with _snapshot_rec_lock:
        return jsonify(dict(_snapshot_rec))


@app.route("/api/stream/save_batch", methods=["POST"])
def api_stream_save_batch():
    with session_lock:
        if session["status"] != "running":
            return jsonify({"error": "No active session"}), 400
        if session["_save_next_batch"]:
            return jsonify({"error": "A save is already queued"}), 409
        if session["extra_save_status"] in ("recording", "saving"):
            return jsonify({"error": "A save is already in progress"}), 409
        session["_save_next_batch"] = True
    _slog("[save] Extra batch save queued by user")
    return jsonify({"ok": True})


@app.route("/api/stream/status", methods=["GET"])
def api_stream_status():
    snap = _session_snapshot()
    return jsonify(snap)


@app.route("/api/stream/config", methods=["PATCH"])
def api_stream_config():
    body = request.get_json(force=True) or {}
    new_duration = body.get("batch_duration_s")
    if new_duration is None:
        return jsonify({"error": "batch_duration_s required"}), 400

    new_duration = int(new_duration)
    new_duration = max(30, min(new_duration, 600))

    with session_lock:
        session["batch_duration_s"] = new_duration
        session["_drop_current_batch"] = True

    _slog(f"Batch duration changed to {new_duration}s")
    return jsonify({"ok": True})


@app.route("/api/stream/results", methods=["GET"])
def api_stream_results():
    with session_lock:
        results = list(session["results"])
    return jsonify({"results": results})


def _preview_is_fresh() -> bool:
    try:
        return time.time() - PREVIEW_PATH.stat().st_mtime < PREVIEW_FRESH_S
    except OSError:
        return False


@app.route("/api/stream/probe", methods=["GET"])
def api_stream_probe():
    rtsp_url = request.args.get("rtsp_url", "").strip()
    if not rtsp_url:
        return jsonify({"ok": False, "error": "rtsp_url query param required"})

    recorder = get_camera_recorder()
    recorder.start_recording(rtsp_url)
    deadline = time.time() + PROBE_WAIT_S
    while not _preview_is_fresh():
        if time.time() > deadline:
            return jsonify({"ok": False, "error": recorder.describe_recorder_status().last_error
                            or "no video from camera"})
        time.sleep(0.5)

    pieces = sorted(BUFFER_DIR.glob("*.mkv"), key=lambda p: p.stat().st_mtime)
    info = read_video_stream_info(pieces[-1]) if pieces else None
    if info is None:
        return jsonify({"ok": False, "error": "no video from camera"})
    rate = info["avg_frame_rate"] or "0/1"
    fps = float(Fraction(rate)) if not rate.endswith("/0") else 0.0
    return jsonify({"ok": True, "fps": fps, "width": info["width"], "height": info["height"],
                    "codec": info["codec"]})


@app.route("/api/stream/recorder_status", methods=["GET"])
def api_stream_recorder_status():
    status = dataclasses.asdict(get_camera_recorder().describe_recorder_status())
    status["rtsp_url"] = mask_url_password(status["rtsp_url"])
    return jsonify(status)


@app.route("/api/stream/record/start", methods=["POST"])
def api_stream_record_start():
    body = request.get_json(silent=True) or {}
    with session_lock:
        if session.get("is_recording"):
            return jsonify({"ok": False, "error": "Manual recording already running"}), 409
        session_url = session["rtsp_url"]
    rtsp_url = ((body.get("rtsp_url") or "").strip() or session_url
                or get_camera_recorder().recording_url())
    if not rtsp_url:
        return jsonify({"ok": False, "error": "rtsp_url required"}), 400
    filename = _start_manual_recording(rtsp_url)
    return jsonify({"ok": True, "file": filename})


@app.route("/api/stream/record/stop", methods=["POST"])
def api_stream_record_stop():
    with session_lock:
        is_rec = session.get("is_recording")
    if not is_rec:
        return jsonify({"ok": False, "error": "No manual recording running"}), 400
    saved = _stop_manual_recording()
    if not saved:
        return jsonify({"ok": False, "error": "nothing was recorded"}), 500
    return jsonify({"ok": True, "file": ", ".join(p.name for p in saved)})


@app.route("/api/stream/snapshot", methods=["GET"])
def api_stream_snapshot():
    rtsp_url = request.args.get("rtsp_url", "").strip()
    if not rtsp_url:
        return jsonify({"ok": False, "error": "rtsp_url query param required"}), 400

    get_camera_recorder().start_recording(rtsp_url)
    if not _preview_is_fresh():
        return jsonify({"ok": False, "error": "no recent frame from camera"}), 502
    try:
        jpeg = PREVIEW_PATH.read_bytes()
    except OSError as e:
        return jsonify({"ok": False, "error": f"could not read preview: {e}"}), 502
    GCP_REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GCP_REFERENCE_PATH.write_bytes(jpeg)
    return Response(jpeg, mimetype="image/jpeg")


@app.route("/api/stream/live", methods=["GET"])
def api_stream_live():
    rtsp_url = request.args.get("rtsp_url", "").strip()
    if not rtsp_url:
        return jsonify({"error": "rtsp_url required"}), 400

    get_camera_recorder().start_recording(rtsp_url)

    def generate():
        last_mtime = None
        while True:
            try:
                mtime = PREVIEW_PATH.stat().st_mtime
                jpeg = PREVIEW_PATH.read_bytes() if mtime != last_mtime else None
            except OSError:
                jpeg = None
            if jpeg:
                last_mtime = mtime
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpeg + b"\r\n")
            time.sleep(0.25)

    resp = Response(
        stream_with_context(generate()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/api/sensor/config", methods=["GET"])
def api_sensor_config_get():
    if SENSOR_CONFIG_PATH.exists():
        return jsonify(json.loads(SENSOR_CONFIG_PATH.read_text()))
    return jsonify({})


@app.route("/api/sensor/config", methods=["POST"])
def api_sensor_config_save():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON object"}), 400
    SENSOR_CONFIG_PATH.write_text(json.dumps(data, indent=2))
    return jsonify({"ok": True})


@app.route("/api/sensor/test", methods=["POST"])
def api_sensor_test():
    sensor_cfg = request.get_json(force=True)
    try:
        distance_m, raw = read_sensor_once(sensor_cfg)
        return jsonify({"ok": True, "value_m": distance_m, "value_raw": raw, "unit": sensor_cfg.get("unit", "m")})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/sensor/ports", methods=["GET"])
def api_sensor_ports():
    return jsonify({"ports": list_com_ports()})


if __name__ == "__main__":
    ensure_dirs()
    banner = "\n".join([
        "",
        "================================================",
        "  Pravah Stream Mode — Local Server",
        "================================================",
        "  http://localhost:5002",
        "  Press Ctrl+C to stop.",
        "================================================",
    ])
    print(banner)
    app.run(host="127.0.0.1", port=5002, debug=False, threaded=True)
