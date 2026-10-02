from dataclasses import dataclass


@dataclass(frozen=True)
class OnvifTarget:
    host: str
    username: str
    password: str
    clock_offset_s: float
