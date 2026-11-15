import json
import tempfile
import unittest
from pathlib import Path
from threading import Barrier, BrokenBarrierError
from typing import cast
from unittest.mock import patch

from gtm import cli
from gtm.contracts import SUB_AGENTS, validate_sub_agent_result
from gtm.merge import MERGE_SYSTEM, merge_outputs
from gtm.snapshot import REQUIRED_LINES, SNAPSHOT_SYSTEM, build_snapshot
from gtm.inputs import evidence_id_index, load_research_pack, validate_research_pack
from gtm.orchestrator import GTMOrchestrator
from research.contracts import JsonObject


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = tuple(ROOT / "data" / f"{name}.json" for name in ("notion", "baseten", "linear"))


def partial_pack() -> JsonObject:
    """A copy of the Notion sample with its market trends removed, so Research is partial."""
    pack = load_research_pack(SAMPLES[0])
    cast(dict[str, list[str]], pack["market"])["trends"] = []
    coverage = cast(dict[str, JsonObject], pack["coverage"])
    coverage["market"] = {"status": "partial", "missing": ["market.trends"]}
    pack["status"] = "partial"
    return validate_research_pack(pack)


class FakeModel:
    def __init__(
        self,
        *,
        fail_agent: str = "",
        invalid_citations: bool = False,
        invalid_first_attempt: bool = False,
        with_gaps: bool = False,
        empty_agent: str = "",
        merge_reply: object = None,
        snapshot_reply: object = None,
        barrier: Barrier | None = None,
    ) -> None:
        self.with_gaps = with_gaps
        self.empty_agent = empty_agent
        self.systems: list[str] = []
        self.merge_reply = merge_reply
        self.merge_requests: list[JsonObject] = []
        self.snapshot_reply = snapshot_reply
        self.snapshot_requests: list[JsonObject] = []
        self.fail_agent = fail_agent
        self.invalid_citations = invalid_citations
        self.invalid_first_attempt = invalid_first_attempt
        self.barrier = barrier
        self.prompts: list[JsonObject] = []

    def json(self, system: str, prompt: str) -> JsonObject:
        if system == SNAPSHOT_SYSTEM:
            request = cast(JsonObject, json.loads(prompt))
            self.snapshot_requests.append(request)
            if self.snapshot_reply is not None:
                return cast(JsonObject, self.snapshot_reply)
            lines: JsonObject = {}
            for key, spec in cast(dict[str, JsonObject], request["lines"]).items():
                evidence = cast(list[JsonObject], spec["allowed_evidence"])
                recs = cast(list[JsonObject], spec["allowed_recommendations"])
                lines[key] = {
                    "status": "found",
                    "text": f"Test {key} line.",
                    "basis": "evidence_based",
                    "evidence_ids": [evidence[0]["id"]] if evidence else [],
                    "recommendation_ids": [] if evidence else [recs[0]["id"]],
                }
            return {"lines": lines}
        if system == MERGE_SYSTEM:
            request = cast(JsonObject, json.loads(prompt))
            self.merge_requests.append(request)
            if self.merge_reply is not None:
                return cast(JsonObject, self.merge_reply)
            return {
                "themes": [
                    {"title": item["title"], "recommendation_ids": [item["id"]]}
                    for item in cast(list[JsonObject], request["recommendations"])
                ],
                "gap_groups": [
                    {"gap_ids": [item["id"]], "keep": item["id"]}
                    for item in cast(list[JsonObject], request["gaps"])
                ],
            }
        if self.fail_agent and self.fail_agent in system:
            raise RuntimeError(f"{self.fail_agent} test failure")
        if self.barrier is not None:
            try:
                self.barrier.wait(timeout=3)
            except BrokenBarrierError as error:
                raise AssertionError("Sub-agent calls did not run concurrently.") from error
        payload = cast(JsonObject, json.loads(prompt))
        self.prompts.append(payload)
        self.systems.append(system)
        if self.empty_agent and self.empty_agent in system:
            return {"recommendations": [], "gaps": ["Not enough evidence."]}
        available = cast(list[str], payload["available_evidence_ids"])
        if not available:
            return {"recommendations": [], "gaps": ["No role-relevant evidence."]}
        first_attempt = "validation_error" not in payload
        invalid = self.invalid_citations or (self.invalid_first_attempt and first_attempt)
        cited = ["not-a-real-id"] if invalid else [available[0]]
        recommendation: JsonObject = {
            "title": "Test recommendation",
            "recommendation": "Test this segment before scaling.",
            "rationale": "The provided evidence identifies the relevant context.",
            "basis": "hypothesis",
            "evidence_ids": cited,
        }
        if "Competitive Strategy" in system:
            recommendation.update(hypothesis_fields(3, 3))
        gaps = ["No win/loss data."] if self.with_gaps else []
        return {"recommendations": [recommendation], "gaps": gaps}


