import csv
import pathlib
import subprocess
import threading
import time
from typing import Optional

import psutil

from streaming.config import _log, BUFFER_DIR, PREVIEW_PATH
from streaming.models.piece import Piece
from streaming.models.recorder_status import RecorderStatus

PIECE_SECONDS = 10
MIN_RETENTION_S = 600
STALL_TIMEOUT_S = 15
RESTART_DELAY_S = 2
POLL_INTERVAL_S = 1
PIECE_NAME_FORMAT = "%Y-%m-%d_%H-%M-%S"
PID_FILE_NAME = "recorder.pid"


def build_recorder_command(rtsp_url: str, run_id: str) -> list:
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-timeout", "10000000",
        "-skip_frame", "nokey",
        "-i", rtsp_url,
        "-map", "0:v:0", "-c:v", "copy",
        "-f", "segment", "-segment_time", str(PIECE_SECONDS),
        "-segment_format", "matroska", "-reset_timestamps", "1",
        "-segment_list", str(BUFFER_DIR / f"run_{run_id}.csv"),
        "-segment_list_type", "csv", "-strftime", "1",
        str(BUFFER_DIR / f"{PIECE_NAME_FORMAT}_{run_id}.mkv"),
        "-map", "0:v:0", "-fps_mode", "passthrough", "-q:v", "3",
        "-update", "1", "-atomic_writing", "1", "-f", "image2",
        str(PREVIEW_PATH),
    ]


def stop_orphaned_recorder() -> None:
    pid_file = BUFFER_DIR / PID_FILE_NAME
    try:
        pid = int(pid_file.read_text())
        proc = psutil.Process(pid)
        if str(BUFFER_DIR) in " ".join(proc.cmdline()):
            proc.kill()
            proc.wait(timeout=5)
            _log.warning(f"[recorder] stopped orphaned ffmpeg (pid {pid}) from an earlier run")
    except (OSError, ValueError, psutil.Error):
        pass
    pid_file.unlink(missing_ok=True)


def parse_piece_wall_start(path: pathlib.Path) -> float:
    stamp = path.stem.rsplit("_", 1)[0]
    return time.mktime(time.strptime(stamp, PIECE_NAME_FORMAT))


def read_run_pieces(list_path: pathlib.Path) -> list:
    run_id = list_path.stem[len("run_"):]
    pieces = []
    with open(list_path, newline="") as f:
        for row in list(csv.reader(f))[1:]:
            if len(row) < 3:
                continue
            path = BUFFER_DIR / row[0]
            if not path.exists():
                continue
            pieces.append(Piece(path=path, run_id=run_id, start_s=float(row[1]),
                                end_s=float(row[2]),
                                wall_start=parse_piece_wall_start(path)))
    return pieces


def list_finished_pieces() -> list:
    pieces = []
    for list_path in BUFFER_DIR.glob("run_*.csv"):
        pieces.extend(read_run_pieces(list_path))
    return sorted(pieces, key=lambda p: (p.wall_start, p.run_id, p.start_s))


class CameraRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._rtsp_url = ""
        self._running = False
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._restarts = 0
        self._last_error: Optional[str] = None
        self._retention_floor_s = MIN_RETENTION_S
        self._hold_since: Optional[float] = None

    def start_recording(self, rtsp_url: str) -> None:
        with self._lock:
            if self._running and self._rtsp_url == rtsp_url:
                return
        self.stop_recording()
        BUFFER_DIR.mkdir(parents=True, exist_ok=True)
        stop_orphaned_recorder()
        with self._lock:
            self._rtsp_url = rtsp_url
            self._running = True
            self._restarts = 0
            self._last_error = None
            self._thread = threading.Thread(target=self._supervise_recording, daemon=True)
            self._thread.start()
        _log.info(f"[recorder] started for {rtsp_url}")

    def stop_recording(self) -> None:
        with self._lock:
            was_running = self._running
            self._running = False
            thread = self._thread
        self._terminate_ffmpeg()
        if thread is not None:
            thread.join(timeout=10)
        if was_running:
            _log.info("[recorder] stopped")

    def reserve_clip_length(self, clip_s: float) -> None:
        with self._lock:
            self._retention_floor_s = max(MIN_RETENTION_S, 2 * clip_s)

    def hold_pieces_since(self, wall_ts: Optional[float]) -> None:
        with self._lock:
            self._hold_since = wall_ts

    def describe_recorder_status(self) -> RecorderStatus:
        now = time.time()
        pieces = list_finished_pieces()
        with self._lock:
            running, url = self._running, self._rtsp_url
            restarts, last_error = self._restarts, self._last_error
        newest_file = self._newest_piece_file()
        return RecorderStatus(
            running=running,
            rtsp_url=url,
            buffered_s=round(sum(p.end_s - p.start_s for p in pieces), 1),
            newest_piece_age_s=round(now - newest_file.stat().st_mtime, 1) if newest_file else None,
            preview_age_s=round(now - PREVIEW_PATH.stat().st_mtime, 1) if PREVIEW_PATH.exists() else None,
            restarts=restarts,
            last_error=last_error,
        )

    def recording_url(self) -> str:
        with self._lock:
            return self._rtsp_url if self._running else ""

    def _supervise_recording(self) -> None:
        while self._is_running():
            run_id = str(int(time.time()))
            log_path = BUFFER_DIR / "ffmpeg.log"
            with open(log_path, "ab") as log_file:
                proc = subprocess.Popen(build_recorder_command(self._rtsp_url, run_id),
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=log_file)
            (BUFFER_DIR / PID_FILE_NAME).write_text(str(proc.pid))
            with self._lock:
                self._proc = proc
            self._watch_ffmpeg(proc)
            self._terminate_ffmpeg()
            if not self._is_running():
                break
            with self._lock:
                self._restarts += 1
            _log.warning(f"[recorder] ffmpeg ended ({self._last_error}) — restart "
                         f"#{self._restarts} in {RESTART_DELAY_S}s")
            time.sleep(RESTART_DELAY_S)

    def _watch_ffmpeg(self, proc: subprocess.Popen) -> None:
        last_progress = time.time()
        last_signature = None
        while self._is_running():
            if proc.poll() is not None:
                self._set_last_error(f"ffmpeg exited with code {proc.returncode}")
                return
            signature = self._progress_signature()
            if signature != last_signature:
                last_signature = signature
                last_progress = time.time()
            elif time.time() - last_progress > STALL_TIMEOUT_S:
                self._set_last_error(f"no new video for {STALL_TIMEOUT_S}s — stream stalled")
                return
            self._prune_buffer()
            time.sleep(POLL_INTERVAL_S)

    def _progress_signature(self):
        newest = self._newest_piece_file()
        piece_sig = (newest.name, newest.stat().st_size) if newest else None
        preview_sig = PREVIEW_PATH.stat().st_mtime if PREVIEW_PATH.exists() else None
        return piece_sig, preview_sig

    def _terminate_ffmpeg(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        (BUFFER_DIR / PID_FILE_NAME).unlink(missing_ok=True)
        if proc.poll() is not None:
            return
        try:
            proc.stdin.write(b"q")
            proc.stdin.flush()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait(timeout=5)

    def _prune_buffer(self) -> None:
        with self._lock:
            retention_s = self._retention_floor_s
            hold_since = self._hold_since
        cutoff = time.time() - retention_s
        if hold_since is not None:
            cutoff = min(cutoff, hold_since - PIECE_SECONDS)
        files = sorted(BUFFER_DIR.glob("*.mkv"), key=parse_piece_wall_start)
        max_files = int(retention_s // PIECE_SECONDS) + 6
        excess = max(0, len(files) - max_files) if hold_since is None else 0
        for index, path in enumerate(files[:-1]):
            if index < excess or parse_piece_wall_start(path) < cutoff:
                try:
                    path.unlink()
                except OSError:
                    pass
        live_runs = {p.stem.rsplit("_", 1)[1] for p in BUFFER_DIR.glob("*.mkv")}
        for list_path in BUFFER_DIR.glob("run_*.csv"):
            if list_path.stem[len("run_"):] not in live_runs:
                list_path.unlink(missing_ok=True)

    def _newest_piece_file(self) -> Optional[pathlib.Path]:
        files = list(BUFFER_DIR.glob("*.mkv"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def _is_running(self) -> bool:
        with self._lock:
            return self._running

    def _set_last_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message


_recorder = CameraRecorder()


def get_camera_recorder() -> CameraRecorder:
    return _recorder
