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
    from .web_intelligence import ResearchRequest, valid_research, assess_quality, entity_match
    cases=json.loads(Path(path).read_text())
    results=[]
    for case in cases:
        company,website=case.get('company','Acme'),case.get('website','https://example.com')
        url,aliases=case.get('url',website),case.get('aliases',[])
        request=ResearchRequest(company,website,aliases=aliases)
        source={'id':'s1','url':url,'text':case['text'],'kind':case.get('kind','company'),
                'published_at':case.get('published_at'),'retrieved_at':datetime.now(timezone.utc).isoformat(),
                'entity_match':entity_match(request,url,case['text']) or 'none'}
        finding={'text':case['claim'],'basis':case['basis'],'source_ids':[case.get('source_id','s1')],
                 'evidence':[{'source_id':case.get('source_id','s1'),'quote':case['quote']}]}
        if 'date' in case: finding['date']=case['date']
        if 'signal_status' in case: finding['signal_status']=case['signal_status']
        content={'company':company,'website':website,'sources':[source],
                 'problems':[],'trends':[],'buying_signals':[],'conflicts':[],
                 'uncertainties':[],'schema_version':3,'quality':assess_quality([source],365)}
        if aliases: content['aliases']=aliases
        category=case.get('category','problems')
        if category.startswith('gtm.'): content['gtm']={category[4:]:[finding]}
        else: content[category]=[finding]
        try:
            content=ContentPolicy().check(content)
            accepted=valid_research(Artifact('eval','eval','eval','web_intelligence',content,(url,)))
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
