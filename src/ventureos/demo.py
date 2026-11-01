"""Local operator-only runtime demo; no model, web, or external actions."""
from ventureos.logging_utils import logged
from .execution import Task, Artifact
from .gateways import Principal
from .runtime import RuntimeHarness
from .store import PostgresStore


class BriefDemoAgent:
    @logged
    def execute(self, context):
        task = context.task
        context.services.checkpoint({'brief_validated':True})
        return Artifact(task.tenant_id,task.run_id,task.task_id,'brief_demo',{'goal':task.payload['goal'],'demo':True})


@logged
def execute_demo(dsn, brief, tenant, run_id):
    store=PostgresStore(dsn)
    store.initialize()
    runtime=RuntimeHarness(store)
    runtime.register('demo',BriefDemoAgent(),lambda a:a.kind=='brief_demo' and a.content.get('demo') is True)
    principal=Principal(tenant,frozenset({'task:submit','task:execute','agent:demo'}))
    task=Task(tenant,run_id,run_id+':brief','demo',{'goal':brief.goal})
    runtime.submit(principal,task)
    runtime.work_once(principal)
    row=store.get(tenant,task.task_id)
    return {'mode':'runtime_demo','status':row['status'],'attempts':row['attempts'],'artifact':row['artifact']}
