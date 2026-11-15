"""The minimum baseline, checked in code. The model never decides whether the input is enough.

A strategy pack passes when every required check passes. A failed check names the Research
gaps that would fix it, so HITL 1 can send exactly those back to Research.
"""

from typing import cast

from .contracts import Baseline, Check, JsonObject, SUB_AGENTS, recommendations

# Snapshot lines required for planning. Vision is optional: many companies publish none.
REQUIRED_SNAPSHOT_LINES = (
    "mission", "problem", "target_market", "icp", "product", "client_value",
    "market_brief", "competitive_landscape",
)
# Research items that fill each snapshot line, used for the "research more" option.
RESEARCH_GAPS = {
    "mission": ["company.mission"],
    "vision": ["company.vision"],
    "problem": ["company.problem"],
    "target_market": ["sales.target_customer", "market.category"],
    "icp": ["sales.target_customer", "sales.buyer_role"],
    "product": ["company.offering"],
    "client_value": ["company.offering", "company.problem"],
    "market_brief": ["market"],
    "competitive_landscape": ["competitors"],
}
MIN_HYPOTHESES = 2
MIN_SALES_RECOMMENDATIONS = 2
MIN_MARKET_RECOMMENDATIONS = 1


def _check(check_id: str, label: str, passed: bool, detail: str, required: bool = True) -> Check:
    return {"id": check_id, "label": label, "passed": passed, "required": required,
            "detail": detail}


def evaluate(pack: JsonObject) -> Baseline:
    snapshot = cast(JsonObject, pack["snapshot"])
    lines = cast(dict[str, JsonObject], snapshot["lines"])
    sub_agents = cast(dict[str, JsonObject], pack["sub_agents"])
    checks: list[Check] = [
        _check("research_complete", "Research evidence pack is complete",
               pack.get("research_status") == "complete",
               f"research status is {pack.get('research_status')}"),
    ]
    for key in REQUIRED_SNAPSHOT_LINES:
        found = lines[key].get("status") == "found"
        checks.append(_check(f"snapshot.{key}", f"Snapshot has {key.replace('_', ' ')}", found,
                             "found" if found else "unknown in the snapshot"))
    vision = lines["vision"].get("status") == "found"
    checks.append(_check("snapshot.vision", "Snapshot has vision", vision,
                         "found" if vision else "not published or not found (optional)",
                         required=False))
    for agent in SUB_AGENTS:
        status = sub_agents[agent].get("status")
        checks.append(_check(f"sub_agent.{agent}", f"{agent.replace('_', ' ')} completed",
                             status == "complete", f"status is {status}"))
    hypotheses = [r for r in recommendations(pack, "competitive_strategy") if "rank" in r]
    checks.append(_check("hypotheses", f"At least {MIN_HYPOTHESES} ranked competitive hypotheses",
                         len(hypotheses) >= MIN_HYPOTHESES, f"{len(hypotheses)} found"))
    sales = recommendations(pack, "challenger_salesman")
    checks.append(_check("sales", f"At least {MIN_SALES_RECOMMENDATIONS} sales recommendations",
                         len(sales) >= MIN_SALES_RECOMMENDATIONS, f"{len(sales)} found"))
    market = recommendations(pack, "market_analysis")
    checks.append(_check("market", f"At least {MIN_MARKET_RECOMMENDATIONS} market recommendation",
                         len(market) >= MIN_MARKET_RECOMMENDATIONS, f"{len(market)} found"))

    failed = [c for c in checks if c["required"] and not c["passed"]]
    research_gaps: list[str] = []
    for check in failed:
        if check["id"].startswith("snapshot."):
            for gap in RESEARCH_GAPS[check["id"].split(".", 1)[1]]:
                if gap not in research_gaps:
                    research_gaps.append(gap)
    return {"status": "fail" if failed else "pass", "checks": checks,
            "missing": [c["id"] for c in failed], "research_gaps": research_gaps}
