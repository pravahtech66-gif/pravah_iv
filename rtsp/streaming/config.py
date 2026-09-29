import logging
import os
import pathlib
import subprocess

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"
    "|timeout;5000000"
    "|stimeout;5000000"
    "|listen_timeout;5000000"
    "|max_delay;60000000"
)

import cv2

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
RESULTS_ROOT = BASE_DIR / "static" / "results"
STREAM_TMP = RESULTS_ROOT / "stream_tmp"
RECORDINGS_DIR = BASE_DIR / "recordings"
BUFFER_DIR = RECORDINGS_DIR / "buffer"
PREVIEW_PATH = BUFFER_DIR / "preview.jpg"
QUEUE_DIR = RECORDINGS_DIR / "queue"
GCP_REFERENCE_PATH = RECORDINGS_DIR / "gcp_reference.jpg"
SENSOR_CONFIG_PATH = BASE_DIR / "sensor_config.json"
DESKTOP = pathlib.Path.home() / "Desktop"
BATCH_COOLDOWN_S = 300

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("app_stream")

def _patch_ffmpeg_path() -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    _roots = [
        pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        pathlib.Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
    ]
    for root in _roots:
        if not root.exists():
            continue
        for exe in root.rglob("ffmpeg.exe"):
            os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
            logging.getLogger("app_stream").info(f"ffmpeg found at {exe} — added to PATH")
            return

_patch_ffmpeg_path()


def ensure_dirs() -> None:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    STREAM_TMP.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_desktop_writable() -> tuple[bool, str]:
    try:
        DESKTOP.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"cannot create Desktop folder: {e}"
    if not os.access(str(DESKTOP), os.W_OK):
        return False, f"no write permission for {DESKTOP}"
    probe = DESKTOP / f".pravah_write_test_{os.getpid()}.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as e:
        return False, f"write test failed: {e}"
    return True, ""


SNAPSHOT_CLIP_COUNT = 1
