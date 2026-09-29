import dataclasses
import datetime
import functools
import json
import pathlib
import subprocess
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from streaming.config import _log, BASE_DIR
from streaming.camera_onvif import read_camera_stream_settings

PROBE_TIMEOUT_S = 60


def mask_url_password(url: str) -> str:
    parts = urlsplit(url)
    userinfo, sep, hostport = parts.netloc.rpartition("@")
    if not sep or ":" not in userinfo:
        return url
    username = userinfo.split(":", 1)[0]
    return urlunsplit(parts._replace(netloc=f"{username}:***@{hostport}"))


def read_video_stream_info(path: pathlib.Path) -> Optional[dict]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries",
             "stream=codec_name,width,height,avg_frame_rate,nb_read_packets:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S).stdout
        info = json.loads(out)
        stream = info["streams"][0]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError):
        return None
    duration = info.get("format", {}).get("duration")
    frames = stream.get("nb_read_packets")
    return {
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "frames": int(frames) if frames is not None else None,
        "duration": float(duration) if duration is not None else None,
    }


@functools.lru_cache(maxsize=1)
def read_software_version() -> Optional[str]:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(BASE_DIR),
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def read_camera_settings_or_none(rtsp_url: str) -> Optional[dict]:
    try:
        return read_camera_stream_settings(rtsp_url)
    except Exception as e:
        _log.info(f"[manifest] camera settings unavailable: {type(e).__name__} {e}")
        return None


def write_clip_manifest(clip_path: pathlib.Path, *, source: str, rtsp_url: str,
                        requested_duration_s: float, integrity=None, fitness=None,
                        water_level_m=None) -> pathlib.Path:
    manifest = {
        "source": source,
        "rtsp_url": mask_url_password(rtsp_url),
        "requested_duration_s": requested_duration_s,
        "saved_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "stream": read_video_stream_info(clip_path),
        "camera_settings": read_camera_settings_or_none(rtsp_url),
        "integrity": dataclasses.asdict(integrity) if integrity is not None else None,
        "fitness": dataclasses.asdict(fitness) if fitness is not None else None,
        "water_level_m": water_level_m,
        "software_version": read_software_version(),
    }
    manifest_path = clip_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest_path
