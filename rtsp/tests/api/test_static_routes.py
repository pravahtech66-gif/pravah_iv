import time

import numpy as np
import pytest

import static_mode
from streaming.config import cv2


def _poll_status(client, job_id, terminal=("done", "error"), timeout_s=5.0):
    deadline = time.time() + timeout_s
    data = None
    while time.time() < deadline:
        resp = client.get(f"/api/status/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        if data["status"] in terminal:
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {terminal}; last={data}")


@pytest.fixture()
def results_root(monkeypatch, tmp_path):
    root = tmp_path / "results"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(static_mode, "RESULTS_ROOT", root)
    return root


@pytest.fixture()
def fake_pipeline(monkeypatch):
    def _fake(cfg, video_abs, job, job_id, job_dir):
        return {
            "mean_speed": 1.23,
            "max_speed": 4.56,
            "median_speed": 2.34,
            "vector_mean_speed": 1.1,
            "vector_median_speed": 1.0,
            "result_image_path": None,
        }

    monkeypatch.setattr(static_mode, "run_pipeline", _fake)
    return _fake


def _make_real_video(path, frames=3, w=32, h=24):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (w, h))
    assert writer.isOpened(), "VideoWriter failed to open"
    for i in range(frames):
        frame = np.full((h, w, 3), fill_value=(i * 40) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_static_mode_index_200(client):
    resp = client.get("/static-mode")
    assert resp.status_code == 200


def test_process_missing_video_and_config_400(client, clean_state, results_root):
    resp = client.post("/api/process", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Missing" in resp.get_json()["error"]


def test_process_malformed_config_json_400(client, clean_state, results_root):
    data = {
        "video": (__import__("io").BytesIO(b"fakebytes"), "clip.mp4"),
        "config": "{not valid json",
    }
    resp = client.post("/api/process", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Malformed config JSON" in resp.get_json()["error"]


def test_process_happy_path_walks_to_done(client, clean_state, results_root, fake_pipeline):
    import io
    data = {
        "video": (io.BytesIO(b"tiny-fake-video-bytes"), "clip.mp4"),
        "config": '{"fps": 25}',
    }
    resp = client.post("/api/process", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    job_id = body["job_id"]
    assert body["status"] == "processing"

    final = _poll_status(client, job_id)
    assert final["status"] == "done"
    assert final["mean_speed"] == 1.23
    assert final["max_speed"] == 4.56
    assert final["median_speed"] == 2.34
    assert final["result_image_url"] is None


def test_process_pipeline_runtime_error_walks_to_error(client, clean_state, results_root, monkeypatch):
    def _boom(cfg, video_abs, job, job_id, job_dir):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(static_mode, "run_pipeline", _boom)

    import io
    data = {
        "video": (io.BytesIO(b"tiny"), "clip.mp4"),
        "config": "{}",
    }
    resp = client.post("/api/process", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]

    final = _poll_status(client, job_id)
    assert final["status"] == "error"
    assert final["error_message"] == "pipeline exploded"


def test_process_sensor_h_a_is_camera_z_minus_distance(client, clean_state, results_root,
                                                        fake_pipeline, monkeypatch):
    import io
    import json

    monkeypatch.setattr(static_mode, "read_sensor_once", lambda cfg: (2.0, "2000"))
    config = {"lens_position": [0.0, -3.0, 1.5], "h_a": 0.0,
              "sensor_enabled": True, "sensor_config": {"port": "COM9"}}
    data = {"video": (io.BytesIO(b"tiny"), "clip.mp4"), "config": json.dumps(config)}

    resp = client.post("/api/process", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]

    saved = json.loads((results_root / job_id / "config.json").read_text())
    assert saved["h_a"] == pytest.approx(1.5 - 2.0)

    final = _poll_status(client, job_id)
    assert final["sensor_fallback"] is False


def test_process_defaults_use_stabilization_off(client, clean_state, results_root, fake_pipeline):
    import io
    import json

    data = {"video": (io.BytesIO(b"tiny"), "clip.mp4"), "config": "{}"}
    resp = client.post("/api/process", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]

    saved = json.loads((results_root / job_id / "config.json").read_text())
    assert saved["use_stabilization"] is False


def test_process_keeps_explicit_use_stabilization(client, clean_state, results_root, fake_pipeline):
    import io
    import json

    data = {"video": (io.BytesIO(b"tiny"), "clip.mp4"), "config": '{"use_stabilization": true}'}
    resp = client.post("/api/process", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]

    saved = json.loads((results_root / job_id / "config.json").read_text())
    assert saved["use_stabilization"] is True


def test_status_unknown_job_404(client, clean_state):
    resp = client.get("/api/status/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Unknown job_id"


def test_cancel_sets_cancelling_and_flag(client, clean_state):
    with static_mode.jobs_lock:
        static_mode.jobs["job1"] = {"status": "processing", "cancel": False,
                                    "progress_log": []}

    resp = client.post("/api/cancel/job1")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "cancelling"
    with static_mode.jobs_lock:
        assert static_mode.jobs["job1"]["cancel"] is True


def test_cancel_unknown_job_404(client, clean_state):
    resp = client.post("/api/cancel/nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Unknown job_id"


def test_first_frame_no_file_400(client):
    resp = client.post("/api/static/first_frame", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'video' file"


def test_first_frame_garbage_bytes_422(client):
    import io
    data = {"video": (io.BytesIO(b"not-a-real-video"), "junk.mp4")}
    resp = client.post("/api/static/first_frame", data=data, content_type="multipart/form-data")
    assert resp.status_code == 422
    assert "Could not read first frame" in resp.get_json()["error"]


def test_first_frame_real_video_returns_png(client, tmp_path):
    import io
    video_path = _make_real_video(tmp_path / "real.avi")
    with open(video_path, "rb") as fh:
        video_bytes = fh.read()

    data = {"video": (io.BytesIO(video_bytes), "real.avi")}
    resp = client.post("/api/static/first_frame", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"
