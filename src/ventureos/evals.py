"""Offline content regression harness. Exit nonzero when a fixture fails."""
from ventureos.logging_utils import logged
import argparse
import json
from pathlib import Path
from .safety import ContentPolicy, UnsafeContent


@logged
def evaluate_file(path):
    cases=json.loads(Path(path).read_text())
    if not isinstance(cases,list) or not cases:
        raise ValueError('nonempty evaluation cases required')
    results=[]
    for case in cases:
        try:
            output=ContentPolicy().check(case['input'])
            passed=not case['blocked'] and output==case['output']
        except UnsafeContent:
            passed=case['blocked'] is True
        results.append({'name':case['name'],'passed':bool(passed)})
    return {'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'cases':results}


@logged
def evaluate_research_file(path):
    """Golden acceptance/evidence regressions, not a model accuracy benchmark."""
    from datetime import datetime, timezone
    from .execution import Artifact
    from .web_intelligence import valid_research, assess_quality
    cases=json.loads(Path(path).read_text())
    results=[]
    for case in cases:
        source={'id':'s1','url':'https://example.com','text':case['text'],'kind':'company',
                'published_at':case.get('published_at'),'retrieved_at':datetime.now(timezone.utc).isoformat()}
        finding={'text':case['claim'],'basis':case['basis'],'source_ids':[case.get('source_id','s1')],
                 'evidence':[{'source_id':case.get('source_id','s1'),'quote':case['quote']}]}
        content={'company':'Acme','website':'https://example.com','sources':[source],
                 'problems':[finding],'trends':[],'buying_signals':[],'conflicts':[],
                 'uncertainties':[],'schema_version':2,'quality':assess_quality([source],365)}
        try:
            content=ContentPolicy().check(content)
            accepted=valid_research(Artifact('eval','eval','eval','web_intelligence',content,('https://example.com',)))
            passed=accepted==case['accepted'] and not case.get('blocked',False)
            if case.get('stale'):
                passed=passed and content['quality']['stale_source_ids']==['s1']
        except UnsafeContent:
            passed=case.get('blocked',False)
        results.append({'name':case['name'],'passed':bool(passed)})
    return {'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'cases':results}


@logged
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixtures')
    parser.add_argument('--research',action='store_true')
    args=parser.parse_args()
    report=evaluate_research_file(args.fixtures) if args.research else evaluate_file(args.fixtures)
    print(json.dumps(report,indent=2))
    raise SystemExit(1 if report['failed'] else 0)


if __name__=='__main__': main()
