"""Offline tests for the PM agent. Provider doubles only; no live model calls."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from pm import __main__ as cli
from pm.agent import PMAgent
from pm.baseline import evaluate
from pm.contracts import JsonObject, validate_strategy_pack
from pm.plan import JsonPlanner, PlanState, build_tools

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = (ROOT / "data" / "notion-gtm.json", ROOT / "data" / "linear-gtm.json")


def load(path: Path = SAMPLES[0]) -> JsonObject:
    return cast(JsonObject, json.loads(path.read_text(encoding="utf-8")))


def incomplete(pack: JsonObject) -> JsonObject:
    """A copy with no mission and no competitive landscape, from a partial Research pack."""
    pack = copy.deepcopy(pack)
    lines = cast(dict[str, JsonObject], cast(JsonObject, pack["snapshot"])["lines"])
    for key in ("mission", "competitive_landscape"):
        lines[key] = {"status": "unknown", "text": "", "basis": "", "evidence_ids": [],
                      "recommendation_ids": []}
    pack["research_status"] = "partial"
    return pack


def plan_json(pack: JsonObject, *, bad_ids: bool = False) -> JsonObject:
    rec = "r999" if bad_ids else cast(list[JsonObject], pack["recommendations"])[0]["id"]
    action = {"description": "Run a 2-week test.", "owner": "sales", "priority": 1,
              "horizon": "now", "success_metric": "10 qualified calls", "based_on": [rec]}
    purposes = ("validate", "prepare", "deliver")
    return {
        "use_case": use_case_json(rec),
        "actions": [{**action, "purpose": purposes[n - 1], "title": f"Action {n}"}
                    for n in range(1, 4)],
        "one_pager": {
            "headline": "One workspace for team knowledge", "problem": "Scattered tools.",
            "value_proposition": "Less tool switching.", "target_customer": "Growing teams.",
            "key_points": ["One", "Two", "Three"], "proof_points": [f"Fact ({rec})"],
            "call_to_action": "Book a 20-minute call.", "based_on": [rec]},
        "mvp_idea": {
            "product_goal": "Show a shared workspace for one team.", "target_user": "Team lead",
            "core_job": "Keep projects and docs together.",
            "must_have_features": [{"name": f"Feature {n}", "why": "Core job.",
                                    "based_on": [rec]} for n in range(1, 4)],
            "out_of_scope": ["Billing"], "success_criteria": ["A demo user finds a doc in 1 click"],
            "demo_scenario": "A team lead creates a project and links its spec.",
            "based_on": [rec]},
    }


def use_case_json(rec: str, icp: str = "operations leads at growing agencies") -> JsonObject:
    return {
        "icp": {"text": icp, "based_on": [rec]},
        "core_problem": {"text": "Scattered client feedback", "based_on": [rec]},
        "mvp_solution": {"text": "a feedback-to-task routing board", "based_on": [rec]},
        "why": "The top-ranked hypothesis points here. The pack has direct evidence for it.",
        "why_based_on": [rec],
        "key_assumption": "Buyers rank routing above price.",
        "alternatives": [{"statement": "Help finance teams cut tool costs",
                          "why_not": "Only third-party price evidence."}],
    }


class FakeModel:
    def __init__(self, replies: list[JsonObject] | None = None) -> None:
        self.replies = replies
        self.requests: list[JsonObject] = []

    def json(self, system: str, prompt: str) -> JsonObject:
        request = cast(JsonObject, json.loads(prompt))
        self.requests.append(request)
        if self.replies:
            return self.replies.pop(0)
        return plan_json(cast(JsonObject, {"recommendations": [{"id": "r1"}]}))


class ScriptedDeepPlanner:
    """Stands in for DeepAgents: calls the same tools an agent would, in order."""

    def __init__(self, *, actions: int = 3, fail: bool = False) -> None:
        self.actions, self.fail = actions, fail

    def run(self, state: PlanState, instructions: str = "", progress=None) -> None:  # type: ignore[no-untyped-def]
        if self.fail:
            raise RuntimeError("model unavailable")
        tools = {tool.__name__: tool for tool in build_tools(state, lambda *a: None)}
        json.loads(tools["read_strategy"]("snapshot"))
        plan = plan_json(state.pack)
        use_case = cast(dict[str, JsonObject], plan["use_case"])
        tools["set_use_case"](
            icp=use_case["icp"]["text"], icp_based_on=use_case["icp"]["based_on"],
            core_problem=use_case["core_problem"]["text"],
            core_problem_based_on=use_case["core_problem"]["based_on"],
            mvp_solution=use_case["mvp_solution"]["text"],
            mvp_solution_based_on=use_case["mvp_solution"]["based_on"],
            why=use_case["why"], why_based_on=use_case["why_based_on"],
            key_assumption=use_case["key_assumption"], alternatives=use_case["alternatives"])
        for action in cast(list[JsonObject], plan["actions"])[: self.actions]:
            tools["add_action"](**action)
        tools["set_one_pager"](**cast(JsonObject, plan["one_pager"]))
        tools["set_mvp_idea"](**cast(JsonObject, plan["mvp_idea"]))


class BaselineTests(unittest.TestCase):
    def test_real_samples_pass(self) -> None:
        for path in SAMPLES:
            with self.subTest(sample=path.name):
                self.assertEqual(evaluate(validate_strategy_pack(load(path)))["status"], "pass")

    def test_missing_lines_fail_and_map_to_research_gaps(self) -> None:
        result = evaluate(validate_strategy_pack(incomplete(load())))
        self.assertEqual(result["status"], "fail")
        self.assertIn("snapshot.mission", result["missing"])
        self.assertIn("research_complete", result["missing"])
        self.assertEqual(result["research_gaps"], ["company.mission", "competitors"])

    def test_missing_vision_is_optional(self) -> None:
        pack = load()
        lines = cast(dict[str, JsonObject], cast(JsonObject, pack["snapshot"])["lines"])
        lines["vision"]["status"] = "unknown"
        self.assertEqual(evaluate(validate_strategy_pack(pack))["status"], "pass")

    def test_invalid_input_is_rejected(self) -> None:
        pack = load()
        pack["schema_version"] = 3
        with self.assertRaisesRegex(ValueError, "schema_version"):
            validate_strategy_pack(pack)


class HitlTests(unittest.TestCase):
    def test_failed_baseline_stops_for_a_decision(self) -> None:
        model = FakeModel()
        result = PMAgent(model).run(incomplete(load()))
        self.assertEqual(result["status"], "hitl_required")
        self.assertEqual(cast(JsonObject, result["hitl"])["options"], ["research", "proceed"])
        self.assertEqual(result["action_plan"], [])
        self.assertEqual(model.requests, [])  # no planning before the person decides

    def test_research_decision_returns_the_gaps(self) -> None:
        pack = incomplete(load())
        result = PMAgent(FakeModel()).run(pack, decision="research", instructions="EU only")
        request = cast(JsonObject, result["research_request"])
        self.assertEqual(result["status"], "research_requested")
        self.assertEqual(request["gaps"], ["company.mission", "competitors"])
        self.assertEqual(request["parent_run_id"], pack["input_run_id"])

    def test_proceed_decision_plans_but_stays_partial(self) -> None:
        pack = incomplete(load())
        result = PMAgent(FakeModel([plan_json(pack)])).run(pack, decision="proceed")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(cast(list[object], result["action_plan"])), 3)


class PlanningTests(unittest.TestCase):
    def test_deepagents_tools_produce_a_complete_plan(self) -> None:
        model = FakeModel()
        result = PMAgent(model, deep_planner=ScriptedDeepPlanner()).run(load())  # type: ignore[arg-type]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(cast(JsonObject, result["planner"])["engine"], "deepagents")
        self.assertEqual(model.requests, [])
        self.assertEqual([a["id"] for a in cast(list[JsonObject], result["action_plan"])],
                         ["a1", "a2", "a3"])
        self.assertIsNotNone(result["one_pager"])
        self.assertEqual(len(cast(list[object], cast(JsonObject, result["mvp_idea"])
                                  ["must_have_features"])), 3)

    def test_unfinished_deepagents_plan_is_completed_by_json_planner(self) -> None:
        pack = load()
        model = FakeModel([plan_json(pack)])
        result = PMAgent(model, deep_planner=ScriptedDeepPlanner(actions=1)).run(pack)  # type: ignore[arg-type]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(cast(JsonObject, result["planner"])["engine"], "deepagents+json")
        self.assertEqual(model.requests[0]["actions_already_recorded"], 1)

    def test_deepagents_failure_falls_back_to_json(self) -> None:
        pack = load()
        result = PMAgent(FakeModel([plan_json(pack)]),
                         deep_planner=ScriptedDeepPlanner(fail=True)).run(pack)  # type: ignore[arg-type]
        self.assertEqual(result["status"], "complete")
        self.assertIn("model unavailable", cast(JsonObject, result["planner"])["error"])

    def test_invented_ids_are_rejected_then_corrected_by_retry(self) -> None:
        pack = load()
        model = FakeModel([plan_json(pack, bad_ids=True), plan_json(pack)])
        result = PMAgent(model).run(pack)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(model.requests), 2)
        self.assertIn("not in the strategy pack", json.dumps(model.requests[1]["validation_errors"]))

    def test_validators_enforce_owner_priority_and_counts(self) -> None:
        state = PlanState(validate_strategy_pack(load()))
        state.set_use_case(cast(JsonObject, plan_json(state.pack)["use_case"]))
        good = cast(list[JsonObject], plan_json(state.pack)["actions"])[0]
        for change, message in (({"purpose": "explore"}, "purpose"), ({"owner": "ceo"}, "owner"), ({"priority": 5}, "priority"),
                                ({"horizon": "soon"}, "horizon"), ({"based_on": []}, "at least 1")):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                state.add_action({**good, **change})
        brief = cast(JsonObject, plan_json(state.pack)["mvp_idea"])
        with self.assertRaisesRegex(ValueError, "3 to 5 features"):
            state.set_mvp_idea({**brief, "must_have_features": []})

    def test_json_planner_stops_after_one_retry(self) -> None:
        pack = load()
        bad = plan_json(pack, bad_ids=True)
        model = FakeModel([bad, bad])
        state = PlanState(validate_strategy_pack(pack))
        JsonPlanner(model).run(state)
        self.assertEqual(len(model.requests), 2)
        self.assertTrue(state.missing())


class UseCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = PlanState(validate_strategy_pack(load()))
        self.rec = cast(list[JsonObject], self.state.pack["recommendations"])[0]["id"]

    def test_statement_is_built_in_code(self) -> None:
        use_case = self.state.set_use_case(use_case_json(cast(str, self.rec)))
        self.assertEqual(use_case["statement"], "Help operations leads at growing agencies solve "
                                                "scattered client feedback with a "
                                                "feedback-to-task routing board.")

    def test_icp_cannot_be_a_pricing_tier(self) -> None:
        for icp in ("small teams on the Plus plan", "Enterprise tier customers", "teams"):
            with self.subTest(icp=icp), self.assertRaisesRegex(ValueError, "role or team"):
                self.state.set_use_case(use_case_json(cast(str, self.rec), icp))

    def test_core_problem_must_be_a_noun_phrase(self) -> None:
        for problem in ("Organizing team knowledge", "get feedback routed", "to track work"):
            value = use_case_json(cast(str, self.rec))
            cast(JsonObject, value["core_problem"])["text"] = problem
            with self.subTest(problem=problem), self.assertRaisesRegex(ValueError, "noun phrase"):
                self.state.set_use_case(value)

    def test_why_is_at_most_3_sentences(self) -> None:
        value = {**use_case_json(cast(str, self.rec)), "why": "One. Two. Three. Four."}
        with self.assertRaisesRegex(ValueError, "1 to 3 sentences"):
            self.state.set_use_case(value)

    def test_plan_and_briefs_wait_for_the_use_case(self) -> None:
        plan = plan_json(self.state.pack)
        with self.assertRaisesRegex(ValueError, "use case first"):
            self.state.add_action(cast(list[JsonObject], plan["actions"])[0])
        with self.assertRaisesRegex(ValueError, "use case first"):
            self.state.set_mvp_idea(cast(JsonObject, plan["mvp_idea"]))
        self.assertEqual(self.state.missing()[0], "use_case")

    def test_plan_needs_a_validate_action(self) -> None:
        self.state.set_use_case(use_case_json(cast(str, self.rec)))
        for action in cast(list[JsonObject], plan_json(self.state.pack)["actions"]):
            self.state.add_action({**action, "purpose": "deliver"})
        self.assertIn("validate the key assumption", " ".join(self.state.missing()))

    def test_result_carries_the_use_case(self) -> None:
        pack = load()
        result = PMAgent(FakeModel([plan_json(pack)])).run(pack)
        use_case = cast(JsonObject, result["use_case"])
        self.assertTrue(cast(str, use_case["statement"]).startswith("Help "))
        self.assertEqual(result["status"], "complete")


class CliTests(unittest.TestCase):
    def test_cli_writes_result_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "incomplete-gtm.json"
            source.write_text(json.dumps(incomplete(load())), encoding="utf-8")
            output = Path(directory) / "out.json"
            pack = incomplete(load())
            with patch.object(cli, "AnthropicModel", return_value=FakeModel([plan_json(pack)])):
                waiting = cli.main([str(source), "--output", str(output), "--no-deepagents"])
                self.assertEqual(json.loads(output.read_text())["status"], "hitl_required")
                planned = cli.main([str(source), "--output", str(output), "--no-deepagents",
                                    "--decision", "proceed"])
                result = json.loads(output.read_text())
        self.assertEqual((waiting, planned), (3, 0))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["decision"], "proceed")


if __name__ == "__main__":
    unittest.main()
