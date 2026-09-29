import json
import pathlib

import pytest

import static_mode
from static_mode import _worker_run_job


def _seed_job(job_id: str, job_dir: pathlib.Path) -> None:
    log_list = [f"Job {job_id} created.", f"Video saved to {job_dir}/input_video.mp4"]
    with static_mode.jobs_lock:
        static_mode.jobs[job_id] = {
            "status": "queued",
            "log": log_list,
            "progress_log": log_list,
            "error_message": None,
            "mean_speed": None,
            "max_speed": None,
            "median_speed": None,
            "vector_mean_speed": None,
            "vector_median_speed": None,
            "result_image_url": None,
            "cancel": False,
            "video_path": str(job_dir / "input_video.mp4"),
            "job_dir": str(job_dir),
            "cleanup_scheduled": False,
            "sensor_fallback": False,
            "sensor_fallback_reason": None,
        }


def _write_config(job_dir: pathlib.Path, cfg: dict | None = None) -> pathlib.Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg if cfg is not None else {"video_file": "input_video.mp4"}
    config_path = job_dir / "config.json"
    config_path.write_text(json.dumps(cfg))
    return config_path


class TestWorkerRunJobSuccess:
    def test_status_done_and_speeds_copied_from_summary(self, tmp_path, clean_state, monkeypatch):
        job_id = "job1"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        def fake_runner(cfg, video_path, job, jid, jdir):
            return {"mean_speed": 1.1, "max_speed": 2.2, "median_speed": 1.5}

        monkeypatch.setattr(static_mode, "run_pipeline", fake_runner)
        _worker_run_job(job_id, config_path, job_dir)

        job = static_mode.jobs[job_id]
        assert job["status"] == "done"
        assert job["mean_speed"] == 1.1
        assert job["max_speed"] == 2.2
        assert job["median_speed"] == 1.5

    def test_result_image_url_built_when_path_exists(self, tmp_path, clean_state, monkeypatch):
        job_id = "job2"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        result_image = job_dir / "result.png"
        result_image.write_bytes(b"fake-png-bytes")

        def fake_runner(cfg, video_path, job, jid, jdir):
            return {
                "mean_speed": 0.5, "max_speed": 0.9, "median_speed": 0.6,
                "result_image_path": str(result_image),
            }

        monkeypatch.setattr(static_mode, "run_pipeline", fake_runner)
        _worker_run_job(job_id, config_path, job_dir)

        job = static_mode.jobs[job_id]
        assert job["status"] == "done"
        assert job["result_image_url"] == f"/static/results/{job_id}/result.png"

    def test_result_image_url_stays_none_when_path_missing(self, tmp_path, clean_state, monkeypatch):
        job_id = "job3"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        def fake_runner(cfg, video_path, job, jid, jdir):
            return {
                "mean_speed": 0.5, "max_speed": 0.9, "median_speed": 0.6,
                "result_image_path": str(job_dir / "does_not_exist.png"),
            }

        monkeypatch.setattr(static_mode, "run_pipeline", fake_runner)
        _worker_run_job(job_id, config_path, job_dir)

        job = static_mode.jobs[job_id]
        assert job["status"] == "done"
        assert job["result_image_url"] is None

    def test_result_image_url_none_when_summary_omits_it(self, tmp_path, clean_state, monkeypatch):
        job_id = "job4"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        def fake_runner(cfg, video_path, job, jid, jdir):
            return {"mean_speed": 0.1, "max_speed": 0.2, "median_speed": 0.15}

        monkeypatch.setattr(static_mode, "run_pipeline", fake_runner)
        _worker_run_job(job_id, config_path, job_dir)

        job = static_mode.jobs[job_id]
        assert job["result_image_url"] is None

    def test_status_set_to_processing_before_completion_fields(self, tmp_path, clean_state, monkeypatch):
        job_id = "job5"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        seen_status = {}

        def fake_runner(cfg, video_path, job, jid, jdir):
            seen_status["status"] = static_mode.jobs[job_id]["status"]
            return {"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0}

        monkeypatch.setattr(static_mode, "run_pipeline", fake_runner)
        _worker_run_job(job_id, config_path, job_dir)

        assert seen_status["status"] == "processing"
        assert static_mode.jobs[job_id]["status"] == "done"


class TestWorkerRunJobErrors:
    def test_runtime_error_sets_status_error_with_message(self, tmp_path, clean_state, monkeypatch):
        job_id = "job_err"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        def failing_runner(cfg, video_path, job, jid, jdir):
            raise RuntimeError("boom: sensor unavailable")

        monkeypatch.setattr(static_mode, "run_pipeline", failing_runner)
        _worker_run_job(job_id, config_path, job_dir)

        job = static_mode.jobs[job_id]
        assert job["status"] == "error"
        assert job["error_message"] == "boom: sensor unavailable"

    def test_generic_exception_sets_status_error_with_wrapped_message(self, tmp_path, clean_state, monkeypatch):
        job_id = "job_err2"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)
        _seed_job(job_id, job_dir)

        def failing_runner(cfg, video_path, job, jid, jdir):
            raise ValueError("bad config")

        monkeypatch.setattr(static_mode, "run_pipeline", failing_runner)
        _worker_run_job(job_id, config_path, job_dir)

        job = static_mode.jobs[job_id]
        assert job["status"] == "error"
        assert "Unexpected error in worker" in job["error_message"]
        assert "bad config" in job["error_message"]


class TestWorkerRunJobUnknownJob:
    def test_unknown_job_id_returns_without_raising(self, tmp_path, clean_state, monkeypatch):
        job_id = "does-not-exist"
        job_dir = tmp_path / job_id
        config_path = _write_config(job_dir)

        def fake_runner(cfg, video_path, job, jid, jdir):
            return {"mean_speed": 1.0, "max_speed": 1.0, "median_speed": 1.0}

        monkeypatch.setattr(static_mode, "run_pipeline", fake_runner)
        _worker_run_job(job_id, config_path, job_dir)

        assert job_id not in static_mode.jobs