def hypothesis_fields(pain: int, fit: int) -> JsonObject:
    return {
        "sub_scores": {"pain": pain, "gap_size": 3, "competitor_weakness": 3, "fit": fit},
        "disconfirming_evidence": "No customer interviews yet.",
        "validation_question": "Who owns this problem today?",
    }


def hypothesis(title: str, pain: int, fit: int, evidence_ids: list[str]) -> JsonObject:
    return {
        "title": title,
        "recommendation": f"{title} opportunity.",
        "rationale": "Alternatives leave this gap.",
        "basis": "hypothesis",
        "evidence_ids": evidence_ids,
        **hypothesis_fields(pain, fit),
    }


class GTMInputTests(unittest.TestCase):
    def test_sample_packs_validate_and_have_evidence_indexes(self):
        for path in SAMPLES:
            with self.subTest(sample=path.name):
                pack = load_research_pack(path)
                index = evidence_id_index(pack)
                self.assertEqual(pack["schema_version"], 4)
                self.assertTrue(index)
                self.assertEqual(len(index), len(cast(list[object], pack["evidence"])))

    def test_invalid_research_pack_is_rejected(self):
        pack = load_research_pack(SAMPLES[0])
        pack["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema_version"):
            validate_research_pack(pack)


class GTMContractTests(unittest.TestCase):
    def test_sub_agent_rejects_unknown_evidence_citation(self):
        result: JsonObject = {
            "recommendations": [{
                "title": "Unsupported",
                "recommendation": "Do something.",
                "rationale": "No valid source.",
                "basis": "hypothesis",
                "evidence_ids": ["unknown"],
            }],
        }
        with self.assertRaisesRegex(ValueError, "unknown evidence IDs"):
            validate_sub_agent_result(
                "market_analysis",
                result,
                {"e1"},
            )

    def test_recommendation_requires_at_least_one_citation(self):
        result: JsonObject = {
            "recommendations": [{
                "title": "No source",
                "recommendation": "Do something.",
                "rationale": "No source was cited.",
                "basis": "hypothesis",
                "evidence_ids": [],
            }],
        }
        with self.assertRaisesRegex(ValueError, "must cite evidence IDs"):
            validate_sub_agent_result(
                "challenger_salesman",
                result,
                {"e1"},
            )


