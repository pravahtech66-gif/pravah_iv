from dataclasses import dataclass, field


@dataclass
class FitnessVerdict:
    score: float
    status: str
    reasons: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
