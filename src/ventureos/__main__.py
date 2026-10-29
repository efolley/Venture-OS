"""Print a credential-free reference workflow as JSON."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts import BusinessBrief
from .harness import AgentHarness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True, help="Business brief JSON file")
    args = parser.parse_args()
    try:
        brief = BusinessBrief(**json.loads(args.brief.read_text()))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(asdict(AgentHarness().plan(brief)), indent=2))


if __name__ == "__main__":
    main()
