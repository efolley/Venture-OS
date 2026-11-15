"""Run the PM agent on a GTM strategy pack (JSON) and write the PM result.

Exit codes: 0 complete or partial, 3 HITL 1 needed (rerun with --decision), 4 research
requested, 2 invalid input.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from .agent import PMAgent, status_exit_code
from .contracts import JsonObject
from .plan import DeepAgentsPlanner
from .providers import AnthropicModel


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pm", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="GTM strategy pack JSON")
    parser.add_argument("--decision", choices=["proceed", "research"], default=None,
                        help="HITL 1 answer when the baseline fails")
    parser.add_argument("--instructions", default="", help='for example "EU only"')
    parser.add_argument("--output", type=Path, default=None,
                        help="PM result JSON (default: runs/<input name>-pm.json)")
    parser.add_argument("--no-deepagents", action="store_true",
                        help="plan with 1 JSON model call instead of the DeepAgents loop")
    args = parser.parse_args(argv)
    _load_env()

    def progress(step: str, data: JsonObject, status: str) -> None:
        print(f"[{step}] {status} {json.dumps(data, ensure_ascii=False)[:200]}", file=sys.stderr)

    try:
        pack = json.loads(args.input.read_text(encoding="utf-8"))
        model = AnthropicModel()
        deep = None if args.no_deepagents else DeepAgentsPlanner(model.chat_model())
        result = PMAgent(model, deep_planner=deep).run(
            pack, decision=args.decision, instructions=args.instructions, progress=progress)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"PM run failed: {error}", file=sys.stderr)
        return 2

    output = args.output or Path("runs") / f"{args.input.stem}-pm.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    baseline = cast(JsonObject, result["baseline"])
    print(f"PM status: {result['status']}")
    print(f"Baseline: {baseline['status']}"
          + (f" (missing: {', '.join(cast(list[str], baseline['missing']))})"
             if baseline["missing"] else ""))
    if result["status"] == "hitl_required":
        print("HITL 1: rerun with --decision research (send gaps to Research) "
              "or --decision proceed (plan with gaps marked unknown).")
    elif result["status"] == "research_requested":
        request = cast(JsonObject, result["research_request"])
        print(f"Research gaps to send back: {', '.join(cast(list[str], request['gaps']))}")
    else:
        use_case = cast(JsonObject | None, result["use_case"])
        print(f"Use case: {use_case['statement'] if use_case else 'not set'}")
        planner = cast(JsonObject, result["planner"])
        print(f"Actions: {len(cast(list[object], result['action_plan']))} · planner: "
              f"{planner['engine']}" + (f" · still missing: {planner['missing']}"
                                        if planner["missing"] else ""))
    print(f"Output: {output}")
    return status_exit_code(cast(str, result["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
