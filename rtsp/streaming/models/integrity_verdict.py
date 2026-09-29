from dataclasses import dataclass, field


@dataclass
class IntegrityVerdict:
    passed: bool
    reasons: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
