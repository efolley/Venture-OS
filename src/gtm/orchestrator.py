"""Parallel GTM orchestration and evidence-linked strategy-pack merging."""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import cast

from research.contracts import EvidencePack, JsonObject, Model
from research.pack import gtm_gaps

from .agents import GTMSubAgent, build_sub_agents
from .contracts import STRATEGY_SCHEMA_VERSION, SUB_AGENTS, StrategyPack, SubAgentResult, validate_strategy_pack
from .inputs import as_object, evidence_id_index, validate_research_pack
from .merge import merge_outputs
from .snapshot import build_snapshot


class GTMOrchestrator:
    """Run 3 model-backed analyses in parallel using only a validated pack."""

    def __init__(
        self,
        model: Model,
        *,
        sub_agents: dict[str, GTMSubAgent] | None = None,
    ) -> None:
        self.model = model
        self.sub_agents = sub_agents if sub_agents is not None else build_sub_agents(model)
        if set(self.sub_agents) != set(SUB_AGENTS):
            raise ValueError("GTM orchestrator requires exactly the 3 configured sub-agents.")

    def run(self, value: object, *, instructions: str = "") -> StrategyPack:
        if len(instructions) > 2000:
            raise ValueError("GTM instructions must be 2000 characters or fewer.")
        pack = validate_research_pack(value)
        evidence_index = evidence_id_index(pack)
        raw_company = as_object(pack.get("company"), "Research pack has no company object.")
        name = raw_company.get("name")
        website = raw_company.get("website")
        run_id = pack.get("run_id")
        status = pack.get("status")
        if not all(isinstance(item, str) and item.strip() for item in (name, website, run_id)):
            raise ValueError("Research pack company name, website, and run_id must be non-empty.")
        if status not in ("complete", "partial"):
            raise ValueError("Research pack status must be complete or partial.")

        results: dict[str, SubAgentResult] = {}
        with ThreadPoolExecutor(max_workers=len(SUB_AGENTS)) as executor:
            futures: dict[Future[SubAgentResult], str] = {
                executor.submit(self.sub_agents[agent].run, pack, instructions): agent
                for agent in SUB_AGENTS
            }
            for future in as_completed(futures):
                agent = futures[future]
                try:
                    results[agent] = future.result()
                except Exception as error:
                    results[agent] = {
                        "name": agent,
                        "status": "failed",
                        "recommendations": [],
                        "gaps": [f"{agent} analysis failed; inspect the error field."],
                        "error": f"{type(error).__name__}: {error}",
                    }

        research_gaps = _research_gaps(pack)
        agent_gaps: list[tuple[str, str]] = []
        recommendations: list[dict[str, object]] = []
        has_failed_agent = False
        has_empty_agent = False
        for agent in SUB_AGENTS:
            result = results[agent]
            if result["status"] == "failed":
                has_failed_agent = True
            if result["status"] == "complete" and not result["recommendations"]:
                has_empty_agent = True
            agent_gaps.extend((agent, gap) for gap in result["gaps"])
            for recommendation in result["recommendations"]:
                recommendations.append({
                    "id": f"r{len(recommendations) + 1}",
                    "agent": agent,
                    **recommendation,
                })

        merged = merge_outputs(self.model, recommendations, agent_gaps)
        snapshot = build_snapshot(self.model, pack, recommendations)

        strategy: JsonObject = {
            "schema_version": STRATEGY_SCHEMA_VERSION,
            "input_run_id": run_id,
            "company": {"name": name, "website": website},
            "research_status": status,
            "status": (
                "partial"
                # Sub-agent gaps are reported, not blocking: a real model always lists some.
                if status == "partial" or research_gaps or has_failed_agent or has_empty_agent
                or snapshot["status"] != "complete"
                else "complete"
            ),
            "snapshot": snapshot,
            "research_gaps": research_gaps,
            "gaps": research_gaps + merged["gaps"],
            "sub_agents": results,
            "recommendations": recommendations,
            "themes": merged["themes"],
            "merge": {"status": merged["status"], "error": merged["error"]},
        }
        return validate_strategy_pack(strategy, set(evidence_index))


def _research_gaps(pack: JsonObject) -> list[str]:
    gaps: list[str] = []
    coverage = pack.get("coverage")
    if isinstance(coverage, dict):
        for field, raw_entry in cast(dict[object, object], coverage).items():
            if not isinstance(field, str) or not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[object, object], raw_entry)
            if entry.get("status") != "partial":
                continue
            missing = entry.get("missing")
            details = (
                ", ".join(item for item in cast(list[object], missing) if isinstance(item, str))
                if isinstance(missing, list) else ""
            )
            gaps.append(f"Research coverage {field} is partial" + (f": {details}" if details else "."))

    coverage_lines = list(gaps)
    for gap in gtm_gaps(cast(EvidencePack, pack)):
        # Skip a GTM gap whose field is already named by a coverage line
        # (for example "market.trends" in "Research coverage market is partial: ...").
        field = gap.split()[0] if gap.strip() else ""
        if field and any(field in line for line in coverage_lines):
            continue
        text = f"Research GTM gap: {gap}"
        if text not in gaps:
            gaps.append(text)
    if pack.get("status") == "partial" and not gaps:
        gaps.append("Research pack status is partial.")
    return gaps
