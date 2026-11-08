import json
import unittest
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import cast
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_intelligence import ResearchEngine
from web_intelligence.api import create_app
from web_intelligence.contracts import JsonObject, Report, SearchResult
from web_intelligence.providers import GeminiModel


GOLDEN = Path(__file__).parent / "agents_data" / "web_intelligence_golden_data.json"


class FakeModel:
    def __init__(self, report: Report) -> None:
        self.report = report

    def json(self, system: str, prompt: str) -> JsonObject:
        if "Classify a user message" in system:
            request = json.loads(prompt)
            if request["has_current_report"] and request["message"].startswith("Who"):
                return {"action": "follow_up"}
            return {"action": "research", "company": self.report["company"]["name"], "website": ""}
        if "Answer the user's follow-up" in system:
            return {
                "action": "answer",
                "answer": self.report["icp"]["buyer"],
                "sources": self.report["sources"],
            }
        return {"action": "report", "report": self.report}


class SearchRequestModel(FakeModel):
    def __init__(self, report: Report) -> None:
        super().__init__(report)
        self.report_calls = 0

    def json(self, system: str, prompt: str) -> JsonObject:
        if "You are a Web Intelligence analyst" in system:
            self.report_calls += 1
            if self.report_calls == 1:
                return {"action": "search", "query": "pricing and customers"}
        return super().json(system, prompt)


class FakeSearch:
    def __init__(self, sources: list[str]) -> None:
        website = sources[0].rstrip("/")
        self.sources = [*sources, f"{website}/company"]
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        return [
            {"url": url, "title": f"{query} source {index}", "text": f"Evidence text for {url}."}
            for index, url in enumerate(self.sources[:limit])
        ]


class BlockingSearch(FakeSearch):
    def __init__(self, sources: list[str]) -> None:
        super().__init__(sources)
        self.started = Event()
        self.release = Event()

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("Test search was not released.")
        return super().search(query, limit)


class OfficialWebsiteSearch(FakeSearch):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if query.startswith("site:stripe.example.com"):
            self.queries.append(query)
            return [{
                "url": "https://stripe.example.com/about",
                "title": "Stripe company information",
                "text": "Company profile and product information.",
            }]
        return super().search(query, limit)


def ignore_progress(
    module: str,
    input_data: object,
    output_data: object,
    status: str,
) -> None:
    del module, input_data, output_data, status


