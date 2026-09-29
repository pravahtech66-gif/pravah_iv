import numpy as np
import pytest

from streaming.clip_fitness import assess_clip_fitness
from streaming.config import cv2

WIDTH = 320
HEIGHT = 240
FRAME_COUNT = 40
CENTRE_AOI = [[80, 60], [240, 60], [240, 180], [80, 180]]


def _smooth_noise(rng, height, width):
    noise = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 2)
    return np.clip(128 + 40 * noise / noise.std(), 0, 255).astype(np.uint8)


def _write_clip(path, frames):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 25, (WIDTH, HEIGHT))
    for grey in frames:
        writer.write(cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR))
    writer.release()
    return path


def _moving_frames(seed=0):
    rng = np.random.default_rng(seed)
    base = _smooth_noise(rng, HEIGHT, WIDTH + 3 * FRAME_COUNT)
    frames = []
    for index in range(FRAME_COUNT):
        frame = base[:, 3 * index:3 * index + WIDTH].astype(np.float32)
        fresh = _smooth_noise(rng, HEIGHT, WIDTH).astype(np.float32)
        frames.append((0.8 * frame + 0.2 * fresh).astype(np.uint8))
    return frames


def test_moving_texture_scores_high(tmp_path):
    clip = _write_clip(tmp_path / "moving.avi", _moving_frames())
    verdict = assess_clip_fitness(clip, {"aoi_corners": CENTRE_AOI}, None)
    assert verdict.status == "ok"
    assert verdict.score >= 9.0
    assert verdict.metrics["sample_pairs"] == 12
    assert verdict.metrics["stationary_correlation"] < 0.5
    assert verdict.metrics["camera_shift_px"] is None


def test_static_texture_gets_stationary_penalty(tmp_path):
    still = _smooth_noise(np.random.default_rng(1), HEIGHT, WIDTH)
    clip = _write_clip(tmp_path / "static.avi", [still] * FRAME_COUNT)
    verdict = assess_clip_fitness(clip, {"aoi_corners": CENTRE_AOI}, None)
    assert verdict.metrics["stationary_correlation"] > 0.9
    assert any("barely moves" in reason for reason in verdict.reasons)
    assert verdict.score == 6.0
    assert verdict.status == "low_confidence"


def test_flat_grey_gets_texture_and_flat_penalties(tmp_path):
    grey = np.full((HEIGHT, WIDTH), 128, np.uint8)
    clip = _write_clip(tmp_path / "flat.avi", [grey] * FRAME_COUNT)
    verdict = assess_clip_fitness(clip, {"aoi_corners": CENTRE_AOI}, None)
    assert verdict.status == "low_confidence"
    assert verdict.score == 2.0
    assert verdict.metrics["flat_fraction"] == 1.0
    assert verdict.metrics["stationary_correlation"] is None
    assert any("weak surface texture" in reason for reason in verdict.reasons)
    assert any("featureless" in reason for reason in verdict.reasons)


def test_mostly_white_reports_glare(tmp_path):
    frames = []
    for frame in _moving_frames():
        white = frame.copy()
        white[:, :250] = 255
        frames.append(white)
    clip = _write_clip(tmp_path / "glare.avi", frames)
    verdict = assess_clip_fitness(clip, {}, None)
    assert verdict.metrics["saturated_fraction"] > 0.5
    assert any(reason.startswith("glare:") for reason in verdict.reasons)


def test_reference_equal_to_first_frame_is_not_invalid(tmp_path):
    frames = _moving_frames()
    clip = _write_clip(tmp_path / "moving.avi", frames)
    reference = tmp_path / "ref.png"
    cv2.imwrite(str(reference), frames[0])
    verdict = assess_clip_fitness(clip, {"aoi_corners": CENTRE_AOI}, reference)
    assert verdict.status == "ok"
    assert verdict.metrics["camera_shift_px"] < 1.0


def test_reference_shifted_8px_invalidates(tmp_path):
    frames = _moving_frames()
    clip = _write_clip(tmp_path / "moving.avi", frames)
    reference = tmp_path / "ref.png"
    cv2.imwrite(str(reference), np.roll(frames[0], 8, axis=1))
    verdict = assess_clip_fitness(clip, {"aoi_corners": CENTRE_AOI}, reference)
    assert verdict.status == "invalid"
    assert verdict.metrics["camera_shift_px"] == pytest.approx(8.0, abs=1.0)
    assert any("recalibrate" in reason for reason in verdict.reasons)


def test_reference_of_different_size_does_not_invalidate(tmp_path):
    clip = _write_clip(tmp_path / "moving.avi", _moving_frames())
    reference = tmp_path / "ref.png"
    cv2.imwrite(str(reference), np.zeros((100, 100), np.uint8))
    verdict = assess_clip_fitness(clip, {"aoi_corners": CENTRE_AOI}, reference)
    assert verdict.status == "ok"
    assert verdict.metrics["camera_shift_px"] is None
    assert "reference frame size differs — cannot check camera position" in verdict.reasons


def test_missing_aoi_uses_whole_frame(tmp_path):
    clip = _write_clip(tmp_path / "moving.avi", _moving_frames())
    verdict = assess_clip_fitness(clip, {}, None)
    assert verdict.status == "ok"
    assert verdict.metrics["window_count"] == 15 * 12


def test_unreadable_clip(tmp_path):
    verdict = assess_clip_fitness(tmp_path / "missing.mp4", {"aoi_corners": CENTRE_AOI}, None)
    assert verdict.score == 0.0
    assert verdict.status == "low_confidence"
    assert verdict.reasons == ["clip could not be read"]
    assert verdict.metrics == {}
