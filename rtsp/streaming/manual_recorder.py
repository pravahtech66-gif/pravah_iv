import time

from streaming.config import RECORDINGS_DIR
from streaming.session import session, session_lock, _slog
from streaming.recorder import get_camera_recorder, list_finished_pieces
from streaming.clip_cutter import cut_window_clips
from streaming.clip_manifest import write_clip_manifest

STOP_WAIT_S = 15


def _start_manual_recording(rtsp_url: str) -> str:
    recorder = get_camera_recorder()
    recorder.start_recording(rtsp_url)
    started_at = time.time()
    recorder.hold_pieces_since(started_at)
    filename = time.strftime("recording_%Y%m%d_%H%M%S", time.localtime(started_at)) + ".mp4"

    with session_lock:
        session["is_recording"] = True
        session["rec_file"] = filename
        session["rec_started_at"] = started_at

    _slog(f"Manual recording started → {RECORDINGS_DIR / filename}")
    return filename


def _buffer_reaches(wall_ts: float) -> bool:
    return any(p.wall_start + (p.end_s - p.start_s) > wall_ts for p in list_finished_pieces())


def _stop_manual_recording() -> list:
    stopped_at = time.time()
    with session_lock:
        started_at = session.get("rec_started_at")
        filename = session.get("rec_file", "")
        session["is_recording"] = False

    recorder = get_camera_recorder()
    saved = []
    if started_at is not None:
        deadline = stopped_at + STOP_WAIT_S
        while time.time() < deadline and not _buffer_reaches(stopped_at):
            time.sleep(1)
        saved = cut_window_clips(started_at, stopped_at, RECORDINGS_DIR / filename)
        for path in saved:
            write_clip_manifest(path, source="manual",
                                rtsp_url=recorder.recording_url(),
                                requested_duration_s=round(stopped_at - started_at, 1))
    recorder.hold_pieces_since(None)

    _slog(f"Manual recording stopped → {', '.join(p.name for p in saved) or 'nothing saved'}")
    return saved