class GeminiProviderTests(unittest.TestCase):
    def test_native_gemini_json_request_uses_default_lite_model(self):
        response_body = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{"text": '{"action":"clarify","question":"Which company?"}'}]
                }
            }]
        }).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                del _args
                return None

            def read(self):
                return response_body

        model = GeminiModel(api_key="test-key")
        with patch("web_intelligence.providers.urlopen", return_value=FakeResponse()) as urlopen:
            result = model.json("system", "prompt")

        request = urlopen.call_args.args[0]
        self.assertEqual(model.model, "gemini-3.5-flash-lite")
        self.assertIn("/models/gemini-3.5-flash-lite:generateContent", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        payload = json.loads(request.data)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(result["action"], "clarify")

    def test_gemini_requires_an_api_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                GeminiModel(api_key="").json("system", "prompt")


class WebIntelligenceApiTests(unittest.TestCase):
    reports: list[Report]
    report: Report

    @classmethod
    def setUpClass(cls):
        cls.reports = cast(list[Report], json.loads(GOLDEN.read_text()))
        cls.report = cls.reports[0]

    def setUp(self):
        engine = ResearchEngine(FakeModel(self.report), FakeSearch(self.report["sources"]))
        self.client = TestClient(create_app(engine))

    def wait_for_job(self, job_id: str) -> JsonObject:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            response = self.client.get(f"/api/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            result = response.json()
            if result["status"] != "running":
                return result
            sleep(0.01)
        self.fail("Background job did not finish in time.")

    def test_research_report_progress_and_grounded_follow_up(self):
        session_id = self.client.post("/api/sessions").json()["session_id"]
        response = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"message": "Stripe"},
        )
        self.assertEqual(response.status_code, 202)
        first = self.wait_for_job(response.json()["job_id"])
        self.assertEqual(first["status"], "succeeded")
        first_result = cast(JsonObject, first["result"])
        self.assertEqual(first_result["report"], self.report)
        events = cast(list[JsonObject], first["events"])
        self.assertEqual(
            {event["module"] for event in events},
            {"understanding", "collecting", "analyzing", "validating", "complete"},
        )
        self.assertTrue(all("input" in event and "output" in event for event in events))
        analysis = next(event for event in events if event["module"] == "analyzing")
        analysis_input = cast(JsonObject, analysis["input"])
        sources = cast(list[JsonObject], analysis_input["sources"])
        self.assertEqual(len(sources), 3)
        self.assertTrue(all(isinstance(source.get("retrieved_at"), str) for source in sources))

        response = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"message": "Who is the buyer?"},
        )
        second = self.wait_for_job(response.json()["job_id"])
        self.assertEqual(second["status"], "succeeded")
        second_result = cast(JsonObject, second["result"])
        self.assertEqual(second_result["message"], self.report["icp"]["buyer"])
        self.assertEqual(second_result["citations"], self.report["sources"])
        history = self.client.get(f"/api/sessions/{session_id}").json()["history"]
        self.assertEqual(len(history), 2)

    def test_all_golden_reports_match_the_expected_output_shape(self):
        for expected in self.reports:
            with self.subTest(company=expected["company"]["name"]):
                engine = ResearchEngine(
                    FakeModel(expected),
                    FakeSearch(expected["sources"]),
                )
                result = engine.turn(expected["company"]["name"], {"history": []}, ignore_progress)
                self.assertEqual(result["report"], expected)

    def test_single_string_list_fields_are_normalized(self):
        report = json.loads(json.dumps(self.report))
        expected_pain_point = report["problem"]["pain_points"][0]
        expected_user = report["icp"]["users"][0]
        report["problem"]["pain_points"] = expected_pain_point
        report["icp"]["users"] = expected_user
        expected_website = report["company"]["website"].replace("https://", "https://www.", 1)
        report["company"]["website"] = expected_website.removeprefix("https://")
        engine = ResearchEngine(
            FakeModel(cast(Report, report)),
            FakeSearch(self.report["sources"]),
        )

        result = engine.turn("Stripe", {"history": []}, ignore_progress)

        accepted = cast(Report, result["report"])
        self.assertEqual(accepted["problem"]["pain_points"], [expected_pain_point])
        self.assertEqual(accepted["icp"]["users"], [expected_user])
        self.assertEqual(accepted["company"]["website"], expected_website)

    def test_missing_company_website_source_triggers_focused_search(self):
        report = json.loads(json.dumps(self.report))
        report["company"]["website"] = "https://stripe.example.com"
        search = OfficialWebsiteSearch(self.report["sources"])
        engine = ResearchEngine(FakeModel(cast(Report, report)), search)

        result = engine.turn("Stripe", {"history": []}, ignore_progress)

        self.assertEqual(result["kind"], "report")
        self.assertEqual(
            cast(Report, result["report"])["company"]["website"],
            "https://stripe.example.com",
        )
        self.assertTrue(any(query.startswith("site:stripe.example.com") for query in search.queries))

    def test_unknown_session_and_job_are_rejected(self):
        self.assertEqual(self.client.get("/api/sessions/missing").status_code, 404)
        session_id = self.client.post("/api/sessions").json()["session_id"]
        response = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"message": "Stripe"},
        )
        self.assertEqual(response.status_code, 202)
        # A completed job can be followed by another turn; session ownership is enforced.
        self.wait_for_job(response.json()["job_id"])
        self.assertEqual(self.client.get("/api/jobs/missing").status_code, 404)

    def test_react_search_request_runs_a_second_evidence_round(self):
        model = SearchRequestModel(self.report)
        search = FakeSearch(self.report["sources"])
        engine = ResearchEngine(model, search)
        events: list[JsonObject] = []
        result = engine.turn(
            "Stripe",
            {"history": []},
            lambda module, input_data, output_data, status:
                events.append({
                    "module": module,
                    "input": input_data,
                    "output": output_data,
                    "status": status,
                }),
        )
        self.assertEqual(result["kind"], "report")
        self.assertEqual(model.report_calls, 2)
        self.assertEqual(len(search.queries), 2)
        self.assertIn("pricing and customers", search.queries[1])

    def test_research_url_must_be_public_https(self):
        engine = ResearchEngine(FakeModel(self.report), FakeSearch(self.report["sources"]))
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            engine.turn("https://127.0.0.1/", {"history": []}, ignore_progress)

    def test_session_rejects_overlapping_research_jobs(self):
        search = BlockingSearch(self.report["sources"])
        client = TestClient(create_app(ResearchEngine(FakeModel(self.report), search)))
        session_id = client.post("/api/sessions").json()["session_id"]
        first = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"message": "Stripe"},
        )
        self.assertTrue(search.started.wait(timeout=1))
        second = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"message": "Datadog"},
        )
        search.release.set()
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.wait_for_job_with_client(client, first.json()["job_id"])["status"], "succeeded")

    def test_report_cannot_add_uncollected_sources(self):
        report = json.loads(json.dumps(self.report))
        report["sources"][0] = "https://unknown.example/"
        client = TestClient(create_app(
            ResearchEngine(FakeModel(report), FakeSearch(self.report["sources"]))
        ))
        session_id = client.post("/api/sessions").json()["session_id"]
        submitted = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"message": "Stripe"},
        )
        result = self.wait_for_job_with_client(client, submitted.json()["job_id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("collected source URLs", str(result["error"]))
        failed_events = cast(list[JsonObject], result["events"])
        failed_steps = [
            event for event in failed_events
            if event["module"] == "validating" and event["status"] == "failure"
        ]
        self.assertEqual(len(failed_steps), 1)

    @staticmethod
    def wait_for_job_with_client(client: TestClient, job_id: str) -> JsonObject:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            result = client.get(f"/api/jobs/{job_id}").json()
            if result["status"] != "running":
                return result
            sleep(0.01)
        raise AssertionError("Background job did not finish in time.")


if __name__ == "__main__":
    unittest.main()
