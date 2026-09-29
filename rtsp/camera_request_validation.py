import urllib.parse
from typing import Optional


def validate_camera_rtsp_url(rtsp_url) -> Optional[str]:
    if not isinstance(rtsp_url, str) or not rtsp_url.strip():
        return "rtsp_url is required"
    try:
        parts = urllib.parse.urlsplit(rtsp_url)
        host = parts.hostname
    except ValueError:
        return "rtsp_url is not a valid URL"
    if parts.scheme != "rtsp" or not host:
        return "rtsp_url must look like rtsp://user:password@host/path"
    if not parts.username or not parts.password:
        return "rtsp_url must include the camera username and password"
    return None


def validate_camera_write_request(payload) -> Optional[str]:
    if not isinstance(payload, dict):
        return "JSON body required"
    if payload.get("confirm") is not True:
        return "confirm must be true"
    return validate_camera_rtsp_url(payload.get("rtsp_url"))
