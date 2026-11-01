"""Opt-in synchronous worker runtime for registered, trusted agent plugins."""
from ventureos.logging_utils import logged
import time
from dataclasses import replace
from typing import Callable
from .execution import Agent, AgentContext, Artifact, Task
from .gateways import Principal, ModelGateway, ToolGateway
from .store import PostgresStore, Lease, LeaseLost
from .safety import ContentPolicy
from .telemetry import operation


class TransientError(RuntimeError):
    """Only explicitly classified, safe failures are automatically retried."""


class Services:
    @logged
    def __init__(self, runtime, principal: Principal, lease: Lease):
        self.runtime, self.principal, self.lease = runtime, principal, lease

    @logged
    def content(self, value):
        """Mandatory entry point for future RAG adapters and untrusted context."""
        return ContentPolicy().check(value)

    @logged
    def checkpoint(self, value: dict):
        self.runtime.store.checkpoint(self.lease,value)

    @logged
    def snapshot(self, text):
        from .blobs import LocalBlobStore
        self.principal.authorize(self.lease.task.tenant_id,'agent:web_intelligence')
        self.runtime.store.reserve(self.lease,0)
        return LocalBlobStore().put(self.principal,self.lease.task.tenant_id,text)

    @logged
    def heartbeat(self):
        self.runtime.store.heartbeat(self.lease,self.runtime.lease_seconds)

    @logged
    def _timeout(self):
        deadline = self.lease.task.deadline
        remaining = self.runtime.call_timeout if deadline is None else min(self.runtime.call_timeout, deadline-time.time())
        if remaining<=0: raise ValueError('deadline exceeded')
        return min(remaining, self.runtime.lease_seconds / 2)

    @logged
    def model(self, model: str, prompt: str, max_units: int):
        self.principal.authorize(self.lease.task.tenant_id,'model:'+model)
        if self.runtime.models is None: raise ValueError('model provider not configured')
        timeout = self._timeout()
        # Conservatively charge the full reservation, including ambiguous failures.
        self.runtime.store.reserve(self.lease,max_units)
        return self.runtime.models.generate(self.principal,self.lease.task.tenant_id,model,prompt,max_units,timeout)

    @logged
    def tool(self, name: str, arguments: dict, units: int = 1):
        self.principal.authorize(self.lease.task.tenant_id,'tool:'+name)
        self._timeout()
        self.runtime.store.reserve(self.lease,units)
        return self.runtime.tools.invoke(self.principal,self.lease.task.tenant_id,name,arguments)


class RuntimeHarness:
    @logged
    def __init__(self, store: PostgresStore, *, models: ModelGateway | None = None,
                 tools: ToolGateway | None = None, lease_seconds: float = 60, call_timeout: float = 20):
        if lease_seconds<=0 or call_timeout<=0: raise ValueError('positive time limits required')
        self.store, self.models, self.tools = store, models, tools or ToolGateway()
        self.lease_seconds, self.call_timeout = lease_seconds, call_timeout
        self.last_error = None
        self.agents: dict[str, tuple[Agent,Callable[[Artifact],bool]]] = {}

    @logged
    def register(self, name: str, agent: Agent, validator: Callable[[Artifact],bool]):
        if name in self.agents or not isinstance(agent,Agent) or not callable(validator):
            raise ValueError('valid unique agent and validator required')
        self.agents[name] = (agent,validator)

    @logged
    def submit(self, principal: Principal, task: Task):
        principal.authorize(task.tenant_id,'task:submit')
        principal.authorize(task.tenant_id,'agent:'+task.agent_id)
        self.store.submit(task)

    @logged
    def approve(self, principal: Principal, tenant: str, task: str, digest: str):
        principal.authorize(tenant,'task:approve')
        return self.store.approve(tenant,task,digest)

    @logged
    def reject(self, principal: Principal, tenant: str, task: str, digest: str):
        principal.authorize(tenant,'task:approve')
        return self.store.reject(tenant,task,digest)

    @logged
    def replay(self, principal: Principal, tenant: str, task_id: str, new_task_id: str):
        """Explicit new execution with fresh identity, budget, and approval requirement."""
        principal.authorize(tenant,'task:replay')
        row=self.store.get(tenant,task_id)
        if not row or row['status'] not in ('failed','succeeded','rejected'):
            raise ValueError('only terminal tasks may be replayed')
        if new_task_id==task_id:
            raise ValueError('replay requires a new task ID')
        task=Task.from_dict(row['task'])
        self.submit(principal,replace(task,task_id=new_task_id))

    @logged
    def work_once(self, principal: Principal, worker: str = 'local', *, task_id: str | None = None):
        self.last_error = None
        principal.authorize(principal.tenant_id,'task:execute')
        allowed = tuple(name for name in self.agents if 'agent:'+name in principal.scopes)
        lease = self.store.claim(principal.tenant_id,worker,self.lease_seconds,allowed_agents=allowed, task_id=task_id)
        if lease is None: return None
        try:
            principal.authorize(lease.task.tenant_id,'agent:'+lease.task.agent_id)
            agent, validator = self.agents[lease.task.agent_id]
            with operation('agent.execute', {'agent.id':lease.task.agent_id, 'task.id':lease.task.task_id}):
                safe_task = replace(lease.task,payload=ContentPolicy().check(lease.task.payload))
                artifact = agent.execute(AgentContext(safe_task,ContentPolicy().check(lease.checkpoint),Services(self,principal,lease)))
            if isinstance(artifact,Artifact):
                artifact = replace(artifact,content=ContentPolicy().check(artifact.content),sources=tuple(ContentPolicy().check(list(artifact.sources))))
            if not isinstance(artifact,Artifact) or not validator(artifact):
                raise ValueError('artifact failed runtime validation')
            if lease.task.agent_id == 'web_intelligence':
                from .progress import report_phase
                report_phase('saving')
            self.store.complete(lease,artifact)
            return 'succeeded'
        except LeaseLost:
            return 'lease_lost'
        except Exception as error:
            from .diagnostics import describe_failure
            self.last_error = describe_failure(error)
            retry = isinstance(error,TransientError) and lease.attempt<lease.task.max_attempts
            try:
                self.store.fail(lease,retryable=retry,delay=min(2**(lease.attempt-1),60) if retry else 0)
            except LeaseLost:
                return 'lease_lost'
            return 'retry' if retry else 'failed'
