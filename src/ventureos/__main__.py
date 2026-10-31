"""Print a credential-free reference workflow as JSON."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from .contracts import BusinessBrief
from .harness import AgentHarness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True, help="Business brief JSON file")
    parser.add_argument('--execute-demo', action='store_true', help='Opt in to local PostgreSQL demo execution, not business agent execution')
    parser.add_argument('--tenant', help='Operator-selected tenant for the runtime demo')
    parser.add_argument('--run-id', help='Stable ID; repeating it reuses the persisted result')
    args = parser.parse_args()
    try:
        brief = BusinessBrief(**json.loads(args.brief.read_text()))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    if args.execute_demo:
        if not args.tenant or not args.run_id:
            parser.error('--tenant and --run-id are required for runtime demo')
        dsn = os.environ.get('VENTUREOS_DATABASE_URL')
        if not dsn:
            parser.error('Set VENTUREOS_DATABASE_URL for the runtime demo')
        try:
            from .demo import execute_demo
            result = execute_demo(dsn,brief,args.tenant,args.run_id)
        except Exception:
            parser.error('Runtime demo failed; check optional dependencies, database access, and task input')
        print(json.dumps(result,indent=2))
        if result['status']!='succeeded':
            raise SystemExit(1)
    else:
        print(json.dumps(asdict(AgentHarness().plan(brief)), indent=2))


if __name__ == "__main__":
    main()
