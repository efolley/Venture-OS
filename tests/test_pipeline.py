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
from pipeline.runner import run_pipeline, slug
from research import MemoryStore, ResearchAgent
from research.contracts import JsonObject
from test_gtm import FakeModel


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
                               "--output-dir", directory])
            research = json.loads((Path(directory) / "acme-cloud-research.json").read_text())
            strategy = json.loads((Path(directory) / "acme-cloud-gtm.json").read_text())
        self.assertEqual(status, 0)
        self.assertEqual(strategy["input_run_id"], research["run_id"])
        self.assertIn("snapshot", strategy)


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
                                            run_inline=True, results_dir=self.results))

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

    def test_gtm_needs_a_known_run_with_a_pack(self) -> None:
        missing = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.client.post("/api/gtm/runs",
                                          json={"research_run_id": missing}).status_code, 409)
        self.assertEqual(self.client.post("/api/gtm/runs",
                                          json={"research_run_id": "not-a-uuid"}).status_code, 404)
        self.assertEqual(self.client.get("/api/gtm/jobs/nope").status_code, 404)


class StrategyRenderTests(unittest.TestCase):
    def test_strategy_renders_escaped_snapshot_and_ranked_hypotheses(self) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UI"))
        from render import competitive_markdown, snapshot_markdown

        pack = research_agent().run("Acme Cloud", "acmecloud.com").pack
        strategy = cast(JsonObject, dict(GTMOrchestrator(FakeModel()).run(dict(cast(dict, pack)))))
        strategy["snapshot"]["company"]["name"] = "Acme *Cloud*"  # type: ignore[index]
        text = snapshot_markdown(strategy)
        self.assertIn("Acme \\*Cloud\\*", text)
        self.assertIn("Mission:", text)
        self.assertIn("| 1 | 12/20 |", competitive_markdown(strategy))


if __name__ == "__main__":
    unittest.main()
