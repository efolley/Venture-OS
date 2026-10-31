"""Provider-neutral execution contracts. JSON payloads cross persistence boundaries."""
from dataclasses import asdict, dataclass, field
import json
import math
from typing import Any, Protocol, runtime_checkable


def json_payload(value: Any) -> None:
    try:
        if not isinstance(value, dict):
            raise ValueError('payload must be an object')
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('payload must be a finite JSON object') from error


def identity(*values: str) -> None:
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError('identifiers must be nonempty strings')


@dataclass(frozen=True)
class Task:
    tenant_id: str
    run_id: str
    task_id: str
    agent_id: str
    payload: dict
    max_attempts: int = 3
    budget_units: int = 10000
    deadline: float | None = None
    requires_approval: bool = False

    def __post_init__(self):
        identity(self.tenant_id, self.run_id, self.task_id, self.agent_id)
        json_payload(self.payload)
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError('max_attempts must be positive')
        if type(self.budget_units) is not int or self.budget_units < 0:
            raise ValueError('budget_units must be nonnegative')
        if self.deadline is not None and (type(self.deadline) not in (int, float) or not math.isfinite(self.deadline)):
            raise ValueError('deadline must be a finite epoch timestamp')
        if type(self.requires_approval) is not bool:
            raise ValueError('requires_approval must be boolean')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**value)


@dataclass(frozen=True)
class Artifact:
    tenant_id: str
    run_id: str
    task_id: str
    kind: str
    content: dict
    sources: tuple[str, ...] = ()

    def __post_init__(self):
        identity(self.tenant_id, self.run_id, self.task_id, self.kind)
        json_payload(self.content)
        if not isinstance(self.sources, tuple) or any(not isinstance(s, str) or not s.strip() for s in self.sources):
            raise ValueError('sources must be a tuple of nonempty references')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, 'sources': tuple(value.get('sources', ()))})


@dataclass(frozen=True)
class AgentContext:
    task: Task
    checkpoint: dict = field(default_factory=dict)
    services: Any = None


@runtime_checkable
class Agent(Protocol):
    def execute(self, context: AgentContext) -> Artifact: ...
