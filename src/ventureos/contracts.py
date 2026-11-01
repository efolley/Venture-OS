"""Shared planning contracts; execution contracts will extend these types."""
from ventureos.logging_utils import logged

from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessBrief:
    goal: str
    target_market: str
    service: str
    constraints: list[str]

    @logged
    def __post_init__(self) -> None:
        for field in ("goal", "target_market", "service"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a nonempty string")
        if not isinstance(self.constraints, list) or not all(
            isinstance(item, str) for item in self.constraints
        ):
            raise ValueError("constraints must be a list of strings")


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    owner: str
    deliverable: str
    depends_on: tuple[str, ...] = ()
    condition: str = "always"


@dataclass(frozen=True)
class WorkflowPlan:
    brief: BusinessBrief
    steps: tuple[WorkflowStep, ...]
    mode: str = "preview"
