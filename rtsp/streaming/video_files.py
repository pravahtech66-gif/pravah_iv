import pathlib
import shutil
import threading
import time

from streaming.config import _log, STREAM_TMP, DESKTOP
from streaming.session import session, session_lock, _slog


def _cleanup_file(path: pathlib.Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _save_batch_as_mp4(copy_path: pathlib.Path, save_key: str, batch_idx: int) -> None:
    ts = time.strftime("%Y%m%d_%H%M%S")
    mp4_name = f"pravah_batch{batch_idx}_{ts}.mp4"
    mp4_path = DESKTOP / mp4_name
    status_key = f"{save_key}_save_status"
    path_key = f"{save_key}_save_path"

    with session_lock:
        session[status_key] = "saving"
    _slog(f"[save] Saving batch {batch_idx} → Desktop/{mp4_name}")

    try:
        shutil.move(str(copy_path), str(mp4_path))
        ok = True
    except OSError as e:
        _log.warning(f"[save] move failed: {e}")
        ok = False
    _cleanup_file(copy_path)

    with session_lock:
        if ok:
            session[status_key] = "saved"
            session[path_key] = str(mp4_path)
            _slog(f"[save] Batch {batch_idx} saved → Desktop/{mp4_name}")
        else:
            session[status_key] = "failed"
            _slog(f"[save] Batch {batch_idx} save FAILED")


def _trigger_batch_save(out_path: pathlib.Path, save_key: str, batch_idx: int) -> None:
    copy_path = STREAM_TMP / f"save_{out_path.name}"
    try:
        shutil.copy2(str(out_path), str(copy_path))
    except Exception as e:
        _slog(f"[save] Could not copy batch {batch_idx} for saving: {e}")
        with session_lock:
            session[f"{save_key}_save_status"] = "failed"
        return
    t = threading.Thread(target=_save_batch_as_mp4, args=(copy_path, save_key, batch_idx), daemon=True)
    t.start()
