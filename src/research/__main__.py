"""Command line entry point: research 1 company and print the evidence pack as JSON."""

import argparse
import json
import sys
from pathlib import Path

from .agent import ResearchAgent
from .contracts import JsonObject
from .logs import setup_logging
from .providers import GeminiModel, TavilySearch
from .store import default_store


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research", description=__doc__)
    parser.add_argument("company", nargs="?", default="", help="company name")
    parser.add_argument("--website", default="", help="company website (http is upgraded to https)")
    parser.add_argument("--instructions", default="", help='for example "EU only"')
    parser.add_argument("--parent-run", default=None, help="previous run ID for a re-run")
    parser.add_argument("--gap", action="append", default=[], help="gap to research, repeatable")
    args = parser.parse_args(argv)
    _load_env()
    setup_logging()

    def progress(step: str, data: JsonObject, status: str) -> None:
        print(f"[{step}] {status} {json.dumps(data, ensure_ascii=False)[:200]}", file=sys.stderr)

    agent = ResearchAgent(GeminiModel(), TavilySearch(), default_store())
    try:
        result = agent.run(args.company, args.website, instructions=args.instructions,
                           gaps=args.gap, parent_run_id=args.parent_run, progress=progress)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    output: JsonObject = {"run_id": result.run_id, "status": result.status}
    if result.pack is not None:
        output["pack"] = result.pack
    else:
        output.update(message=result.message, candidates=result.candidates)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
