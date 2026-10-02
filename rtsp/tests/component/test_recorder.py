import subprocess
import sys
import time

import pytest

import streaming.recorder as recorder
from streaming.recorder import CameraRecorder


@pytest.fixture()
def buffer_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(recorder, "BUFFER_DIR", tmp_path)
    monkeypatch.setattr(recorder, "PREVIEW_PATH", tmp_path / "preview.jpg")
    return tmp_path


def _make_pieces(buffer_dir, ages_s, run_id="1700000000"):
    now = time.time()
    for age in ages_s:
        stamp = time.strftime(recorder.PIECE_NAME_FORMAT, time.localtime(now - age))
        (buffer_dir / f"{stamp}_{run_id}.mkv").write_bytes(b"")


def _remaining_ages(buffer_dir):
    now = time.time()
    return sorted(round(now - recorder.parse_piece_wall_start(p))
                  for p in buffer_dir.glob("*.mkv"))


def test_prune_deletes_pieces_older_than_retention(buffer_dir):
    _make_pieces(buffer_dir, range(5, 905, 10))
    CameraRecorder()._prune_buffer()
    ages = _remaining_ages(buffer_dir)
    assert max(ages) <= recorder.MIN_RETENTION_S + 1
    assert len(ages) == 60


def test_reserve_clip_length_extends_retention(buffer_dir):
    _make_pieces(buffer_dir, range(5, 905, 10))
    rec = CameraRecorder()
    rec.reserve_clip_length(400)
    rec._prune_buffer()
    assert max(_remaining_ages(buffer_dir)) in range(794, 802)


def test_prune_hard_cap_limits_file_count(buffer_dir):
    _make_pieces(buffer_dir, range(0, 100))
    CameraRecorder()._prune_buffer()
    max_files = recorder.MIN_RETENTION_S // recorder.PIECE_SECONDS + 6
    ages = _remaining_ages(buffer_dir)
    assert len(ages) == max_files
    assert max(ages) <= max_files + 1


def test_hold_keeps_pieces_since_hold_time(buffer_dir):
    _make_pieces(buffer_dir, range(5, 905, 10))
    rec = CameraRecorder()
    rec.hold_pieces_since(time.time() - 800)
    rec._prune_buffer()
    ages = _remaining_ages(buffer_dir)
    assert max(ages) in range(804, 812)
    assert len(ages) > recorder.MIN_RETENTION_S // recorder.PIECE_SECONDS + 6


def test_prune_never_deletes_newest_piece(buffer_dir):
    _make_pieces(buffer_dir, [5000])
    CameraRecorder()._prune_buffer()
    assert len(list(buffer_dir.glob("*.mkv"))) == 1


def test_prune_removes_segment_list_of_a_run_with_no_pieces_left(buffer_dir):
    _make_pieces(buffer_dir, [5], run_id="222")
    (buffer_dir / "run_111.csv").write_text("")
    (buffer_dir / "run_222.csv").write_text("")
    CameraRecorder()._prune_buffer()
    assert not (buffer_dir / "run_111.csv").exists()
    assert (buffer_dir / "run_222.csv").exists()


def test_watchdog_restarts_a_stalled_recorder_and_stop_ends_it(buffer_dir, monkeypatch):
    silent_command = [sys.executable, "-c", "import sys; sys.stdin.read(1)"]
    monkeypatch.setattr(recorder, "build_recorder_command", lambda url, run_id: silent_command)
    monkeypatch.setattr(recorder, "STALL_TIMEOUT_S", 0.5)
    monkeypatch.setattr(recorder, "RESTART_DELAY_S", 0)
    monkeypatch.setattr(recorder, "POLL_INTERVAL_S", 0.1)
    started = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        started.append(real_popen(*args, **kwargs))
        return started[-1]

    monkeypatch.setattr(recorder.subprocess, "Popen", recording_popen)

    rec = CameraRecorder()
    rec.start_recording("rtsp://fake")
    try:
        deadline = time.time() + 15
        while rec.describe_recorder_status().restarts < 2 and time.time() < deadline:
            time.sleep(0.1)
        status = rec.describe_recorder_status()
        assert status.restarts >= 2
        assert "stalled" in status.last_error
        assert status.running
    finally:
        rec.stop_recording()

    assert not rec.describe_recorder_status().running
    assert started and all(proc.poll() is not None for proc in started)


def _sleeping_process(*extra_args):
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *extra_args])


def test_orphaned_recorder_writing_into_our_buffer_is_stopped(buffer_dir):
    orphan = _sleeping_process(str(buffer_dir / "piece.mkv"))
    (buffer_dir / recorder.PID_FILE_NAME).write_text(str(orphan.pid))
    try:
        recorder.stop_orphaned_recorder()
        assert orphan.wait(timeout=5) is not None
        assert not (buffer_dir / recorder.PID_FILE_NAME).exists()
    finally:
        orphan.kill()


def test_process_not_writing_into_our_buffer_is_left_alone(buffer_dir):
    unrelated = _sleeping_process()
    (buffer_dir / recorder.PID_FILE_NAME).write_text(str(unrelated.pid))
    try:
        recorder.stop_orphaned_recorder()
        assert unrelated.poll() is None
    finally:
        unrelated.kill()


def test_start_recording_stops_orphan_left_by_a_crashed_app(buffer_dir, monkeypatch):
    orphan = _sleeping_process(str(buffer_dir / "piece.mkv"))
    (buffer_dir / recorder.PID_FILE_NAME).write_text(str(orphan.pid))
    monkeypatch.setattr(recorder, "build_recorder_command",
                        lambda url, run_id: [sys.executable, "-c", "import sys; sys.stdin.read(1)"])
    rec = CameraRecorder()
    try:
        rec.start_recording("rtsp://fake")
        assert orphan.wait(timeout=5) is not None
    finally:
        rec.stop_recording()
        orphan.kill()
