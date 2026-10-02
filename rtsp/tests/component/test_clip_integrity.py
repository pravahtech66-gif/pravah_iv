import shutil
import subprocess
import types

import pytest

import streaming.clip_integrity as clip_integrity
from streaming.clip_integrity import check_clip_integrity, count_decode_errors

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg/ffprobe not on PATH")

FPS = 25
SECONDS = 3


def _make_clip(path, video_filter=None):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
           "-i", f"testsrc=size=160x120:rate={FPS}", "-t", str(SECONDS)]
    if video_filter:
        cmd += ["-vf", video_filter, "-fps_mode", "passthrough"]
    cmd += ["-c:v", "libx264", "-bf", "0", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, timeout=60)
    return path


@needs_ffmpeg
def test_clean_clip_passes(tmp_path):
    verdict = check_clip_integrity(_make_clip(tmp_path / "clean.mp4"), SECONDS)
    assert verdict.passed, verdict.reasons
    assert verdict.metrics["frames"] == SECONDS * FPS
    assert verdict.metrics["missing_frames"] == 0
    assert verdict.metrics["decode_errors"] == 0


@needs_ffmpeg
def test_clip_with_timestamp_gap_fails(tmp_path):
    clip = _make_clip(tmp_path / "gap.mp4", video_filter="select='not(between(n,30,44))'")
    verdict = check_clip_integrity(clip, SECONDS, run_decode_check=False)
    assert not verdict.passed
    assert verdict.metrics["missing_frames"] == 15
    assert any("frames missing" in r for r in verdict.reasons)
    assert any("stalled" in r for r in verdict.reasons)


@needs_ffmpeg
def test_too_short_clip_fails(tmp_path):
    verdict = check_clip_integrity(_make_clip(tmp_path / "short.mp4"), SECONDS + 2,
                                   run_decode_check=False)
    assert not verdict.passed
    assert any(r.startswith("too short") for r in verdict.reasons)


@needs_ffmpeg
def test_wrong_reported_fps_fails(tmp_path, monkeypatch):
    clip = _make_clip(tmp_path / "clean.mp4")
    monkeypatch.setattr(clip_integrity, "read_opencv_fps", lambda path: 30.0)
    verdict = check_clip_integrity(clip, SECONDS, run_decode_check=False)
    assert not verdict.passed
    assert any("file reports 30.000 fps" in r for r in verdict.reasons)


def test_decode_errors_ignore_muxer_timestamp_warnings(monkeypatch, tmp_path):
    stderr = "\n".join([
        "[matroska @ 0x1] Application provided invalid, non monotonically increasing dts to muxer",
        "[h264 @ 0x2] error while decoding MB 12 34, bytestream -5",
        "",
    ])
    monkeypatch.setattr(clip_integrity.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stderr=stderr, stdout="", returncode=0))
    assert count_decode_errors(tmp_path / "any.mp4") == 1


def test_measured_fps_is_not_skewed_by_millisecond_timestamp_rounding():
    true_fps = 60.0
    timestamps = [round(i / true_fps, 3) for i in range(1800)]
    metrics = clip_integrity.measure_clip_timing(timestamps)
    assert metrics["measured_fps"] == pytest.approx(true_fps, rel=1e-3)
    assert metrics["missing_frames"] == 0


def test_measured_fps_still_reveals_a_camera_delivering_fewer_frames_than_it_claims():
    delivered_fps = 58.0
    timestamps = [round(i / delivered_fps, 3) for i in range(1740)]
    metrics = clip_integrity.measure_clip_timing(timestamps)
    assert metrics["measured_fps"] == pytest.approx(delivered_fps, rel=1e-3)


def test_measured_fps_counts_missing_frames_as_part_of_the_clock():
    true_fps = 25.0
    kept = [i for i in range(750) if not 300 <= i < 305]
    timestamps = [i / true_fps for i in kept]
    metrics = clip_integrity.measure_clip_timing(timestamps)
    assert metrics["missing_frames"] == 5
    assert metrics["measured_fps"] == pytest.approx(true_fps, rel=1e-6)


@needs_ffmpeg
def test_clean_60fps_matroska_clip_passes(tmp_path):
    clip = tmp_path / "clean60.mkv"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=160x120:rate=60", "-t", str(SECONDS),
                    "-c:v", "libx264", "-bf", "0", "-pix_fmt", "yuv420p", str(clip)],
                   check=True, timeout=60)
    verdict = check_clip_integrity(clip, SECONDS, run_decode_check=False)
    assert verdict.passed, verdict.reasons
