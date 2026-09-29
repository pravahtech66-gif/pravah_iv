import pathlib
import shutil
from typing import Optional

from streaming.config import QUEUE_DIR


def enqueue_clip(path: pathlib.Path, batch_idx: int) -> pathlib.Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    dest = QUEUE_DIR / f"batch_{batch_idx:05d}.mp4"
    shutil.move(str(path), str(dest))
    return dest


def take_oldest_clip() -> Optional[tuple]:
    clips = sorted(QUEUE_DIR.glob("batch_*.mp4")) if QUEUE_DIR.exists() else []
    if not clips:
        return None
    return clips[0], int(clips[0].stem[len("batch_"):])


def discard_queued_clips() -> int:
    clips = list(QUEUE_DIR.glob("batch_*.mp4")) if QUEUE_DIR.exists() else []
    for clip in clips:
        clip.unlink(missing_ok=True)
    return len(clips)
