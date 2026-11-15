"""Run the standalone GTM orchestrator on a Research evidence-pack JSON file."""

import argparse
import json
import sys
from pathlib import Path

from research.providers import default_model

from .inputs import load_research_pack
from .orchestrator import GTMOrchestrator


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Research evidence-pack JSON")
    parser.add_argument(
        "--output",
        type=Path,
        help="strategy-pack output JSON (default: runs/<input-name>-gtm.json)",
    )
    parser.add_argument(
        "--instructions",
        default="",
        help="optional GTM focus or constraints (max 2000 characters)",
    )
    args = parser.parse_args(argv)
    _load_env()

    output_path = args.output or Path("runs") / f"{args.input.stem}-gtm.json"
    try:
        pack = load_research_pack(args.input)
        strategy = GTMOrchestrator(default_model()).run(
            pack,
            instructions=args.instructions,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(strategy, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        print(f"GTM run failed: {error}", file=sys.stderr)
        return 2

    failed_agents = [
        name
        for name, result in strategy["sub_agents"].items()
        if result.get("status") == "failed"
    ]
    print(f"GTM strategy status: {strategy['status']}")
    print(f"Company: {strategy['company']['name']}")
    print(f"Recommendations: {len(strategy['recommendations'])}")
    print(f"Gaps: {len(strategy['gaps'])}")
    print(f"Output: {output_path}")
    if failed_agents:
        print(f"Sub-agents failed: {', '.join(failed_agents)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
