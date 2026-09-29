import copy
import threading
import time

from streaming.config import _log


_SESSION_DEFAULTS: dict = {
    "status": "idle",
    "rtsp_url": "",
    "batch_duration_s": 60,
    "batch_index_recording": 0,
    "batch_index_processing": None,
    "recording_started_at": None,
    "results": [],
    "log": [],
    "last_velocity_grid": None,
    "sensor_fallback": False,
    "sensor_fallback_reason": None,
    "warn_batch_dropped": False,
    "warn_duration_changed": False,
    "cooldown_until": None,
    "_audit_dir": None,
    "extra_save_status": None,
    "extra_save_path": None,
    "extra_save_batch_idx": None,
    "_drop_current_batch": False,
    "_pending_batch": None,
    "_pending_batch_idx": None,
    "_processor_busy": False,
    "_stop_event": None,
    "_batch_ready_event": None,
    "_session_fps": 25.0,
    "_output_dir": None,
    "_pipeline_config": None,
    "_save_next_batch": False,
}

session: dict = copy.deepcopy(_SESSION_DEFAULTS)
session_lock = threading.Lock()

_snapshot_rec: dict = {
    "status": None,
    "path": None,
    "error": None,
    "clip_index": 0,
    "total_clips": 0,
    "saved_paths": [],
    "folder": None,
    "attempt": None,
}
_snapshot_rec_lock = threading.Lock()


def _reset_session() -> None:
    global session
    new = copy.deepcopy(_SESSION_DEFAULTS)
    session.update(new)


_MAX_LOG_ENTRIES = 200

def _slog(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    _log.info(entry)
    with session_lock:
        log = session["log"]
        log.append(entry)
        if len(log) > _MAX_LOG_ENTRIES:
            del log[: len(log) - _MAX_LOG_ENTRIES]


_MAX_RESULTS_IN_POLL = 50

def _session_snapshot() -> dict:
    with session_lock:
        snap = {k: v for k, v in session.items() if not k.startswith("_")}
        snap["results"] = list(snap["results"][-_MAX_RESULTS_IN_POLL:])
        snap["log"] = list(snap["log"][-_MAX_LOG_ENTRIES:])
        snap["total_batches_processed"] = len(session["results"])
        snap["save_next_queued"]  = session["_save_next_batch"]
        warn_dropped = snap["warn_batch_dropped"]
        warn_changed = snap["warn_duration_changed"]
        session["warn_batch_dropped"] = False
        session["warn_duration_changed"] = False
    snap["warn_batch_dropped"] = warn_dropped
    snap["warn_duration_changed"] = warn_changed
    return snap
