import pathlib
import subprocess
import tempfile
import time

from streaming.config import _log
from streaming.recorder import list_finished_pieces

CONTIGUITY_TOLERANCE_S = 0.05
JOIN_TIMEOUT_S = 120


def group_contiguous_pieces(pieces: list) -> list:
    chains = []
    for piece in pieces:
        previous = chains[-1][-1] if chains else None
        if (previous is not None and previous.run_id == piece.run_id
                and abs(piece.start_s - previous.end_s) <= CONTIGUITY_TOLERANCE_S):
            chains[-1].append(piece)
        else:
            chains.append([piece])
    return chains


def chain_duration(chain: list) -> float:
    return chain[-1].end_s - chain[0].start_s


def select_latest_clip_pieces(pieces: list, duration_s: float, not_before_wall=None):
    if not_before_wall is not None:
        pieces = [p for p in pieces if p.wall_start >= not_before_wall]
    for chain in reversed(group_contiguous_pieces(pieces)):
        selected = []
        for piece in reversed(chain):
            selected.insert(0, piece)
            if chain_duration(selected) >= duration_s:
                return selected
    return None


def join_pieces_into_clip(pieces: list, dest: pathlib.Path, duration_s=None) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as list_file:
        for piece in pieces:
            list_file.write(f"file '{piece.path.resolve().as_posix()}'\n")
        list_path = pathlib.Path(list_file.name)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
           "-i", str(list_path), "-c", "copy"]
    if duration_s is not None:
        cmd += ["-t", str(duration_s)]
    cmd.append(str(dest))
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=JOIN_TIMEOUT_S)
    finally:
        list_path.unlink(missing_ok=True)
    if result.returncode != 0:
        _log.warning(f"[cutter] join failed: {result.stderr.decode(errors='replace')[-300:]}")
        return False
    return dest.exists() and dest.stat().st_size > 0


def cut_latest_clip(duration_s: float, dest: pathlib.Path, not_before_wall=None) -> bool:
    pieces = select_latest_clip_pieces(list_finished_pieces(), duration_s, not_before_wall)
    if pieces is None:
        return False
    return join_pieces_into_clip(pieces, dest, duration_s)


def wait_for_latest_clip(duration_s: float, dest: pathlib.Path, timeout_s: float,
                         not_before_wall=None, should_stop=lambda: False) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline and not should_stop():
        if cut_latest_clip(duration_s, dest, not_before_wall):
            return True
        time.sleep(1)
    return False


def cut_window_clips(start_wall: float, end_wall: float, dest: pathlib.Path) -> list:
    pieces = [p for p in list_finished_pieces()
              if p.wall_start + (p.end_s - p.start_s) > start_wall and p.wall_start < end_wall]
    chains = group_contiguous_pieces(pieces)
    saved = []
    for index, chain in enumerate(chains, start=1):
        target = dest if len(chains) == 1 else dest.with_name(f"{dest.stem}_part{index}{dest.suffix}")
        if join_pieces_into_clip(chain, target):
            saved.append(target)
    return saved
