"""The PM agent: check the baseline, apply HITL 1, establish the use case, then plan.

PM's main purpose is to establish 1 use case before anything is built: "Help {ICP} solve
{core problem} with {MVP solution}", with a short why and the key assumption to test. The
action plan, a 1-pager, and an MVP idea derive from it. PM proposes; a person
decides what to do next. Nothing is built.

Flow:
1. Validate the GTM strategy pack.
2. Check the minimum baseline in code.
3. If the baseline fails and no decision was given, stop with `hitl_required`: a person
   chooses `research` (send the gaps back to Research) or `proceed` (plan with the gaps
   marked unknown).
4. With `research`, stop with `research_requested` and the exact Research gaps.
5. Otherwise set the use case, then plan: DeepAgents first, then the JSON planner for
   anything left unfinished.
"""

import time
from typing import Literal, cast

from . import baseline as baseline_rules
from .contracts import (
    RESULT_SCHEMA_VERSION, Decision, JsonObject, Model, PMStatus, Progress, no_progress,
    validate_strategy_pack,
)
from .plan import DeepAgentsPlanner, JsonPlanner, PlanState

HITL_QUESTION = ("The strategy pack is missing required information. Research more to fill "
                 "the gaps, or proceed and plan with the gaps marked unknown?")


class PMAgent:
    def __init__(self, model: Model, *, deep_planner: DeepAgentsPlanner | None = None) -> None:
        self.model = model
        self.deep_planner = deep_planner

    def run(self, value: object, *, decision: Decision | None = None, instructions: str = "",
            progress: Progress = no_progress) -> JsonObject:
        pack = validate_strategy_pack(value)
        check = baseline_rules.evaluate(pack)
        progress("baseline", {"status": check["status"], "missing": check["missing"]},
                 "success" if check["status"] == "pass" else "failed")
        company = cast(JsonObject, pack["company"])
        result: JsonObject = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "input_run_id": pack["input_run_id"],
            "company": {"name": company.get("name"), "website": company.get("website", "")},
            "status": "complete",
            "baseline": check,
            "decision": decision,
            "hitl": None,
            "research_request": None,
            "use_case": None,
            "action_plan": [],
            "one_pager": None,
            "mvp_idea": None,
            "planner": {"engine": "", "rejected": [], "missing": [], "error": ""},
        }
        if check["status"] == "fail":
            if decision is None:
                result["status"] = "hitl_required"
                result["hitl"] = {"question": HITL_QUESTION, "options": ["research", "proceed"],
                                  "missing": check["missing"], "research_gaps": check["research_gaps"]}
                progress("hitl", {"missing": check["missing"]}, "waiting")
                return result
            if decision == "research":
                result["status"] = "research_requested"
                result["research_request"] = {
                    "company": company.get("name"), "website": company.get("website", ""),
                    "parent_run_id": pack["input_run_id"], "gaps": check["research_gaps"],
                    "instructions": instructions,
                }
                progress("hitl", {"decision": "research", "gaps": check["research_gaps"]}, "done")
                return result

        state = PlanState(pack)
        started = time.perf_counter()
        planner = cast(dict[str, object], result["planner"])
        engines: list[str] = []
        if self.deep_planner is not None:
            engines.append("deepagents")
            try:
                self.deep_planner.run(state, instructions, progress)
            except Exception as error:  # noqa: BLE001 - fall back to the JSON planner
                planner["error"] = f"DeepAgents stopped: {type(error).__name__}: {error}"[:300]
                progress("plan", {"planner": "deepagents", "error": planner["error"]}, "failed")
        if state.missing():
            engines.append("json")
            JsonPlanner(self.model).run(state, instructions, progress)

        planner["engine"] = "+".join(engines)
        planner["duration_s"] = round(time.perf_counter() - started, 1)
        planner["rejected"] = state.rejected[-20:]
        planner["missing"] = state.missing()
        actions = sorted(state.actions, key=lambda a: (a["priority"], ("now", "next", "later")
                                                       .index(a["horizon"])))
        result.update(use_case=state.use_case, action_plan=actions,
                      one_pager=state.one_pager,
                      mvp_idea=state.mvp_idea)
        gaps_accepted = check["status"] == "fail"  # only reachable with decision "proceed"
        status: PMStatus = "partial" if state.missing() or gaps_accepted else "complete"
        result["status"] = status
        progress("plan", {"status": status, "actions": len(actions),
                          "rejected": len(state.rejected), "duration_s": planner["duration_s"]}, "done")
        return result


def status_exit_code(status: str) -> int:
    codes: dict[str, Literal[0, 1, 3, 4]] = {"complete": 0, "partial": 0, "hitl_required": 3,
                                             "research_requested": 4}
    return codes.get(status, 1)
