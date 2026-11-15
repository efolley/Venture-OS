"""Run Research, then hand its evidence pack straight to the GTM orchestrator.

This is the first slice of the VentureOS harness: deterministic code, not an LLM agent.
It chains the 2 implemented agents and stops early when a step cannot continue:

- Research asks the user to pick a website (`clarify`): stop and return the candidates.
- Research fails or returns no pack: stop with the error.
- Research returns a `complete` or `partial` pack: run GTM on it. A partial pack is still
  analyzed; GTM marks its own result `partial` and lists the Research gaps.
- GTM raises: keep the evidence pack and report the error.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from gtm.orchestrator import GTMOrchestrator
from research.agent import ResearchAgent
from research.contracts import EvidencePack, JsonObject, Progress, no_progress

PipelineStatus = Literal["complete", "partial", "clarify", "research_failed", "gtm_failed"]


@dataclass
class PipelineResult:
    status: PipelineStatus
    research_run_id: str = ""
    research_status: str = ""
    pack: EvidencePack | None = None
    strategy: JsonObject | None = None
    candidates: list[JsonObject] = field(default_factory=list)
    message: str = ""


def run_pipeline(
    research: ResearchAgent,
    gtm: GTMOrchestrator,
    company: str,
    website: str = "",
    *,
    instructions: str = "",
    progress: Progress = no_progress,
) -> PipelineResult:
    """Research 1 company, then run GTM on its evidence pack."""
    progress("pipeline", {"step": "research", "company": company, "website": website}, "running")
    try:
        result = research.run(company, website, instructions=instructions, progress=progress)
    except Exception as error:  # noqa: BLE001 - report, do not crash the pipeline
        progress("pipeline", {"step": "research", "error": str(error)}, "failed")
        return PipelineResult("research_failed", message=f"{type(error).__name__}: {error}")

    base = PipelineResult("research_failed", research_run_id=result.run_id,
                          research_status=result.status, message=result.message)
    if result.status == "clarify":
        progress("pipeline", {"step": "research", "candidates": len(result.candidates)}, "clarify")
        base.status, base.candidates = "clarify", result.candidates
        return base
    if result.pack is None or result.status not in ("complete", "partial"):
        progress("pipeline", {"step": "research", "status": result.status}, "failed")
        base.message = base.message or f"Research ended with status {result.status} and no pack."
        return base
    base.pack = result.pack

    progress("pipeline", {"step": "gtm", "research_status": result.status}, "running")
    try:
        strategy = gtm.run(dict(result.pack), instructions=instructions)
    except Exception as error:  # noqa: BLE001 - keep the evidence pack
        progress("pipeline", {"step": "gtm", "error": str(error)}, "failed")
        base.status, base.message = "gtm_failed", f"{type(error).__name__}: {error}"
        return base
    base.strategy = dict(strategy)
    base.status = "complete" if strategy["status"] == "complete" else "partial"
    progress("pipeline", {"step": "gtm", "status": strategy["status"]}, base.status)
    return base


def slug(name: str) -> str:
    """A file-name-safe company name: 'Baseten, Inc.' becomes 'baseten-inc'."""
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "company"
