"""Chat flow, FastAPI endpoints, and UI rendering, with provider doubles. No live calls."""

import sys
import unittest
from pathlib import Path

from doubles import FULL_ITEMS, FULL_ROUTES, FakeSearch, WorldModel, page
from research import Limits, MemoryStore, ResearchAgent

try:
    from fastapi.testclient import TestClient

    from research.api import create_app
except ImportError:  # the api and test extras are optional
    TestClient = None  # type: ignore[assignment,misc]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UI"))
from render import esc, pack_markdown  # noqa: E402

AMBIGUOUS = {"official website": [page("https://acmecloud.com/", "Acme Cloud", "Docs tool"),
                                  page("https://acmecloud.io/", "Acme Cloud Hosting", "Hosting")],
             **FULL_ROUTES}
RESOLVE = {"status": "ambiguous", "candidates": [
    {"name": "Acme Cloud", "website": "https://acmecloud.com", "reason": "documents"},
    {"name": "Acme Cloud Hosting", "website": "https://acmecloud.io", "reason": "hosting"}]}


@unittest.skipIf(TestClient is None, "install the api and test extras")
class ApiChat(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()

    def client(self, routes=None, limits=None) -> "TestClient":  # type: ignore[no-untyped-def]
        agent = ResearchAgent(WorldModel(FULL_ITEMS, resolve=RESOLVE),
                              FakeSearch(routes or FULL_ROUTES), self.store, limits=limits)
        client = TestClient(create_app(agent, self.store, run_inline=True))
        self.session = client.post("/api/sessions").json()["session_id"]
        return client

    def send(self, client: "TestClient", message: str) -> dict:
        job_id = client.post(f"/api/sessions/{self.session}/messages",
                             json={"message": message}).json()["job_id"]
        job = client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "done", job)
        return job

    def test_website_message_returns_pack_and_events(self) -> None:
        client = self.client()
        job = self.send(client, "acmecloud.com")
        self.assertEqual(job["reply"]["kind"], "pack")
        self.assertEqual(job["reply"]["pack"]["status"], "complete")
        self.assertIn("plan", [e["step"] for e in job["events"]])
        runs = client.get("/api/runs").json()["runs"]
        self.assertEqual(runs[0]["status"], "complete")
        detail = client.get(f"/api/runs/{runs[0]['id']}").json()
        self.assertEqual(detail["pack"]["run_id"], runs[0]["id"])
        trail = client.get(f"/api/runs/{runs[0]['id']}/rounds").json()
        self.assertEqual(trail["rounds"][1]["coverage"]["company"]["status"], "complete")
        self.assertTrue(trail["sources"])

    def test_follow_up_question_then_answer(self) -> None:
        client = self.client(AMBIGUOUS)
        first = self.send(client, "Acme Cloud")["reply"]
        self.assertEqual(first["kind"], "clarify")
        self.assertIn("1. Acme Cloud: https://acmecloud.com/", first["message"])
        second = self.send(client, "1")["reply"]
        self.assertEqual(second["kind"], "pack")
        self.assertEqual(second["pack"]["company"]["website"], "https://acmecloud.com/")
        history = client.get(f"/api/sessions/{self.session}").json()["history"]
        self.assertEqual([h["role"] for h in history], ["user", "assistant"] * 2)

    def test_misspelled_name_then_pick_website(self) -> None:
        routes = {"official website": [page("https://acmecloud.com/", "Acme Cloud", "home")],
                  **FULL_ROUTES}
        agent = ResearchAgent(WorldModel(FULL_ITEMS, resolve={"corrected_name": "Acme Cloud",
                                                              "candidates": [{"name": "Acme Cloud",
                                                                              "website": "https://acmecloud.com"}]}),
                              FakeSearch(routes), self.store)
        client = TestClient(create_app(agent, self.store, run_inline=True))
        self.session = client.post("/api/sessions").json()["session_id"]
        first = self.send(client, "Research Acme Clowd for me")["reply"]
        self.assertEqual(first["kind"], "clarify")
        self.assertIn("Did you mean Acme Cloud?", first["message"])
        self.assertIn("1. Acme Cloud: https://acmecloud.com/", first["message"])
        pack = self.send(client, "1")["reply"]["pack"]
        self.assertEqual((pack["company"]["name"], pack["status"]), ("Acme Cloud", "complete"))
        self.assertIn("corrected from Acme Clowd to Acme Cloud", pack["uncertainties"][0])

    def test_partial_pack_offers_rerun(self) -> None:
        client = self.client(limits=Limits(rounds=2))
        first = self.send(client, "acmecloud.com")["reply"]
        self.assertIn("Reply yes", first["message"])
        second = self.send(client, "yes")["reply"]
        self.assertEqual(second["pack"]["parent_run_id"], first["run_id"])
        self.assertEqual(second["pack"]["status"], "complete")

    def test_unknown_ids_and_bad_input(self) -> None:
        client = self.client()
        self.assertEqual(client.get("/api/runs/not-a-uuid").status_code, 404)
        self.assertEqual(client.get("/api/jobs/x").status_code, 404)
        self.assertEqual(client.post("/api/sessions/x/messages", json={"message": "a"}).status_code, 404)
        self.assertEqual(client.post(f"/api/sessions/{self.session}/messages",
                                     json={"message": ""}).status_code, 422)


