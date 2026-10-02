import shutil
import threading
import time

from streaming.config import STREAM_TMP, BATCH_COOLDOWN_S
from streaming.session import session, session_lock, _slog
from streaming.recorder import get_camera_recorder
from streaming.clip_cutter import wait_for_latest_clip
from streaming.clip_integrity import check_clip_integrity
from streaming.clip_queue import enqueue_clip
from streaming.video_files import _cleanup_file, _trigger_batch_save


def _recorder_thread(rtsp_url: str, stop_event: threading.Event) -> None:
    _slog(f"Recorder starting: {rtsp_url}")
    recorder = get_camera_recorder()
    recorder.start_recording(rtsp_url)

    consecutive_failures = 0
    MAX_FAILURES = 3

    while not stop_event.is_set():
        with session_lock:
            if session["status"] not in ("running", "stopping"):
                break
            duration_s = session["batch_duration_s"]
            batch_idx  = session["batch_index_recording"]

        recorder.reserve_clip_length(duration_s)
        not_before = time.time()

        batch_attempt = 0
        out_path = None

        while True:
            if stop_event.is_set():
                break

            batch_attempt += 1
            attempt_label = f" (attempt {batch_attempt})" if batch_attempt > 1 else ""

            with session_lock:
                session["recording_started_at"] = time.time()

            if batch_attempt == 1:
                with session_lock:
                    if session["_save_next_batch"]:
                        session["_save_next_batch"] = False
                        session["extra_save_status"] = "recording"
                        session["extra_save_batch_idx"] = batch_idx
                        _slog(f"[save] Batch {batch_idx} queued for extra Desktop save")

            out_path = STREAM_TMP / f"batch_{batch_idx}_try{batch_attempt}.mp4"
            _slog(f"Batch {batch_idx}{attempt_label}: recording {duration_s}s")

            clip_ok = wait_for_latest_clip(duration_s, out_path, timeout_s=duration_s + 60,
                                           not_before_wall=not_before,
                                           should_stop=stop_event.is_set)
            if not clip_ok and stop_event.is_set():
                _cleanup_file(out_path)
                break
            verdict = check_clip_integrity(out_path, duration_s, run_decode_check=False) \
                if clip_ok else None

            if verdict is None or not verdict.passed:
                reason = "; ".join(verdict.reasons) if verdict is not None else \
                    (recorder.describe_recorder_status().last_error or "no video from camera")
                _slog(f"Batch {batch_idx}{attempt_label}: REJECTED — {reason}")
                with session_lock:
                    audit_dir = session.get("_audit_dir")
                if audit_dir and out_path.exists() and out_path.stat().st_size > 0:
                    nc_dir = audit_dir / "not_considered"
                    try:
                        nc_dir.mkdir(parents=True, exist_ok=True)
                        nc_dest = nc_dir / f"batch_{batch_idx}_try{batch_attempt}.mp4"
                        if out_path != nc_dest:
                            shutil.move(str(out_path), str(nc_dest))
                        _slog(f"[audit] Rejected batch saved → not_considered/{nc_dest.name}")
                    except Exception:
                        pass
                _cleanup_file(out_path)
                consecutive_failures += 1
                if consecutive_failures >= MAX_FAILURES:
                    _slog(f"Too many failures ({MAX_FAILURES}) — aborting")
                    with session_lock:
                        session["status"] = "error"
                    break
                not_before = time.time()
                continue

            consecutive_failures = 0
            _slog(f"Batch {batch_idx}{attempt_label}: done — "
                  f"{verdict.metrics['frames']} frames")
            break

        with session_lock:
            if session["status"] == "error":
                break
        if stop_event.is_set():
            break
        if out_path is None or not out_path.exists():
            continue

        with session_lock:
            audit_dir = session.get("_audit_dir")
        if audit_dir and audit_dir.exists() and out_path.exists():
            audit_mp4 = audit_dir / f"vid_{batch_idx + 1}.mp4"
            _slog(f"[audit] Saving batch {batch_idx} → {audit_dir.name}/{audit_mp4.name}")
            try:
                shutil.copy2(str(out_path), str(audit_mp4))
                sz_mb = audit_mp4.stat().st_size / (1024 * 1024)
                _slog(f"[audit] Saved {audit_mp4.name} ({sz_mb:.1f} MB)")
            except Exception:
                _slog(f"[audit] ⚠ Failed to save {audit_mp4.name}")

        with session_lock:
            should_save_ex = (session["extra_save_batch_idx"] == batch_idx
                              and session["extra_save_status"] == "recording")
        if should_save_ex:
            _trigger_batch_save(out_path, "extra", batch_idx)

        queued_path = enqueue_clip(out_path, batch_idx)
        _slog(f"Batch {batch_idx} queued for processor → {queued_path.name}")
        with session_lock:
            session["batch_index_recording"] += 1
            batch_ready_event = session["_batch_ready_event"]
        if batch_ready_event is not None:
            batch_ready_event.set()

        with session_lock:
            if session["status"] == "stopping":
                break

        cooldown_end = time.time() + BATCH_COOLDOWN_S
        with session_lock:
            session["cooldown_until"] = cooldown_end
        _slog(f"Batch {batch_idx}: cooldown {BATCH_COOLDOWN_S}s — next recording at "
              f"{time.strftime('%H:%M:%S', time.localtime(cooldown_end))}")

        while time.time() < cooldown_end:
            if stop_event.is_set():
                break
            time.sleep(1.0)

        with session_lock:
            session["cooldown_until"] = None

    with session_lock:
        if session["status"] not in ("error",):
            session["status"] = "stopped"
    _slog("Recorder thread exiting")
