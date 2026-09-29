import shutil
import time

from streaming.config import DESKTOP, STREAM_TMP, SNAPSHOT_CLIP_COUNT, _check_desktop_writable, _log
from streaming.session import _snapshot_rec, _snapshot_rec_lock
from streaming.recorder import get_camera_recorder
from streaming.clip_cutter import wait_for_latest_clip
from streaming.clip_integrity import check_clip_integrity
from streaming.clip_manifest import write_clip_manifest
from streaming.video_files import _cleanup_file

MAX_SNAPSHOT_ATTEMPTS = 5


def _run_snapshot_recording(rtsp_url: str, duration_s: int = 60) -> None:
    global _snapshot_rec

    ok, err = _check_desktop_writable()
    if not ok:
        _log.warning(f"[snapshot] Desktop not writable — aborting: {err}")
        with _snapshot_rec_lock:
            _snapshot_rec.update({"status": "failed", "error": err,
                                  "clip_index": 0, "total_clips": SNAPSHOT_CLIP_COUNT})
        return

    date_folder = time.strftime("%Y-%m-%d")
    time_folder = time.strftime("%H-%M")
    folder_name = f"{date_folder}/{time_folder}"
    batch_dir = DESKTOP / date_folder / time_folder
    reject_dir = batch_dir / "not_considered"
    try:
        batch_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        err = f"cannot create folder {batch_dir}: {e}"
        _log.warning(f"[snapshot] {err}")
        with _snapshot_rec_lock:
            _snapshot_rec.update({"status": "failed", "error": err,
                                  "clip_index": 0, "total_clips": SNAPSHOT_CLIP_COUNT})
        return

    _log.info(f"[snapshot] Batch folder: Desktop/{folder_name}/")

    recorder = get_camera_recorder()
    recorder.start_recording(rtsp_url)
    recorder.reserve_clip_length(duration_s)
    not_before = time.time()

    saved_paths: list[str] = []
    last_error = None

    for clip_no in range(1, SNAPSHOT_CLIP_COUNT + 1):
        mp4_dest = batch_dir / f"vid_{clip_no}.mp4"

        for attempt in range(1, MAX_SNAPSHOT_ATTEMPTS + 1):
            with _snapshot_rec_lock:
                _snapshot_rec.update({
                    "status": "recording", "clip_index": clip_no,
                    "total_clips": SNAPSHOT_CLIP_COUNT,
                    "saved_paths": list(saved_paths), "error": None,
                    "folder": folder_name, "attempt": attempt,
                })

            tmp_path = STREAM_TMP / f"snapshot_{clip_no}_try{attempt}.mp4"
            if not wait_for_latest_clip(duration_s, tmp_path, timeout_s=duration_s + 60,
                                        not_before_wall=not_before):
                _cleanup_file(tmp_path)
                reject_reason = (recorder.describe_recorder_status().last_error
                                 or "no video from camera")
                verdict = None
            else:
                verdict = check_clip_integrity(tmp_path, duration_s)
                if verdict.passed:
                    shutil.move(str(tmp_path), str(mp4_dest))
                    write_clip_manifest(mp4_dest, source="record_button", rtsp_url=rtsp_url,
                                        requested_duration_s=duration_s, integrity=verdict)
                    saved_paths.append(str(mp4_dest))
                    with _snapshot_rec_lock:
                        _snapshot_rec.update({"status": "saving", "path": str(mp4_dest),
                                              "saved_paths": list(saved_paths),
                                              "attempt": attempt})
                    _log.info(f"[snapshot] Clip {clip_no} accepted (attempt {attempt})")
                    break
                reject_reason = "; ".join(verdict.reasons)

            _log.warning(f"[snapshot] Clip {clip_no} attempt {attempt} REJECTED "
                         f"({reject_reason})")
            if verdict is not None:
                try:
                    reject_dir.mkdir(parents=True, exist_ok=True)
                    reject_path = reject_dir / f"vid_{clip_no}_try{attempt}.mp4"
                    shutil.move(str(tmp_path), str(reject_path))
                    write_clip_manifest(reject_path, source="record_button", rtsp_url=rtsp_url,
                                        requested_duration_s=duration_s, integrity=verdict)
                    _log.info(f"[snapshot] Moved rejected clip → "
                              f"not_considered/{reject_path.name}")
                except Exception as e:
                    _log.warning(f"[snapshot] Could not move rejected clip: {e}")
                    _cleanup_file(tmp_path)

            last_error = reject_reason
            with _snapshot_rec_lock:
                _snapshot_rec.update({
                    "status": "rejected",
                    "error": f"Clip {clip_no} attempt {attempt}: {reject_reason}",
                    "attempt": attempt,
                })
            not_before = time.time()
        else:
            break

    with _snapshot_rec_lock:
        if len(saved_paths) == SNAPSHOT_CLIP_COUNT:
            _snapshot_rec.update({"status": "saved",
                                  "path": saved_paths[-1],
                                  "saved_paths": list(saved_paths),
                                  "clip_index": len(saved_paths),
                                  "total_clips": SNAPSHOT_CLIP_COUNT,
                                  "error": None,
                                  "folder": folder_name,
                                  "attempt": None})
            _log.info(f"[snapshot] Run complete — {len(saved_paths)}/{SNAPSHOT_CLIP_COUNT} "
                      f"clips saved to Desktop/{folder_name}/")
        else:
            _snapshot_rec.update({"status": "failed",
                                  "error": last_error or "no clips captured",
                                  "saved_paths": [], "total_clips": SNAPSHOT_CLIP_COUNT})
            _log.warning(f"[snapshot] Run failed after {MAX_SNAPSHOT_ATTEMPTS} attempts "
                         f"({last_error})")
