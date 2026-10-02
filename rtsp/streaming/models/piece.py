import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Piece:
    path: pathlib.Path
    run_id: str
    start_s: float
    end_s: float
    wall_start: float
