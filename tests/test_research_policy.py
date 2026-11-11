"""Input and output tests for the claim policy, plus an offline end-to-end run.

The pages are synthetic and shaped like a real Notion run that showed 6 problems:
stale facts, unused first-party pages, reused quotes, claims that go beyond their
quote, forum posts marked as fact, and a website rule that dropped news copies.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).parent))

from test_research import FakeModel, FakeSearch, ScriptedRunner, ignore_progress  # noqa: E402

from ventureos.research import ResearchEngine  # noqa: E402
from ventureos.research.contracts import JsonObject, SearchResult  # noqa: E402
from ventureos.research.engine import (  # noqa: E402
    _is_dated,
    _off_target_reason,
    _unsupported_entities,
)
from ventureos.research.render import brief_markdown, code_text  # noqa: E402
from ventureos.research.workspace import ResearchWorkspace  # noqa: E402


SITE = "https://www.notion.com"
JOBS = "https://jobs.example.net/notion-outdoor"
CRUNCHBASE = "https://www.crunchbase.com/organization/notion-labs"
PAGES: list[SearchResult] = [
    {"url": f"{SITE}/", "title": "Notion",
     "text": "Notion is the connected workspace where teams write, plan and organize work. "
             "Notion AI helps teams search, draft and summarize across their workspace."},
    {"url": f"{SITE}/pricing", "title": "Notion pricing",
     "text": "The Plus plan costs 10 dollars per seat per month when billed annually. "
             "The Business plan costs 20 dollars per seat per month when billed annually."},
    {"url": f"{SITE}/customers", "title": "Notion customers",
     "text": "Teams at Figma, Ramp and OpenAI use Notion to run their docs and projects."},
    {"url": "https://techcrunch.com/2020/04/01/notion-raise", "title": "Notion raises at a 2 billion dollar valuation",
     "published_at": "2020-04-01T00:00:00Z",
     "text": "Notion has raised 50 million dollars at a 2 billion dollar valuation. "
             "Notion pricing ranges from 5 to 25 dollars per user per month."},
    {"url": "https://finance.yahoo.example/notion-raise", "title": "Notion raises at a 2 billion dollar valuation",
     "published_at": "2020-04-01T00:00:00Z",
     "text": "Notion has raised 50 million dollars. Notion grew its user base quickly. "
             "Notion says demand came from remote teams."},
    {"url": "https://www.g2.com/products/notion/reviews", "title": "Notion reviews",
     "published_at": "2026-09-01",
     "text": "Reviewers say Notion competes with Airtable, Craft Agents and Reflect for small teams."},
    {"url": "https://promptarmor.example/notion-ai-leak", "title": "Notion AI data exfiltration",
     "published_at": "2026-10-01",
     "text": "PromptArmor reported that Notion AI could leak workspace data through a prompt injection. "
             "Notion fixed the issue after disclosure. Notion users should review shared pages."},
    {"url": "https://www.reddit.com/r/Notion/leak", "title": "Notion AI leak thread",
     "published_at": "2026-10-02",
     "text": "One user writes that the Notion AI leak was easy to reproduce in a shared workspace."},
    {"url": JOBS, "title": "Jobs - Notion Outdoor",
     "text": "Notion Outdoor lists open roles at mountain resorts and gear shops."},
    {"url": CRUNCHBASE, "title": "Notion Labs company profile",
     "text": "Notion Labs is a software company with an estimated 800 employees."},
]
REPORTS_URL = [p["url"] for p in PAGES]


class AllPagesSearch(FakeSearch):
    """Returns every page per query, so one search collects the whole run."""

    def search(self, query: str, limit: int = 5, *, include_domains: list[str] | None = None) -> list[SearchResult]:
        if include_domains:
            return super().search(query, limit, include_domains=include_domains)
        self.queries.append(query)
        self.calls.append((query, None))
        return [dict(page) for page in self.pages]  # type: ignore[misc]


def claim(url: str, category: str, text: str, quote: str, basis: str = "fact") -> JsonObject:
    return {"url": url, "category": category, "text": text, "quote": quote, "basis": basis}


G2 = "https://www.g2.com/products/notion/reviews"
TC = "https://techcrunch.com/2020/04/01/notion-raise"
CLAIMS: list[JsonObject] = [
    claim(f"{SITE}/", "product", "Notion describes itself as a connected workspace for writing and planning work.",
          "Notion is the connected workspace where teams write, plan and organize work."),
    claim(f"{SITE}/pricing", "pricing", "The company says the Plus plan costs 10 dollars per seat per month.",
          "The Plus plan costs 10 dollars per seat per month when billed annually."),
    claim(f"{SITE}/customers", "customers", "The company says teams at Figma, Ramp and OpenAI use Notion.",
          "Teams at Figma, Ramp and OpenAI use Notion to run their docs and projects."),
    claim(TC, "signals", "Notion raised 50 million dollars at a 2 billion dollar valuation.",
          "Notion has raised 50 million dollars at a 2 billion dollar valuation."),
    # rejected: pricing from a news article while the pricing page was collected
    claim(TC, "pricing", "Notion pricing ranges from 5 to 25 dollars per user per month.",
          "Notion pricing ranges from 5 to 25 dollars per user per month."),
    # rejected: reuses the signals quote for another category
    claim(TC, "market", "Investors value the workspace software market leader Notion highly.",
          "Notion has raised 50 million dollars at a 2 billion dollar valuation."),
    # rejected: names 2 competitors its quote does not contain
    claim(G2, "competitors", "Notion competes with Airtable, Craft Agents, Reflect, Coda and Smartsheet.",
          "Reviewers say Notion competes with Airtable, Craft Agents and Reflect for small teams."),
    claim(G2, "competitors", "Reviewers say Notion competes with Airtable, Craft Agents and Reflect.",
          "Reviewers say Notion competes with Airtable, Craft Agents and Reflect for small teams."),
    claim("https://promptarmor.example/notion-ai-leak", "risks",
          "PromptArmor reported that Notion AI could leak workspace data through prompt injection.",
          "PromptArmor reported that Notion AI could leak workspace data through a prompt injection."),
    claim("https://www.reddit.com/r/Notion/leak", "risks",
          "One forum user says the Notion AI leak was easy to reproduce.",
          "One user writes that the Notion AI leak was easy to reproduce in a shared workspace."),
]


def runner() -> ScriptedRunner:
    def build(workspace: ResearchWorkspace) -> list[JsonObject]:
        ids = {s["url"]: s["id"] for s in workspace.evidence}
        return [{"text": c["text"], "basis": c["basis"], "category": c["category"],
                 "source_id": ids[cast(str, c["url"])], "quote": c["quote"]} for c in CLAIMS]
    return ScriptedRunner(queries=("notion funding competitors risks",), claims=build)


class SourceFilterTests(unittest.TestCase):
    def test_off_target_rule_by_source_kind(self):
        cases = [
            # (kind, title, text, expected reason)
            ("news", "Notion raises", "Notion raised money.", None),
            ("other", "Notion raises", "Notion raised. Notion grew. Notion hired.", None),
            ("other", "Jobs - Notion Outdoor", "Notion Outdoor lists roles.", "does not mention the company website"),
            ("aggregator", "Notion Labs", "Notion Labs profile. Notion. Notion.", "does not mention the company website"),
            ("aggregator", "Notion", "Official site notion.com.", None),
            ("news", "Figma raises", "Figma raised money.", "does not mention the company"),
        ]
        for kind, title, text, expected in cases:
            with self.subTest(kind=kind, title=title):
                self.assertEqual(_off_target_reason(kind, title, text, "Notion", "notion.com"), expected)


class ClaimPolicyUnitTests(unittest.TestCase):
    def test_unsupported_entities(self):
        quote = "Reviewers say Notion competes with Airtable, Craft Agents and Reflect."
        self.assertEqual(_unsupported_entities("Notion competes with Airtable and Coda.", quote, "Notion"), ["Coda"])
        self.assertEqual(_unsupported_entities("Reviewers name Airtable and Reflect.", quote, "Notion"), [])
        self.assertEqual(_unsupported_entities("It has 4,000 users.", "It serves 4000 teams.", "Notion"), [])
        self.assertEqual(_unsupported_entities("It has 5,000 users.", "It serves 4000 teams.", "Notion"), ["5,000"])

    def test_dated_after_12_months(self):
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertTrue(_is_dated("2020-04-01T00:00:00Z", now))
        self.assertFalse(_is_dated("2026-09-01", now))
        self.assertFalse(_is_dated(None, now))
        self.assertFalse(_is_dated("not a date", now))

    def test_code_text_shows_urls_without_escapes(self):
        self.assertEqual(code_text("https://a-b.example.com/x_y"), "`https://a-b.example.com/x_y`")


class BudgetTests(unittest.TestCase):
    def test_spent_budget_tells_the_agent_to_record_claims(self):
        workspace = ResearchWorkspace("Notion", SITE, AllPagesSearch(PAGES), max_searches=1)
        workspace.search_web("notion")
        reply = workspace.search_web("notion again")
        self.assertIn("Do not call search_web again", reply)
        self.assertIn("add_claim", reply)


class NotionEndToEndTests(unittest.TestCase):
    """From a company name to a brief, stored evidence, and a grounded follow-up."""

    def setUp(self):
        self.runner = runner()
        model = FakeModel(intent_company="Notion", intent_website=SITE)
        self.engine = ResearchEngine(model, AllPagesSearch(PAGES), agent_runner=self.runner)
        self.state: dict = {"history": []}  # type: ignore[type-arg]
        self.result = self.engine.turn("Research Notion", self.state, ignore_progress)  # type: ignore[arg-type]
        self.brief = cast(JsonObject, self.result["brief"])
        self.claims = cast(list[JsonObject], self.brief["claims"])

    def rejection(self, index: int) -> str:
        return str(self.runner.results[index].get("rejected", ""))

    def test_sources_relaxed_for_news_and_reports_but_not_aggregators(self):
        urls = [s["url"] for s in cast(list[JsonObject], self.brief["sources"])]
        self.assertIn("https://finance.yahoo.example/notion-raise", urls)
        self.assertIn("https://promptarmor.example/notion-ai-leak", urls)
        self.assertEqual(self.brief["rejected_sources"], [
            {"url": JOBS, "reason": "does not mention the company website"},
            {"url": CRUNCHBASE, "reason": "does not mention the company website"},
        ])

    def test_bad_claims_are_rejected_with_reasons(self):
        self.assertIn("must cite a page from the company's own website", self.rejection(4))
        self.assertIn("already supports another claim", self.rejection(5))
        self.assertIn("Coda, Smartsheet", self.rejection(6))
        self.assertEqual(len(self.claims), 7)

    def test_accepted_claims_carry_dates_and_honest_basis(self):
        by_category = {c["category"]: c for c in self.claims if c["category"] != "risks"}
        self.assertEqual(by_category["pricing"]["source_id"], "s2")
        self.assertTrue(by_category["signals"]["dated"])
        self.assertEqual(by_category["signals"]["published_at"], "2020-04-01T00:00:00Z")
        self.assertFalse(by_category["competitors"]["dated"])
        forum = next(c for c in self.claims if "forum user" in str(c["text"]))
        self.assertEqual(forum["basis"], "inference")
        self.assertEqual(len({c["quote"] for c in self.claims}), len(self.claims))

    def test_context_is_kept_for_later_agents_and_follow_ups(self):
        evidence = self.state["evidence"]
        self.assertEqual({s["id"] for s in evidence}, {s["id"] for s in self.brief["sources"]})  # type: ignore[union-attr]
        self.assertTrue(all(s["text"] for s in evidence))
        self.assertEqual(self.state["brief"], self.brief)
        answer = self.engine.turn("Who uses Notion?", self.state, ignore_progress)  # type: ignore[arg-type]
        self.assertEqual(answer["kind"], "answer")

    def test_render_marks_dated_claims_and_unescaped_rejected_urls(self):
        rendered = brief_markdown(self.brief)
        self.assertIn("published 2020\\-04\\-01, **dated: older than 12 months**", rendered)
        self.assertIn(f"- `{JOBS}`: does not mention the company website", rendered)
        self.assertNotIn("jobs\\.example", rendered)


if __name__ == "__main__":
    unittest.main()
