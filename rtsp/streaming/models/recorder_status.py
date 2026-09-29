from dataclasses import dataclass
from typing import Optional


@dataclass
class RecorderStatus:
    running: bool
    rtsp_url: str
    buffered_s: float
    newest_piece_age_s: Optional[float]
    preview_age_s: Optional[float]
    restarts: int
    last_error: Optional[str]
