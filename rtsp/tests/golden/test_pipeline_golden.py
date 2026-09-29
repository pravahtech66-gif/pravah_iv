import json
import os
import pathlib

import pytest

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = FIXTURE_DIR / "kunah_config.json"
EXPECTED_PATH = FIXTURE_DIR / "expected.json"
VIDEO_PATH = pathlib.Path(os.environ.get(
    "PRAVAH_GOLDEN_VIDEO",
    str(pathlib.Path.home() / "Desktop" / "Kunah_1.mp4")))

NUMERIC_KEYS = ["mean_speed", "median_speed", "max_speed"]
DISCRETE_KEYS = ["framestep_used", "resolution_used"]


def run_golden(output_dir):
    from piv import run_pipeline
    import cv2
    import numpy as np

    config = json.loads(CONFIG_PATH.read_text())
    cv2.setRNGSeed(0)
    np.random.seed(0)

    job_state = {}
    summary = run_pipeline(config, str(VIDEO_PATH), job_state, "golden",
                           str(output_dir))
    return summary, job_state


@pytest.mark.golden
def test_pipeline_numbers_match_golden(tmp_path):
    if not VIDEO_PATH.exists():
        pytest.skip(f"golden fixture video not found: {VIDEO_PATH} "
                    f"(set PRAVAH_GOLDEN_VIDEO to override)")
    if not EXPECTED_PATH.exists():
        pytest.skip("expected.json missing — run "
                    "`python rtsp/tests/golden/generate_expected.py` "
                    "on known-good code first")

    summary, job_state = run_golden(tmp_path)
    expected = json.loads(EXPECTED_PATH.read_text())

    for key in DISCRETE_KEYS:
        assert summary[key] == pytest.approx(expected[key], rel=1e-9), (
            f"{key}: got {summary[key]!r}, golden {expected[key]!r}")
    for key in NUMERIC_KEYS:
        assert summary[key] == pytest.approx(expected[key], rel=1e-6), (
            f"{key}: got {summary[key]!r}, golden {expected[key]!r}")

    for path_key in ("result_image_path", "camera_overlay_path", "debug_json_path"):
        p = summary.get(path_key)
        assert p and pathlib.Path(p).exists(), f"missing output file: {path_key}"