class GTMRankingTests(unittest.TestCase):
    def test_code_ranks_hypotheses_and_ignores_model_score_and_rank(self):
        low = {**hypothesis("Low", 2, 2, ["e1"]), "score": 99, "rank": 1}
        high = hypothesis("High", 4, 5, ["e1"])
        result = validate_sub_agent_result(
            "competitive_strategy",
            {"recommendations": [low, high], "gaps": []},
            {"e1"},
        )
        ranked = result["recommendations"]
        self.assertEqual([item["title"] for item in ranked], ["High", "Low"])
        self.assertEqual([item.get("rank") for item in ranked], [1, 2])
        self.assertEqual([item.get("score") for item in ranked], [15, 10])

    def test_ties_break_by_pain_then_evidence_count(self):
        # All 3 score 12: (4+3+3+2), (3+3+3+3) and (3+3+3+3) with more evidence.
        a = hypothesis("Fewer sources", 3, 3, ["e1"])
        b = hypothesis("More sources", 3, 3, ["e1", "e2"])
        c = hypothesis("Most pain", 4, 2, ["e1"])
        result = validate_sub_agent_result(
            "competitive_strategy",
            {"recommendations": [a, b, c]},
            {"e1", "e2"},
        )
        self.assertEqual(
            [item["title"] for item in result["recommendations"]],
            ["Most pain", "More sources", "Fewer sources"],
        )

    def test_hypothesis_needs_valid_sub_scores_and_validation_fields(self):
        bad_scores = hypothesis("Bad", 3, 3, ["e1"])
        bad_scores["sub_scores"] = {"pain": 6, "gap_size": 3, "competitor_weakness": 3, "fit": 3}
        missing_question = hypothesis("Missing", 3, 3, ["e1"])
        del missing_question["validation_question"]
        for item, message in ((bad_scores, "integers 1 to 5"), (missing_question, "validation_question")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_sub_agent_result(
                    "competitive_strategy",
                    {"recommendations": [item]},
                    {"e1"},
                )


class GTMMergeTests(unittest.TestCase):
    RECS: list[dict[str, object]] = [
        {"id": "r1", "agent": "market_analysis", "title": "Self-hosted", "recommendation": "A"},
        {"id": "r2", "agent": "challenger_salesman", "title": "VPC track", "recommendation": "B"},
        {"id": "r3", "agent": "competitive_strategy", "title": "Pricing", "recommendation": "C"},
    ]
    GAPS = [
        ("market_analysis", "No win/loss data."),
        ("challenger_salesman", "No win or loss evidence."),
        ("competitive_strategy", "No Enterprise pricing."),
    ]

    def test_overlapping_items_are_grouped_without_rewriting(self):
        reply = {
            "themes": [
                {"title": "Self-hosted deployment", "recommendation_ids": ["r1", "r2"]},
                {"title": "Pricing", "recommendation_ids": ["r3"]},
            ],
            "gap_groups": [
                {"gap_ids": ["g1", "g2"], "keep": "g1"},
                {"gap_ids": ["g3"], "keep": "g3"},
            ],
        }
        result = merge_outputs(FakeModel(merge_reply=reply), self.RECS, self.GAPS)
        self.assertEqual(result["status"], "merged")
        self.assertEqual(result["themes"][0]["agents"], ["challenger_salesman", "market_analysis"])
        self.assertEqual(result["gaps"], [
            "challenger_salesman, market_analysis: No win/loss data.",
            "competitive_strategy: No Enterprise pricing.",
        ])

    def test_invalid_grouping_retries_once_then_falls_back(self):
        reply = {"themes": [{"title": "Missing r3", "recommendation_ids": ["r1", "r2"]}],
                 "gap_groups": []}
        model = FakeModel(merge_reply=reply)
        result = merge_outputs(model, self.RECS, self.GAPS + [("market_analysis", "No win/loss data.")])
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(len(model.merge_requests), 2)
        self.assertIn("validation_error", model.merge_requests[1])
        self.assertEqual(len(result["themes"]), 3)
        self.assertEqual(len(result["gaps"]), 3)
        self.assertIn("exactly 1 theme", result["error"])

    def test_research_gtm_gaps_already_in_coverage_are_not_repeated(self):
        result = GTMOrchestrator(FakeModel()).run(partial_pack())
        self.assertTrue(result["research_gaps"])
        gtm_lines = [gap for gap in result["research_gaps"] if gap.startswith("Research GTM gap")]
        coverage = [gap for gap in result["research_gaps"] if gap.startswith("Research coverage")]
        for line in gtm_lines:
            field = line.removeprefix("Research GTM gap: ").split()[0]
            self.assertFalse(any(field in item for item in coverage), line)


class GTMSnapshotTests(unittest.TestCase):
    def test_snapshot_lines_cite_only_their_allowed_sources(self):
        pack = load_research_pack(SAMPLES[0])
        result = GTMOrchestrator(FakeModel()).run(pack)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["company"]["name"], "Notion")
        lines = cast(dict[str, JsonObject], snapshot["lines"])
        company = cast(dict[str, list[str]], pack["company"])
        self.assertTrue(set(cast(list[str], lines["mission"]["evidence_ids"])) <= set(company["mission"]))
        self.assertTrue(set(cast(list[str], lines["problem"]["evidence_ids"])) <= set(company["problem"]))
        self.assertTrue(set(cast(list[str], lines["product"]["evidence_ids"])) <= set(company["offering"]))
        for key in REQUIRED_LINES:
            self.assertEqual(lines[key]["status"], "found", key)

    def test_line_without_evidence_is_unknown_and_never_asked(self):
        pack = load_research_pack(SAMPLES[0])
        company = cast(dict[str, list[str]], pack["company"])
        company["mission"] = []
        model = FakeModel()
        snapshot = build_snapshot(model, pack, [])
        self.assertNotIn("mission", cast(JsonObject, model.snapshot_requests[0]["lines"]))
        self.assertEqual(cast(dict[str, JsonObject], snapshot["lines"])["mission"]["status"], "unknown")
        self.assertEqual(snapshot["status"], "partial")
        self.assertIn("mission", snapshot["missing"])

    def test_missing_vision_does_not_make_snapshot_partial(self):
        pack = load_research_pack(SAMPLES[0])
        cast(dict[str, list[str]], pack["company"])["vision"] = []
        result = GTMOrchestrator(FakeModel()).run(pack)
        self.assertEqual(result["snapshot"]["status"], "complete")
        self.assertNotIn("vision", result["snapshot"]["missing"])

    def test_one_bad_line_is_retried_alone_and_good_lines_are_kept(self):
        pack = load_research_pack(SAMPLES[0])
        company = cast(dict[str, list[str]], pack["company"])
        calls: list[JsonObject] = []

        class OneBadLine(FakeModel):
            def json(self, system: str, prompt: str) -> JsonObject:
                answer = super().json(system, prompt)
                if system == SNAPSHOT_SYSTEM:
                    calls.append(cast(JsonObject, json.loads(prompt)))
                    mission = cast(dict[str, JsonObject], answer["lines"]).get("mission")
                    if mission is not None:
                        mission["text"] = "x" * 400  # longer than the 250-character limit
                return answer

        snapshot = build_snapshot(OneBadLine(), pack, [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(cast(JsonObject, calls[1]["lines"])), ["mission"])
        self.assertIn("mission", cast(JsonObject, calls[1]["validation_errors"]))
        lines = cast(dict[str, JsonObject], snapshot["lines"])
        self.assertEqual(lines["mission"]["status"], "unknown")
        self.assertEqual(lines["problem"]["status"], "found")
        self.assertEqual(lines["problem"]["evidence_ids"], company["problem"][:1])
        self.assertEqual(snapshot["status"], "partial")
        self.assertIn("longer than 250", cast(dict[str, str], snapshot["line_errors"])["mission"])

    def test_over_long_line_is_trimmed_to_whole_sentences(self):
        pack = load_research_pack(SAMPLES[0])
        sentence = "Competitor A charges less and targets small teams. "

        class LongLandscape(FakeModel):
            def json(self, system: str, prompt: str) -> JsonObject:
                answer = super().json(system, prompt)
                if system == SNAPSHOT_SYSTEM:
                    line = cast(dict[str, JsonObject], answer["lines"])["competitive_landscape"]
                    line["text"] = sentence * 20  # about 1,000 characters
                return answer

        snapshot = build_snapshot(LongLandscape(), pack, [])
        line = cast(dict[str, JsonObject], snapshot["lines"])["competitive_landscape"]
        self.assertEqual(line["status"], "found")
        self.assertLessEqual(len(cast(str, line["text"])), 700)
        self.assertTrue(cast(str, line["text"]).endswith("small teams."))
        self.assertNotIn("competitive_landscape", snapshot["line_errors"])

    def test_unusable_response_twice_falls_back(self):
        model = FakeModel(snapshot_reply=["not", "an", "object"])
        result = GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        snapshot = result["snapshot"]
        self.assertEqual(len(model.snapshot_requests), 2)
        self.assertIn("validation_error", model.snapshot_requests[1])
        self.assertEqual(snapshot["status"], "fallback")
        self.assertTrue(all(
            line["status"] == "unknown" for line in cast(dict[str, JsonObject], snapshot["lines"]).values()
        ))
        self.assertEqual(result["status"], "partial")


class GTMOrchestratorTests(unittest.TestCase):
    def test_complete_and_partial_inputs_merge_three_cited_results(self):
        cases = [(path.name, load_research_pack(path), "complete") for path in SAMPLES]
        cases.append(("notion, partial", partial_pack(), "partial"))
        for label, pack, expected_status in cases:
            with self.subTest(sample=label):
                result = GTMOrchestrator(FakeModel()).run(pack)
                available = set(evidence_id_index(pack))
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(set(result["sub_agents"]), set(SUB_AGENTS))
                self.assertEqual(len(result["recommendations"]), 3)
                self.assertEqual(result["merge"]["status"], "merged")
                self.assertEqual(
                    sorted(i for theme in result["themes"] for i in theme["recommendation_ids"]),
                    sorted(item["id"] for item in result["recommendations"]),
                )
                ranked = [
                    item for item in result["recommendations"]
                    if item["agent"] == "competitive_strategy"
                ]
                self.assertEqual([(item["rank"], item["score"]) for item in ranked], [(1, 12)])
                self.assertTrue(all(
                    set(cast(list[str], recommendation["evidence_ids"])) <= available
                    for recommendation in result["recommendations"]
                ))
                if expected_status == "partial":
                    self.assertTrue(result["research_gaps"])
                    self.assertTrue(result["gaps"])

    def test_all_sub_agents_are_called_concurrently(self):
        model = FakeModel(barrier=Barrier(len(SUB_AGENTS)))
        result = GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(model.prompts), len(SUB_AGENTS))

    def test_failed_sub_agent_is_reported_with_partial_strategy(self):
        model = FakeModel(fail_agent="Market Analysis")
        result = GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(result["status"], "partial")
        market = result["sub_agents"]["market_analysis"]
        self.assertEqual(market["status"], "failed")
        if market["status"] != "failed":
            self.fail("Market analysis failure result was not marked failed.")
        self.assertIn("RuntimeError", market["error"])
        self.assertEqual(len(result["recommendations"]), 2)

    def test_invalid_model_citations_fail_the_sub_agents_not_the_run(self):
        result = GTMOrchestrator(FakeModel(invalid_citations=True)).run(
            load_research_pack(SAMPLES[0])
        )
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all(
            result["sub_agents"][name]["status"] == "failed"
            for name in SUB_AGENTS
        ))
        for name in SUB_AGENTS:
            sub_agent = result["sub_agents"][name]
            if sub_agent["status"] != "failed":
                self.fail(f"{name} result was not marked failed.")
            self.assertIn("unknown evidence IDs", sub_agent["error"])

    def test_invalid_output_is_corrected_by_one_retry(self):
        model = FakeModel(invalid_first_attempt=True)
        result = GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(result["status"], "complete")
        self.assertTrue(all(
            result["sub_agents"][name]["status"] == "complete" for name in SUB_AGENTS
        ))
        self.assertEqual(len(model.prompts), 2 * len(SUB_AGENTS))
        retries = [prompt for prompt in model.prompts if "validation_error" in prompt]
        self.assertEqual(len(retries), len(SUB_AGENTS))
        for retry in retries:
            self.assertIn("unknown evidence IDs", cast(str, retry["validation_error"]))
            self.assertIn("previous_output", retry)

    def test_sub_agent_gaps_are_reported_but_do_not_force_partial(self):
        result = GTMOrchestrator(FakeModel(with_gaps=True)).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["gaps"]), len(SUB_AGENTS))

    def test_sub_agent_with_no_recommendations_makes_strategy_partial(self):
        model = FakeModel(empty_agent="Challenger Salesman")
        result = GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sub_agents"]["challenger_salesman"]["status"], "complete")

    def test_every_sub_agent_advises_the_researched_company(self):
        model = FakeModel()
        GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(len(model.systems), len(SUB_AGENTS))
        for system in model.systems:
            self.assertIn("consultant advising the researched company", system)
            self.assertIn("not for\na competitor or a new entrant", system)

    def test_retry_happens_only_once(self):
        model = FakeModel(invalid_citations=True)
        GTMOrchestrator(model).run(load_research_pack(SAMPLES[0]))
        self.assertEqual(len(model.prompts), 2 * len(SUB_AGENTS))

    def test_instructions_reach_every_sub_agent(self):
        model = FakeModel()
        GTMOrchestrator(model).run(
            load_research_pack(SAMPLES[0]),
            instructions="Focus on European B2B SaaS teams.",
        )
        self.assertEqual(
            [prompt["instructions"] for prompt in model.prompts],
            ["Focus on European B2B SaaS teams."] * len(SUB_AGENTS),
        )


class GTMCLITests(unittest.TestCase):
    def test_cli_writes_merged_strategy_json(self):
        model = FakeModel()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "notion-gtm.json"
            with patch.object(cli, "default_model", return_value=model):
                status = cli.main([str(SAMPLES[0]), "--output", str(output)])
            strategy = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertEqual(strategy["company"]["name"], "Notion")
        self.assertEqual(len(strategy["recommendations"]), 3)
        self.assertEqual(strategy["status"], "complete")


if __name__ == "__main__":
    unittest.main()
