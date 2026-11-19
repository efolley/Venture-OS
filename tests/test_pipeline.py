"""Offline tests for the pipeline: Research hands its evidence pack straight to GTM."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from doubles import FULL_ITEMS, FULL_ROUTES, FakeSearch, WorldModel, page
from gtm.orchestrator import GTMOrchestrator
from pipeline import __main__ as cli
from pipeline.report import report_markdown
from pipeline.runner import run_pipeline, slug
from research import MemoryStore, ResearchAgent
from research.contracts import JsonObject
from pm.agent import PMAgent
from test_gtm import FakeModel
from test_pm import FakeModel as FakePMModel


def research_agent(routes=None, model=None) -> ResearchAgent:  # type: ignore[no-untyped-def]
    return ResearchAgent(model or WorldModel(FULL_ITEMS),
                         FakeSearch(routes if routes is not None else FULL_ROUTES), MemoryStore())


class FailingGTM(GTMOrchestrator):
    def __init__(self) -> None:
        super().__init__(FakeModel())

    def run(self, value: object, *, instructions: str = ""):  # type: ignore[no-untyped-def]
        raise RuntimeError("model unavailable")


class PipelineTests(unittest.TestCase):
    def test_research_pack_flows_into_gtm_with_snapshot(self) -> None:
        gtm_model = FakeModel()
        events: list[tuple[str, str]] = []
        result = run_pipeline(
            research_agent(), GTMOrchestrator(gtm_model), "Acme Cloud", "acmecloud.com",
            instructions="EU only",
            progress=lambda step, data, status: events.append((step, status)),
        )
        self.assertEqual(result.research_status, "complete")
        self.assertIsNotNone(result.pack)
        strategy = cast(JsonObject, result.strategy)
        # GTM ran on exactly the pack Research produced, in memory.
        self.assertEqual(strategy["input_run_id"], result.research_run_id)
        self.assertEqual(cast(JsonObject, strategy["company"])["name"], "Acme Cloud")
        self.assertIn(cast(JsonObject, strategy["snapshot"])["status"], ("complete", "partial"))
        self.assertEqual(result.status, "complete" if strategy["status"] == "complete" else "partial")
        self.assertEqual({p["instructions"] for p in gtm_model.prompts}, {"EU only"})
        self.assertIn(("pipeline", "running"), events)

    def test_clarify_stops_before_gtm(self) -> None:
        routes = {"official website": [page("https://basecamp.com/", "Basecamp", "Project tool"),
                                       page("https://basecampoutdoor.com/", "Basecamp Outdoor", "Jobs")]}
        model = WorldModel(resolve={"status": "ambiguous", "candidates": [
            {"name": "Basecamp", "website": "https://basecamp.com", "reason": "software"},
            {"name": "Basecamp Outdoor", "website": "https://basecampoutdoor.com", "reason": "jobs"}]})
        gtm_model = FakeModel()
        result = run_pipeline(research_agent(routes, model), GTMOrchestrator(gtm_model), "Basecamp")
        self.assertEqual(result.status, "clarify")
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNone(result.strategy)
        self.assertEqual(gtm_model.prompts, [])

    def test_gtm_failure_keeps_the_evidence_pack(self) -> None:
        result = run_pipeline(research_agent(), FailingGTM(), "Acme Cloud", "acmecloud.com")
        self.assertEqual(result.status, "gtm_failed")
        self.assertIsNotNone(result.pack)
        self.assertIsNone(result.strategy)
        self.assertIn("model unavailable", result.message)

    def test_full_cycle_stops_at_hitl_1_when_pm_baseline_fails(self) -> None:
        pm_model = FakePMModel()
        result = run_pipeline(research_agent(), GTMOrchestrator(FakeModel()), "Acme Cloud",
                              "acmecloud.com", pm=PMAgent(pm_model))
        self.assertEqual(result.status, "hitl_required")
        self.assertIsNotNone(result.strategy)
        pm = cast(JsonObject, result.pm)
        self.assertEqual(pm["input_run_id"], result.research_run_id)
        self.assertIn("sales", cast(JsonObject, pm["baseline"])["missing"])
        self.assertEqual(pm_model.requests, [])  # no planning before the person decides

    def test_full_cycle_with_proceed_produces_the_use_case(self) -> None:
        result = run_pipeline(research_agent(), GTMOrchestrator(FakeModel()), "Acme Cloud",
                              "acmecloud.com", pm=PMAgent(FakePMModel()), decision="proceed")
        self.assertEqual(result.status, "partial")
        use_case = cast(JsonObject, cast(JsonObject, result.pm)["use_case"])
        self.assertTrue(cast(str, use_case["statement"]).startswith("Help "))

    def test_research_decision_returns_gaps_without_planning(self) -> None:
        result = run_pipeline(research_agent(), GTMOrchestrator(FakeModel()), "Acme Cloud",
                              "acmecloud.com", pm=PMAgent(FakePMModel()), decision="research")
        self.assertEqual(result.status, "research_requested")
        self.assertIsNotNone(cast(JsonObject, result.pm)["research_request"])

    def test_slug_makes_safe_file_names(self) -> None:
        self.assertEqual(slug("Baseten, Inc."), "baseten-inc")
        self.assertEqual(slug("  "), "company")

    def test_cli_writes_research_and_gtm_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cli, "default_model", return_value=FakeModel()), \
                patch.object(cli, "TavilySearch", return_value=FakeSearch(FULL_ROUTES)), \
                patch.object(cli, "default_store", return_value=MemoryStore()), \
                patch.object(cli, "ResearchAgent",
                             side_effect=lambda model, search, store: research_agent()):
            status = cli.main(["Acme Cloud", "--website", "acmecloud.com",
                               "--output-dir", directory, "--no-pm"])
            research = json.loads((Path(directory) / "acme-cloud-research.json").read_text())
            strategy = json.loads((Path(directory) / "acme-cloud-gtm.json").read_text())
        self.assertEqual(status, 0)
        self.assertEqual(strategy["input_run_id"], research["run_id"])
        self.assertIn("snapshot", strategy)

    def test_cli_runs_pm_and_reports_hitl_1(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cli, "default_model", return_value=FakeModel()), \
                patch.object(cli, "TavilySearch", return_value=FakeSearch(FULL_ROUTES)), \
                patch.object(cli, "default_store", return_value=MemoryStore()), \
                patch.object(cli, "default_pm", return_value=PMAgent(FakePMModel())), \
                patch.object(cli, "ResearchAgent",
                             side_effect=lambda model, search, store: research_agent()):
            waiting = cli.main(["Acme Cloud", "--website", "acmecloud.com",
                                "--output-dir", directory])
            pm = json.loads((Path(directory) / "acme-cloud-pm.json").read_text())
            planned = cli.main(["Acme Cloud", "--website", "acmecloud.com",
                                "--output-dir", directory, "--decision", "proceed"])
            plan = json.loads((Path(directory) / "acme-cloud-pm.json").read_text())
            report = (Path(directory) / "acme-cloud-report.md").read_text()
        self.assertEqual((waiting, planned), (5, 0))
        self.assertEqual(pm["status"], "hitl_required")
        self.assertTrue(plan["use_case"]["statement"].startswith("Help "))
        self.assertIn(plan["use_case"]["statement"], report)
        self.assertIn("## Action plan", report)
        self.assertIn("## Sources", report)


class ReportTests(unittest.TestCase):
    def test_report_resolves_cited_ids_and_keeps_tables_intact(self) -> None:
        research = {"company": {"name": "Acme"}, "status": "complete", "evidence": [
            {"id": "e1", "statement": "Acme sells A | B.", "excerpt": "We sell A | B.\nToday.",
             "basis": "fact", "url": "https://acme.com/about"}]}
        strategy = {"company": {"name": "Acme"}, "status": "complete", "gaps": [],
                    "recommendations": [{"id": "r1", "agent": "market_analysis", "title": "Focus",
                                         "recommendation": "Go upmarket.", "basis": "hypothesis",
                                         "evidence_ids": ["e1"]}],
                    "snapshot": {"lines": {"mission": {"status": "found", "text": "Make A.",
                                                       "basis": "evidence_based",
                                                       "evidence_ids": ["e1"]}}}}
        report = report_markdown(None, strategy, research)
        self.assertIn("# VentureOS report: Acme", report)
        self.assertIn("- **Mission:** Make A. `e1`", report)
        self.assertIn("- **Vision:** _unknown_", report)
        self.assertIn('| `e1` | Acme sells A \\| B. | "We sell A \\| B. Today." | '
                      "<https://acme.com/about> |", report)
        self.assertIn("| `r1` | Market analyst |", report)

    def test_report_shows_the_hitl_question(self) -> None:
        pm = {"company": {"name": "Acme"}, "status": "hitl_required",
              "baseline": {"missing": ["snapshot.mission"]},
              "hitl": {"question": "Research more or proceed?"}}
        report = report_markdown(pm)
        self.assertIn("Missing: snapshot.mission.", report)
        self.assertIn("**Question:** Research more or proceed?", report)

    def test_report_needs_a_result(self) -> None:
        with self.assertRaises(ValueError):
            report_markdown()


try:
    from fastapi.testclient import TestClient

    from pipeline.api import create_app
except ImportError:  # the api and test extras are optional
    TestClient = None  # type: ignore[assignment,misc]


@unittest.skipIf(TestClient is None, "install the api and test extras")
class PipelineApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.results = Path(self.tmp.name)
        self.store = MemoryStore()
        agent = ResearchAgent(WorldModel(FULL_ITEMS), FakeSearch(FULL_ROUTES), self.store)
        self.client = TestClient(create_app(agent, self.store, GTMOrchestrator(FakeModel()),
                                            PMAgent(FakePMModel()), run_inline=True,
                                            results_dir=self.results,
                                            pm_results_dir=self.results / "pm"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def research_run_id(self) -> str:
        session = self.client.post("/api/sessions").json()["session_id"]
        job_id = self.client.post(f"/api/sessions/{session}/messages",
                                  json={"message": "acmecloud.com"}).json()["job_id"]
        reply = self.client.get(f"/api/jobs/{job_id}").json()["reply"]
        self.assertEqual(reply["kind"], "pack")
        return reply["pack"]["run_id"]

    def test_research_endpoints_still_work(self) -> None:
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        run_id = self.research_run_id()
        self.assertEqual(self.client.get("/api/runs").json()["runs"][0]["id"], run_id)

    def test_gtm_runs_on_a_stored_pack_and_is_saved(self) -> None:
        run_id = self.research_run_id()
        self.assertIsNone(self.client.get(f"/api/gtm/runs/{run_id}").json()["strategy"])
        job_id = self.client.post("/api/gtm/runs", json={"research_run_id": run_id}).json()["job_id"]
        job = self.client.get(f"/api/gtm/jobs/{job_id}").json()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["strategy"]["input_run_id"], run_id)
        self.assertIn("snapshot", job["strategy"])
        saved = self.client.get(f"/api/gtm/runs/{run_id}").json()["strategy"]
        self.assertEqual(saved["input_run_id"], run_id)
        self.assertTrue((self.results / f"{run_id}.json").exists())

    def test_pm_runs_on_the_saved_strategy_with_hitl_decisions(self) -> None:
        run_id = self.research_run_id()
        no_gtm = self.client.post("/api/pm/runs", json={"research_run_id": run_id})
        self.assertEqual(no_gtm.status_code, 409)
        self.client.post("/api/gtm/runs", json={"research_run_id": run_id})
        first = self.client.post("/api/pm/runs", json={"research_run_id": run_id}).json()["job_id"]
        job = self.client.get(f"/api/pm/jobs/{first}").json()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["result"]["status"], "hitl_required")
        second = self.client.post("/api/pm/runs", json={"research_run_id": run_id,
                                                        "decision": "proceed"}).json()["job_id"]
        result = self.client.get(f"/api/pm/jobs/{second}").json()["result"]
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["use_case"]["statement"].startswith("Help "))
        saved = self.client.get(f"/api/pm/runs/{run_id}").json()["result"]
        self.assertEqual(saved["decision"], "proceed")
        self.assertTrue((self.results / "pm" / f"{run_id}.json").exists())

    def test_web_ui_is_served_next_to_the_api(self) -> None:
        static = self.results / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>VentureOS</title>")
        (static / "assets" / "app.js").write_text("console.log(1)")
        client = TestClient(create_app(ResearchAgent(WorldModel(FULL_ITEMS), FakeSearch(FULL_ROUTES), self.store),
                                       self.store, GTMOrchestrator(FakeModel()), run_inline=True,
                                       results_dir=self.results, static_dir=static))
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<title>VentureOS</title>", page.text)
        self.assertEqual(client.get("/assets/app.js").status_code, 200)
        self.assertEqual(client.get("/api/health").json()["status"], "ok")
        without = TestClient(create_app(ResearchAgent(WorldModel(FULL_ITEMS), FakeSearch(FULL_ROUTES), self.store),
                                        self.store, GTMOrchestrator(FakeModel()), static_dir=None))
        self.assertEqual(without.get("/").status_code, 404)

    def test_gtm_needs_a_known_run_with_a_pack(self) -> None:
        missing = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.client.post("/api/gtm/runs",
                                          json={"research_run_id": missing}).status_code, 409)
        self.assertEqual(self.client.post("/api/gtm/runs",
                                          json={"research_run_id": "not-a-uuid"}).status_code, 404)
        self.assertEqual(self.client.get("/api/gtm/jobs/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
