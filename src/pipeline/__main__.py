"""Run the full flow for 1 company: Research, then the GTM orchestrator.

Writes the evidence pack and the strategy pack (with the company snapshot) as JSON:
  <output-dir>/<company>-research.json
  <output-dir>/<company>-gtm.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from gtm.orchestrator import GTMOrchestrator
from research.agent import ResearchAgent
from research.contracts import JsonObject
from research.logs import setup_logging
from research.providers import TavilySearch, default_model
from research.store import default_store

from .runner import run_pipeline, slug

EXIT_CODES = {"complete": 0, "partial": 0, "clarify": 3, "research_failed": 2, "gtm_failed": 1}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("company", help="company name")
    parser.add_argument("--website", default="", help="company website (http is upgraded to https)")
    parser.add_argument("--instructions", default="", help='for example "EU only"')
    parser.add_argument("--output-dir", type=Path, default=Path("runs"),
                        help="where to write the JSON files (default: runs/)")
    args = parser.parse_args(argv)
    _load_env()
    setup_logging()

    def progress(step: str, data: JsonObject, status: str) -> None:
        print(f"[{step}] {status} {json.dumps(data, ensure_ascii=False)[:200]}", file=sys.stderr)

    model = default_model()
    research = ResearchAgent(model, TavilySearch(), default_store())
    result = run_pipeline(research, GTMOrchestrator(model), args.company, args.website,
                          instructions=args.instructions, progress=progress)

    print(f"Pipeline status: {result.status}")
    if result.status == "clarify":
        print(result.message or "Pick the website to research, then run again with --website:")
        for candidate in result.candidates:
            print(f"  - {candidate.get('name')}: {candidate.get('website')}")
        return EXIT_CODES[result.status]
    if result.message:
        print(f"Message: {result.message}")
    name = slug(args.company)
    if result.pack is not None:
        path = args.output_dir / f"{name}-research.json"
        _write(path, result.pack)
        print(f"Research ({result.research_status}): {path}")
    if result.strategy is not None:
        path = args.output_dir / f"{name}-gtm.json"
        _write(path, result.strategy)
        snapshot = cast(JsonObject, result.strategy["snapshot"])
        missing = cast(list[str], snapshot.get("missing", []))
        print(f"GTM ({result.strategy['status']}): {path}")
        print(f"Snapshot: {snapshot['status']}"
              + (f" (missing: {', '.join(missing)})" if missing else ""))
    return EXIT_CODES[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