class ChatParsing(unittest.TestCase):
    def test_request_phrasing_is_stripped(self) -> None:
        from research.chat import company_from_message

        for text, expected in (("Research Linear company", "Linear"), ("Linear", "Linear"),
                               ("Can you research linear.app?", "linear.app"),
                               ("tell me about Acme Cloud Inc.", "Acme Cloud Inc"),
                               ("find info about the Mercury startup", "Mercury"),
                               ("Research Baseteen for me", "Baseteen"),
                               ("Research", "Research")):
            self.assertEqual(company_from_message(text), expected, text)

    def test_unconfirmed_website_still_offers_options(self) -> None:
        routes = {"official website": [page("https://linear.app/", "Linear: plan and build", "x"),
                                       page("https://linear.app/pricing", "Pricing", "x"),
                                       page("https://en.wikipedia.org/wiki/Linear", "Linear", "x")]}
        agent = ResearchAgent(WorldModel(resolve={"status": "not_found", "candidates": []}),
                              FakeSearch(routes), MemoryStore())
        result = agent.run("Linear")
        self.assertEqual(result.status, "clarify")
        self.assertEqual([c["website"] for c in result.candidates],
                         ["https://linear.app/", "https://en.wikipedia.org/"])

    def test_candidate_website_without_scheme(self) -> None:
        routes = {"official website": [page("https://www.linear.app/", "Linear", "x")]}
        agent = ResearchAgent(WorldModel(resolve={"corrected_name": "Linear", "candidates": [
            {"name": "Linear", "website": "linear.app", "reason": "home"}]}),
            FakeSearch(routes), MemoryStore())
        result = agent.run("Linear")
        self.assertEqual(result.candidates[0]["website"], "https://linear.app/")


class Rendering(unittest.TestCase):
    def test_pack_markdown_escapes_and_links(self) -> None:
        store = MemoryStore()
        agent = ResearchAgent(WorldModel(FULL_ITEMS), FakeSearch(FULL_ROUTES), store)
        pack = agent.run("Acme Cloud", "acmecloud.com").pack
        text = pack_markdown(pack)  # type: ignore[arg-type]
        self.assertIn("Beta Docs", text)
        self.assertIn("(https://techcrunch.com/acme-cloud-market)", text)
        self.assertEqual(esc("[x](javascript:alert)"), "\\[x\\]\\(javascript:alert\\)")


if __name__ == "__main__":
    unittest.main()
