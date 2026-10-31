"""Offline content regression harness. Exit nonzero when a fixture fails."""
import argparse
import json
from pathlib import Path
from .safety import ContentPolicy, UnsafeContent


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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixtures')
    args=parser.parse_args()
    report=evaluate_file(args.fixtures)
    print(json.dumps(report,indent=2))
    raise SystemExit(1 if report['failed'] else 0)


if __name__=='__main__': main()
