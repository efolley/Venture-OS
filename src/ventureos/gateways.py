"""Injected providers and read-only tools, authorized before invocation."""
from dataclasses import dataclass
from typing import Callable, Protocol
from .execution import identity, json_payload
from .safety import ContentPolicy
from .telemetry import operation


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    scopes: frozenset[str]

    def authorize(self, tenant_id: str, scope: str):
        identity(self.tenant_id, tenant_id)
        if self.tenant_id != tenant_id or scope not in self.scopes:
            raise PermissionError('tenant or capability denied')


@dataclass(frozen=True)
class ModelReply:
    text: str
    units: int


class ModelProvider(Protocol):
    def __call__(self, model: str, prompt: str, *, max_units: int, timeout: float) -> ModelReply: ...


class ModelGateway:
    def __init__(self, provider: ModelProvider):
        self.provider = provider
        self.policy = ContentPolicy()

    def generate(self, principal: Principal, tenant_id: str, model: str, prompt: str, max_units: int, timeout: float = 30) -> ModelReply:
        principal.authorize(tenant_id, 'model:' + model)
        if type(max_units) is not int or max_units < 1:
            raise ValueError('positive reservation required')
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        with operation('model.generate', {'model.id':model}):
            result = self.provider(model, prompt, max_units=max_units, timeout=timeout)
        if not isinstance(result, ModelReply) or not isinstance(result.text, str) or type(result.units) is not int or not 0 <= result.units <= max_units:
            raise ValueError('provider violated usage contract')
        return ModelReply(self.policy.check(result.text), result.units)


class ToolGateway:
    def __init__(self):
        self.tools: dict[str, tuple[Callable, bool]] = {}
        self.policy = ContentPolicy()

    def register(self, name: str, handler: Callable, *, side_effect: bool):
        if name in self.tools:
            raise ValueError('duplicate tool')
        self.tools[name] = (handler, side_effect)

    def invoke(self, principal: Principal, tenant_id: str, name: str, arguments: dict):
        principal.authorize(tenant_id, 'tool:' + name)
        json_payload(arguments)
        handler, side_effect = self.tools[name]
        if side_effect:
            raise PermissionError('external writes disabled until action-ledger reconciliation is implemented')
        with operation('tool.invoke', {'tool.name':name}):
            result = handler(arguments)
        json_payload(result)
        return self.policy.check(result)
