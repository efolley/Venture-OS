"""Runnable company research: offline fixture or live Tavily + Claude + PostgreSQL."""
from ventureos.logging_utils import logged
import argparse
import json
import os
import uuid
from pathlib import Path

from .execution import AgentContext, Task
from .gateways import ModelGateway, ToolGateway, ModelReply, Principal
from .web_intelligence import ResearchRequest, WebIntelligenceAgent, valid_research


@logged
def fixture_run():
    """An explicitly synthetic sample, not live research or model inference."""
    from .safety import ContentPolicy
    class FixtureServices:
        @logged
        def tool(self, name, args):
            if name == 'web_search':
                return {'urls':['https://example.com']}
            return {'url':args['url'], 'text':'Synthetic Example Agency: manual onboarding delays projects; hiring an operations lead.'}

        @logged
        def content(self, value):
            return ContentPolicy().check(value)

        @logged
        def checkpoint(self, value):
            pass

        @logged
        def model(self, model, prompt, max_units):
            return ModelReply(json.dumps({
                'company_summary':{'text':'Example Agency is a fictional business used to demonstrate company research. Its sample onboarding process is manual and it is hiring an operations lead.', 'source_ids':['s1'], 'basis':'fact'},
                'problems':[{'text':'Manual onboarding delays projects', 'source_ids':['s1'], 'basis':'fact'}],
                'trends':[],
                'buying_signals':[{'text':'Operations hiring may indicate investment in processes', 'source_ids':['s1'], 'basis':'inference'}],
                'uncertainties':['Synthetic fixture only; no actual company research performed.']}), 0)
    task = Task('fixture','fixture','fixture','web_intelligence',
                {'company':'Example Agency (synthetic)','website':'https://example.com'})
    artifact = WebIntelligenceAgent('fixture').execute(AgentContext(task,services=FixtureServices()))
    return {'mode':'fixture', 'status':'succeeded', 'persisted':False, 'artifact':artifact.to_dict()}


@logged
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', action='store_true', help='Synthetic sample; no keys, database, or network')
    parser.add_argument('--company')
    parser.add_argument('--website')
    parser.add_argument('--provider', choices=('anthropic','ollama'), help='Model provider; defaults to MODEL_PROVIDER or anthropic')
    parser.add_argument('--model', help='Model ID; Ollama defaults to qwen3:8b')
    parser.add_argument('--tenant', default='local', help='Local operator scope, not authentication')
    parser.add_argument('--run-id', help='New ID refreshes; repeating an ID reuses accepted results')
    parser.add_argument('--max-pages',type=int,default=6)
    parser.add_argument('--output',type=Path,help='Write JSON to a new file instead of stdout')
    args = parser.parse_args()
    if args.fixture:
        result = fixture_run()
    else:
        from .config import load_local_env
        load_local_env()
        from .progress import report_phase
        report_phase('checking')
        provider = args.provider or os.environ.get('MODEL_PROVIDER','anthropic')
        if provider not in ('anthropic','ollama'):
            parser.error('MODEL_PROVIDER must be anthropic or ollama')
        args.model = args.model or (os.environ.get('OLLAMA_MODEL','qwen3:8b') if provider == 'ollama' else os.environ.get('ANTHROPIC_MODEL'))
        required = ('TAVILY_API_KEY','VENTUREOS_DATABASE_URL') + (() if provider == 'ollama' else ('ANTHROPIC_API_KEY',))
        for name in required:
            if not os.environ.get(name):
                parser.error('Set '+name+' for live research, or use --fixture')
        if not all((args.company,args.website,args.model)):
            parser.error('--company, --website, and --model are required for live research')
        try:
            request = ResearchRequest(args.company,args.website,max_pages=args.max_pages)
            from dataclasses import asdict
            from .web_live import TavilySearch, WebFetch, AnthropicModel, OllamaModel
            from .store import PostgresStore
            from .runtime import RuntimeHarness
            if provider == 'ollama':
                try:
                    OllamaModel.check_available(args.model)
                except (OSError,ValueError):
                    raise
            store = PostgresStore(os.environ['VENTUREOS_DATABASE_URL']); store.initialize()
            tools = ToolGateway()
            tools.register('web_search',TavilySearch(os.environ['TAVILY_API_KEY']),side_effect=False)
            tools.register('web_fetch',WebFetch(),side_effect=False)
            model_adapter = OllamaModel() if provider == 'ollama' else AnthropicModel(os.environ['ANTHROPIC_API_KEY'])
            runtime = RuntimeHarness(store,tools=tools,models=ModelGateway(model_adapter), lease_seconds=600, call_timeout=120)
            runtime.register('web_intelligence',WebIntelligenceAgent(args.model),valid_research)
            run = args.run_id or str(uuid.uuid4())
            task = Task(args.tenant,run,run+':research','web_intelligence',asdict(request))
            actor = Principal(args.tenant,frozenset({'task:submit','task:execute','agent:web_intelligence',
                            'tool:web_search','tool:web_fetch','model:'+args.model}))
            runtime.submit(actor,task)
            # Claim only this task: avoid processing another operator's queued run.
            row = store.get(args.tenant,task.task_id)
            if row['status'] != 'succeeded':
                runtime.work_once(actor,task_id=task.task_id)
            row = store.get(args.tenant,task.task_id)
            result = {'mode':'live', 'status':row['status'], 'run_id':run,
                      'persisted':True, 'artifact':row['artifact']}
            if row['status'] != 'succeeded':
                result['error'] = runtime.last_error or {'stage':'checking', 'function':'ventureos.runtime.RuntimeHarness.work_once', 'exception':'TaskUnavailable', 'message':'Task is not ready for execution or its lease is held by another worker.'}
        except Exception as error:
            from .diagnostics import describe_failure
            result = {'mode':'live', 'status':'failed', 'artifact':None, 'error':describe_failure(error)}
    encoded = json.dumps(result,indent=2)+'\n'
    if args.output:
        with args.output.open('x') as output:
            output.write(encoded)
    else:
        print(encoded,end='')
    if result['status'] != 'succeeded':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
