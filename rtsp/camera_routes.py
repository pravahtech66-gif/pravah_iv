from flask import Blueprint, jsonify, request

from camera_request_validation import (validate_camera_rtsp_url,
                                       validate_camera_write_request)
from streaming import camera_onvif

camera_bp = Blueprint("camera", __name__)

_CAMERA_DOWN = "camera did not answer"


@camera_bp.route("/api/camera/settings", methods=["GET"])
def camera_settings_read():
    rtsp_url = request.args.get("rtsp_url")
    error = validate_camera_rtsp_url(rtsp_url)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    settings = camera_onvif.read_camera_stream_settings(rtsp_url)
    if settings is None:
        return jsonify({"ok": False, "error": _CAMERA_DOWN})
    return jsonify({
        "ok": True,
        "settings": settings,
        "recommended": camera_onvif.RECOMMENDED_STREAM_SETTINGS,
        "mismatches": camera_onvif.describe_settings_mismatches(settings),
    })


@camera_bp.route("/api/camera/settings/apply", methods=["POST"])
def camera_settings_apply():
    payload = request.get_json(silent=True)
    error = validate_camera_write_request(payload)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    result = camera_onvif.apply_recommended_stream_settings(payload["rtsp_url"])
    if result is None:
        return jsonify({"ok": False, "error": _CAMERA_DOWN})
    return jsonify({"ok": True, **result})


@camera_bp.route("/api/camera/clock/sync", methods=["POST"])
def camera_clock_sync():
    payload = request.get_json(silent=True)
    error = validate_camera_write_request(payload)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    result = camera_onvif.sync_camera_clock(payload["rtsp_url"])
    if result is None:
        return jsonify({"ok": False, "error": _CAMERA_DOWN})
    return jsonify({"ok": True, **result})
