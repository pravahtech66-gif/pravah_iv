import pathlib
import statistics
import subprocess

from streaming.config import cv2
from streaming.models.integrity_verdict import IntegrityVerdict

MAX_MISSING_FRACTION = 0.005
MAX_GAP_S = 0.5
MAX_FPS_ERROR_FRACTION = 0.005
PROBE_TIMEOUT_S = 120
DECODE_TIMEOUT_S = 600
MUXER_WARNING = "non monotonically increasing dts"


def read_frame_timestamps(path: pathlib.Path) -> list:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=PROBE_TIMEOUT_S).stdout
    return sorted(float(line.split(",")[0]) for line in out.split()
                  if line and line.split(",")[0] not in ("", "N/A"))


def count_decode_errors(path: pathlib.Path) -> int:
    err = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                          "-f", "null", "-"],
                         capture_output=True, text=True, timeout=DECODE_TIMEOUT_S).stderr
    return sum(1 for line in err.splitlines() if line.strip() and MUXER_WARNING not in line)


def read_opencv_fps(path: pathlib.Path) -> float:
    cap = cv2.VideoCapture(str(path))
    try:
        return float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        cap.release()


def measure_clip_timing(timestamps: list) -> dict:
    intervals = [b - a for a, b in zip(timestamps, timestamps[1:])]
    frame_interval = statistics.median(intervals)
    missing = sum(round(d / frame_interval) - 1 for d in intervals if d > 1.5 * frame_interval)
    return {
        "frames": len(timestamps),
        "frame_interval_s": frame_interval,
        "measured_fps": (len(intervals) + missing) / (timestamps[-1] - timestamps[0]),
        "duration_s": timestamps[-1] - timestamps[0] + frame_interval,
        "missing_frames": missing,
        "missing_fraction": missing / (len(timestamps) + missing),
        "max_gap_s": max(intervals),
    }


def check_clip_integrity(path: pathlib.Path, requested_duration_s: float,
                         run_decode_check: bool = True) -> IntegrityVerdict:
    timestamps = read_frame_timestamps(path)
    if len(timestamps) < 2:
        return IntegrityVerdict(passed=False, reasons=["clip has no readable frames"])

    metrics = measure_clip_timing(timestamps)
    metrics["opencv_fps"] = read_opencv_fps(path)
    reasons = []

    if metrics["duration_s"] < requested_duration_s - metrics["frame_interval_s"]:
        reasons.append(f"too short: {metrics['duration_s']:.1f} s of {requested_duration_s} s")
    if metrics["missing_fraction"] > MAX_MISSING_FRACTION:
        reasons.append(f"{metrics['missing_fraction'] * 100:.1f} % frames missing "
                       f"({metrics['missing_frames']})")
    if metrics["max_gap_s"] > MAX_GAP_S:
        reasons.append(f"stream stalled for {metrics['max_gap_s']:.2f} s")
    fps_error = abs(metrics["opencv_fps"] - metrics["measured_fps"]) / metrics["measured_fps"]
    if fps_error > MAX_FPS_ERROR_FRACTION:
        reasons.append(f"file reports {metrics['opencv_fps']:.3f} fps but frames arrive at "
                       f"{metrics['measured_fps']:.3f} fps")
    if run_decode_check:
        metrics["decode_errors"] = count_decode_errors(path)
        if metrics["decode_errors"]:
            reasons.append(f"{metrics['decode_errors']} corrupted-picture errors")

    return IntegrityVerdict(passed=not reasons, reasons=reasons, metrics=metrics)
