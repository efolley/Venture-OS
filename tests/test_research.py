import json
import re
import unittest
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from urllib.parse import urlsplit
from typing import Callable, cast
from unittest.mock import patch

from ventureos.research import ResearchEngine
from ventureos.research.contracts import CATEGORIES, JsonObject, SearchResult
from ventureos.research.engine import classify_source, clean_text
from ventureos.research.workspace import ResearchWorkspace
from ventureos.research.providers import GeminiModel, TavilySearch
from ventureos.research.render import brief_markdown

try:
    from fastapi.testclient import TestClient
    from ventureos.research.api import create_app
except ImportError:  # optional chat and test extras are not installed
    TestClient = None
    create_app = None


GOLDEN = Path(__file__).parent / "fixtures" / "research_golden_basecamp.json"
SITE = "https://acme.example.com"
FIRST_PARTY_ROTATION = ["product", "pricing", "customers"]
EXTERNAL_ROTATION = ["company", "market", "signals", "risks", "trends", "competitors"]

PAGES: list[SearchResult] = [
    {"url": f"{SITE}/", "title": "Acme Cloud",
     "text": "Acme Cloud builds invoicing software for small agencies. "
             "The company says it serves 4,000 agencies in 30 countries. "
             "Team pricing starts at 29 dollars per user per month."},
    {"url": "https://news.example.org/acme-launch", "title": "Acme Cloud launches an AI assistant",
     "text": "Acme Cloud launched an AI drafting assistant in October 2026. "
             "Analysts expect agencies to adopt it quickly. "
             "Acme.example.com remains the official site."},
    {"url": "https://www.g2.com/products/acme-cloud/reviews", "title": "Acme Cloud reviews",
     "text": "Reviewers praise the simple invoice templates in Acme Cloud. "
             "Several reviewers say the reporting module is limited."},
    {"url": "https://www.reddit.com/r/agencies/acme", "title": "Acme Cloud thread",
     "text": "One agency owner says Acme Cloud replaced three separate tools. "
             "Another participant switched to a competing invoicing product."},
]
OFF_TARGET: SearchResult = {
    "url": "https://jobs.example.net/openings", "title": "Jobs at Acme Outdoor",
    "text": "Acme Outdoor connects job seekers with outdoor employers. Browse open roles at Summit and Ridge.",
}


def make_claims(sources: list[JsonObject], per_source: int = 2) -> list[JsonObject]:
    """Product, pricing and customers claims cite the main site, as the policy requires."""
    claims: list[JsonObject] = []
    counts = {"first": 0, "external": 0}
    for source in sources:
        first = str(source["url"]).startswith(SITE)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(source["text"])) if len(s.strip()) >= 25]
        for sentence in sentences if first else sentences[:per_source]:
            rotation, key = (FIRST_PARTY_ROTATION, "first") if first else (EXTERNAL_ROTATION, "external")
            category = rotation[counts[key] % len(rotation)]
            counts[key] += 1
            claims.append({
                "text": f"The source states: {sentence}"[:400],
                "basis": "fact",
                "category": category,
                "source_id": source["id"],
                "quote": sentence,
            })
    return claims





ClaimEdit = Callable[[list[JsonObject], ResearchWorkspace], list[JsonObject] | None]


class FakeModel:
    """Handles intent and follow-up calls. The research loop uses ScriptedRunner instead."""

    def __init__(
        self,
        *,
        intent_company: str = "Acme Cloud",
        intent_website: str = "",
        follow_up_ids: list[str] | None = None,
    ) -> None:
        self.intent_company, self.intent_website = intent_company, intent_website
        self.follow_up_ids = follow_up_ids

    def json(self, system: str, prompt: str) -> JsonObject:
        if "Classify a user message" in system:
            request = json.loads(prompt)
            if request["has_current_brief"] and request["message"].startswith("Who"):
                return {"action": "follow_up"}
            return {"action": "research", "company": self.intent_company, "website": self.intent_website}
        if "Answer the user's follow-up" in system:
            payload = json.loads(prompt)
            ids = self.follow_up_ids if self.follow_up_ids is not None else [payload["claims"][0]["id"]]
            return {"action": "answer", "answer": "It serves 4,000 agencies.", "claim_ids": ids}
        raise AssertionError("Research no longer calls Model.json.")


class ScriptedRunner:
    """Stands in for the DeepAgents loop: calls the same workspace tools, deterministically."""

    def __init__(
        self,
        *,
        per_source: int = 2,
        queries: tuple[str, ...] = ("market competitors trends",),
        flag: tuple[str, ...] = (),
        edit: ClaimEdit | None = None,
        claims: Callable[[ResearchWorkspace], list[JsonObject]] | None = None,
    ) -> None:
        self.per_source, self.queries, self.flag, self.edit = per_source, queries, flag, edit
        self.claims = claims
        self.results: list[JsonObject] = []

    def __call__(self, workspace: ResearchWorkspace, progress: Callable[..., None]) -> None:
        progress("collecting", {"pass": 1}, {"status": "agent running"}, "running")
        for query in self.queries:
            workspace.search_web(query)
        if not workspace.website or not workspace.company:
            # the agent does this when the user gave no name or website
            workspace.set_company("Acme Cloud", "" if workspace.website else SITE)
        for source_id in self.flag:
            workspace.reject_source(source_id, "different organization")
        if self.claims:
            claims = self.claims(workspace)
        else:
            usable = [s for s in workspace.evidence if s["id"] not in workspace.flagged]
            claims = make_claims(cast(list[JsonObject], usable), self.per_source)
        if self.edit:
            claims = self.edit(claims, workspace) or claims
        for claim in claims:
            self.results.append(json.loads(workspace.add_claim(**claim)))  # type: ignore[arg-type]
        progress("analyzing", {"pass": 1}, workspace.field_status(), "success")


class FakeSearch:
    def __init__(self, pages: list[SearchResult] | None = None) -> None:
        self.pages = pages if pages is not None else PAGES
        self.queries: list[str] = []
        self.calls: list[tuple[str, list[str] | None]] = []

    def search(self, query: str, limit: int = 5, *, include_domains: list[str] | None = None) -> list[SearchResult]:
        self.queries.append(query)
        self.calls.append((query, include_domains))
        pages = self.pages
        if include_domains:
            pages = [p for p in pages if any(urlsplit(p["url"]).hostname in (d, "www." + d) for d in include_domains)]
        return [dict(page) for page in pages[:limit]]  # type: ignore[misc]


class BlockingSearch(FakeSearch):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def search(self, query: str, limit: int = 5, *, include_domains: list[str] | None = None) -> list[SearchResult]:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("Test search was not released.")
        return super().search(query, limit, include_domains=include_domains)


def ignore_progress(module: str, input_data: object, output_data: object, status: str) -> None:
    del module, input_data, output_data, status


def make_engine(
    model: FakeModel | None = None,
    search: FakeSearch | None = None,
    runner: ScriptedRunner | None = None,
) -> ResearchEngine:
    return ResearchEngine(model or FakeModel(), search or FakeSearch(), agent_runner=runner or ScriptedRunner())


class FakeResponse:
    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class ProviderTests(unittest.TestCase):
    def gemini(self, candidate: JsonObject) -> JsonObject:
        with patch("ventureos.research.providers.urlopen", return_value=FakeResponse({"candidates": [candidate]})):
            return GeminiModel(api_key="test-key").json("system", "prompt")

    def test_gemini_json_request_uses_default_lite_model(self):
        body = {"candidates": [{"content": {"parts": [{"text": '{"action":"clarify","question":"Which company?"}'}]}}]}
        model = GeminiModel(api_key="test-key")
        with patch("ventureos.research.providers.urlopen", return_value=FakeResponse(body)) as urlopen:
            result = model.json("system", "prompt")
        request = urlopen.call_args.args[0]
        self.assertEqual(model.model, "gemini-3.5-flash-lite")
        self.assertIn("/models/gemini-3.5-flash-lite:generateContent", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        payload = json.loads(request.data)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 8192)
        self.assertEqual(result["action"], "clarify")

    def test_gemini_requires_an_api_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                GeminiModel(api_key="").json("system", "prompt")

    def test_truncated_gemini_output_is_never_accepted(self):
        candidate = {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"action":"brief","brief":{"claims":['}]}}
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.gemini(candidate)

    def test_invalid_gemini_json_text_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            self.gemini({"content": {"parts": [{"text": "not json"}]}})

    def test_tavily_keeps_published_date_and_skips_empty_text(self):
        body = {"results": [
            {"url": "https://a.example.com/", "title": "A", "raw_content": "Body text.", "published_date": "2026-10-01"},
            {"url": "https://b.example.com/", "title": "B", "content": "   "},
        ]}
        with patch("ventureos.research.providers.urlopen", return_value=FakeResponse(body)):
            results = TavilySearch(api_key="key").search("query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("published_at"), "2026-10-01")

    def test_tavily_requires_an_api_key(self):
        with self.assertRaisesRegex(ValueError, "TAVILY_API_KEY"):
            TavilySearch(api_key="").search("query")


class EvidenceHelperTests(unittest.TestCase):
    def test_clean_text_removes_cookie_navigation_and_signin_text(self):
        raw = ("Skip to main content We use cookies to help. Sign in Menu. "
               "Acme Cloud builds invoicing software for agencies.")
        self.assertEqual(clean_text(raw), "Acme Cloud builds invoicing software for agencies.")

    def test_classify_source_labels_origin(self):
        self.assertEqual(classify_source("https://www.acme.example.com/pricing", "acme.example.com"), "first_party")
        self.assertEqual(classify_source("https://docs.acme.example.com/", "acme.example.com"), "first_party")
        self.assertEqual(classify_source("https://www.g2.com/x"), "review")
        self.assertEqual(classify_source("https://news.ycombinator.com/item?id=1"), "forum")
        self.assertEqual(classify_source("https://leadiq.com/c/x"), "aggregator")
        self.assertEqual(classify_source("https://en.wikipedia.org/wiki/X"), "reference")
        self.assertEqual(classify_source("https://example.org/post"), "other")
        self.assertEqual(classify_source("https://notacme.example.com/", "acme.example.com"), "other")

    def test_tavily_sends_include_domains_only_when_given(self):
        body = {"results": []}
        with patch("ventureos.research.providers.urlopen", return_value=FakeResponse(body)) as urlopen:
            TavilySearch(api_key="key").search("query", include_domains=["acme.example.com"])
            TavilySearch(api_key="key").search("query")
        first, second = (json.loads(call.args[0].data) for call in urlopen.call_args_list)
        self.assertEqual(first["include_domains"], ["acme.example.com"])
        self.assertNotIn("include_domains", second)

    def test_gemini_chat_model_requires_a_key(self):
        with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            GeminiModel(api_key="").chat_model()



class ResearchEngineTests(unittest.TestCase):
    def run_turn(
        self,
        model: FakeModel | None = None,
        search: FakeSearch | None = None,
        message: str = "Acme Cloud",
        runner: ScriptedRunner | None = None,
        state: dict | None = None,  # type: ignore[type-arg]
    ) -> JsonObject:
        engine = make_engine(model, search, runner)
        return engine.turn(message, state if state is not None else {"history": []}, ignore_progress)  # type: ignore[arg-type]

    def test_brief_has_cited_claims_coverage_and_gaps(self):
        state: dict = {"history": []}  # type: ignore[type-arg]
        result = self.run_turn(state=state)
        self.assertEqual(result["kind"], "brief")
        brief = cast(JsonObject, result["brief"])
        claims = cast(list[JsonObject], brief["claims"])
        sources = cast(list[JsonObject], brief["sources"])
        self.assertEqual([c["id"] for c in claims], [f"c{i}" for i in range(1, len(claims) + 1)])
        texts = {s["id"]: s["text"] for s in state["evidence"]}
        for claim in claims:
            self.assertIn(claim["quote"], texts[cast(str, claim["source_id"])])
        self.assertEqual(sum(cast(dict[str, int], brief["coverage"]).values()), len(claims))
        self.assertEqual(brief["gaps"], [])
        self.assertEqual([s["kind"] for s in sources], ["first_party", "other", "review", "forum"])
        self.assertNotIn("icp", brief)
        self.assertNotIn("positioning", brief)

    def test_main_site_is_collected_first_with_a_site_filter(self):
        search = FakeSearch()
        self.run_turn(FakeModel(intent_website=SITE), search=search)
        self.assertEqual(search.calls[0][1], ["acme.example.com"])
        self.assertIsNone(search.calls[1][1])

    def test_paraphrased_quote_is_rejected_and_not_recorded(self):
        def paraphrase(claims: list[JsonObject], _w: ResearchWorkspace) -> None:
            claims[0]["quote"] = "Acme Cloud builds invoicing tools for tiny agencies."
        runner = ScriptedRunner(edit=paraphrase)
        brief = cast(JsonObject, self.run_turn(runner=runner)["brief"])
        self.assertIn("not verbatim", str(runner.results[0]["rejected"]))
        self.assertEqual(len(cast(list, brief["claims"])), len(runner.results) - 1)

    def test_cookie_banner_quote_is_rejected(self):
        def banner(claims: list[JsonObject], _w: ResearchWorkspace) -> None:
            claims[0]["quote"] = "We use cookies to improve your experience on this site."
        runner = ScriptedRunner(edit=banner)
        self.run_turn(runner=runner)
        self.assertIn("cookie, navigation, or sign-in", str(runner.results[0]["rejected"]))

    def test_claim_field_validation(self):
        cases = {
            "unknown source id": ("source_id", "s9"),
            "unknown category": ("category", "strategy"),
            "basis must be": ("basis", "rumor"),
            "needs text": ("text", "short"),
        }
        for message, (field, value) in cases.items():
            with self.subTest(field=field):
                def corrupt(claims: list[JsonObject], _w: ResearchWorkspace, f: str = field, v: str = value) -> None:
                    claims[0][f] = v
                runner = ScriptedRunner(edit=corrupt)
                self.run_turn(runner=runner)
                self.assertRegex(str(runner.results[0]["rejected"]), message)

    def test_brief_needs_3_claims_from_2_sources(self):
        def two_claims(claims: list[JsonObject], _w: ResearchWorkspace) -> list[JsonObject]:
            return claims[:2]
        with self.assertRaisesRegex(ValueError, "3 to 30 distinct claims"):
            self.run_turn(runner=ScriptedRunner(edit=two_claims))

        def one_source(workspace: ResearchWorkspace) -> list[JsonObject]:
            return make_claims(cast(list[JsonObject], workspace.evidence[:1]), 3)
        with self.assertRaisesRegex(ValueError, "at least 2 sources"):
            self.run_turn(runner=ScriptedRunner(claims=one_source))

    def test_off_target_source_is_rejected_before_the_agent_sees_it(self):
        search = FakeSearch([*PAGES[:2], OFF_TARGET, *PAGES[2:]])
        engine = make_engine(search=search)
        brief, evidence = engine.research("Acme", SITE, ignore_progress)
        self.assertNotIn(OFF_TARGET["url"], [s["url"] for s in evidence])
        self.assertEqual(brief["rejected_sources"], [
            {"url": OFF_TARGET["url"], "reason": "does not mention the company website"}])
        self.assertEqual([s["id"] for s in evidence], [ref["id"] for ref in brief["sources"]])

    def test_page_with_only_boilerplate_is_rejected_with_a_reason(self):
        page: SearchResult = {"url": "https://example.org/x", "title": "x",
                              "text": "Skip to main content We use cookies. Sign in Menu."}
        engine = make_engine(search=FakeSearch([page, *PAGES]))
        brief, _ = engine.research("Acme Cloud", "", ignore_progress)
        self.assertEqual(brief["rejected_sources"][0]["reason"], "no usable text after removing boilerplate")

    def test_agent_can_flag_a_source_as_a_different_organization(self):
        brief, evidence = make_engine(runner=ScriptedRunner(flag=("s2",))).research("Acme Cloud", SITE, ignore_progress)
        self.assertEqual([s["id"] for s in brief["sources"]], ["s1", "s3", "s4"])
        self.assertEqual([s["id"] for s in evidence], ["s1", "s3", "s4"])
        self.assertEqual(brief["rejected_sources"][0]["reason"], "flagged by analysis as a different organization")

        workspace = ResearchWorkspace("Acme Cloud", SITE, FakeSearch())
        workspace.search_web("acme")
        workspace.reject_source("s2", "other")
        claim = json.loads(workspace.add_claim(
            "The source states a launch.", "fact", "signals", "s2",
            "Acme Cloud launched an AI drafting assistant in October 2026."))
        self.assertIn("rejected source", claim["rejected"])

    def test_field_status_tracks_missing_fields_until_complete(self):
        workspace = ResearchWorkspace("Acme Cloud", SITE, FakeSearch())
        workspace.seed_main_site()
        status = workspace.field_status()
        self.assertFalse(status["complete"])
        self.assertEqual(status["main_site_pages"], 1)
        self.assertEqual(status["missing_categories"], list(CATEGORIES))
        ScriptedRunner(per_source=3)(workspace, ignore_progress)
        status = workspace.field_status()
        self.assertTrue(status["complete"], status)
        self.assertEqual(status["missing_categories"], [])
        self.assertEqual(len(status["external_sites"]), 3)  # type: ignore[arg-type]

    def test_external_websites_are_capped_at_5_with_a_reason(self):
        externals: list[SearchResult] = [
            {"url": f"https://site{i}.example.net/acme", "title": f"Acme Cloud review {i}",
             "text": f"Acme Cloud is reviewed on site {i}. See acme.example.com for details."}
            for i in range(7)
        ]
        class Batches(FakeSearch):
            def search(self, query, limit=5, *, include_domains=None):  # type: ignore[no-untyped-def]
                self.queries.append(query)
                if include_domains:
                    return [dict(PAGES[0])]  # type: ignore[misc]
                start = (len(self.queries) - 2) * 4
                return [dict(page) for page in externals[start:start + 4]]  # type: ignore[misc]

        workspace = ResearchWorkspace("Acme Cloud", SITE, Batches())
        workspace.seed_main_site()
        workspace.search_web("reviews")
        workspace.search_web("more reviews")
        self.assertEqual(len(workspace.field_status()["external_sites"]), 5)  # type: ignore[arg-type]
        reasons = [r["reason"] for r in workspace.pre_rejected]
        self.assertEqual(reasons.count("external site limit reached"), 2)

    def test_search_budget_is_enforced(self):
        search = FakeSearch()
        workspace = ResearchWorkspace("Acme Cloud", SITE, search, max_searches=2)
        workspace.search_web("one")
        workspace.search_web("two")
        self.assertIn("budget", workspace.search_web("three"))
        self.assertEqual(len(search.queries), 2)

    def test_fewer_than_3_independent_sites_is_reported_as_an_uncertainty(self):
        brief, _ = make_engine(search=FakeSearch(PAGES[:3])).research("Acme Cloud", SITE, ignore_progress)
        self.assertIn("Only 2 independent website(s)", brief["uncertainties"][0])

    def test_company_website_can_be_set_by_the_agent_only_when_the_user_gave_none(self):
        workspace = ResearchWorkspace("", "", FakeSearch())
        workspace.search_web("acme")
        self.assertNotIn("first_party", [s["kind"] for s in workspace.evidence])
        result = json.loads(workspace.set_company("Acme Cloud", "http://acme.example.com"))
        self.assertEqual(result, {"company": "Acme Cloud", "website": "https://acme.example.com"})
        self.assertEqual(workspace.evidence[0]["kind"], "first_party")
        fixed = ResearchWorkspace("Acme Cloud", SITE, FakeSearch())
        self.assertIn("cannot change", fixed.set_company("Acme Cloud", "https://other.example.com"))

    def test_research_url_must_be_public_https(self):
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            self.run_turn(message="https://127.0.0.1/")

    def test_http_website_is_upgraded_to_https_and_reported(self):
        search = FakeSearch()
        events: list[tuple[str, object, str]] = []
        engine = make_engine(FakeModel(intent_website="http://acme.example.com/"), search)
        result = engine.turn("Explore Acme Cloud - http://acme.example.com/", {"history": []},
                             lambda module, _i, output, status: events.append((module, output, status)))
        self.assertEqual(result["kind"], "brief")
        self.assertIn("I used https://acme.example.com/", str(result["message"]))
        self.assertIn("acme.example.com", search.queries[0])
        module, output, status = events[0]
        self.assertEqual((module, status), ("understanding", "success"))
        self.assertEqual(cast(JsonObject, output)["website_upgraded"],
                         {"from": "http://acme.example.com/", "to": "https://acme.example.com/"})

    def test_bare_http_url_message_is_upgraded_and_https_reports_no_upgrade(self):
        upgraded = self.run_turn(FakeModel(intent_company=""), message="http://acme.example.com")
        self.assertIn("I used https://acme.example.com", str(upgraded["message"]))
        plain = self.run_turn(FakeModel(intent_company=""), message="https://acme.example.com")
        self.assertNotIn("I used", str(plain["message"]))

    def test_follow_up_cites_claim_ids_and_source_urls(self):
        engine = make_engine()
        state: dict[str, object] = {"history": []}
        engine.turn("Acme Cloud", cast(dict, state), ignore_progress)  # type: ignore[arg-type]
        answer = engine.turn("Who uses it?", cast(dict, state), ignore_progress)  # type: ignore[arg-type]
        self.assertEqual(answer["kind"], "answer")
        self.assertEqual(answer["claim_ids"], ["c1"])
        self.assertEqual(answer["citations"], [f"{SITE}/"])

    def test_follow_up_rejects_unknown_claims_and_reports_insufficient_evidence(self):
        def follow_up(ids: list[str]) -> JsonObject:
            engine = make_engine(FakeModel(follow_up_ids=ids))
            state = {"history": []}
            engine.turn("Acme Cloud", state, ignore_progress)  # type: ignore[arg-type]
            return engine.turn("Who uses it?", state, ignore_progress)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "unknown claim"):
            follow_up(["c99"])
        self.assertEqual(follow_up([])["kind"], "insufficient")

    def test_research_can_run_without_a_session_for_other_agents(self):
        brief, evidence = make_engine().research("Acme Cloud", SITE, ignore_progress)
        self.assertEqual(brief["company"]["website"], SITE)
        self.assertTrue(all("text" in source for source in evidence))
        self.assertEqual(brief["schema_version"], 2)

    def test_engine_needs_a_chat_model_or_runner(self):
        engine = ResearchEngine(FakeModel(), FakeSearch())
        with self.assertRaisesRegex(ValueError, "chat_model or an agent_runner"):
            engine.research("Acme Cloud", SITE, ignore_progress)



class GoldenBasecampTests(unittest.TestCase):
    """Contract and grounding checks on real-shaped Basecamp pages, not a model benchmark."""

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def runner_for(self, extra_claims: list[JsonObject] | None = None) -> ScriptedRunner:
        golden = self.golden

        def build(workspace: ResearchWorkspace) -> list[JsonObject]:
            ids = {s["url"]: s["id"] for s in workspace.evidence}
            claims = [{"text": c["text"], "basis": c["basis"], "category": c["category"],
                       "source_id": ids[c["source_url"]], "quote": c["quote"]} for c in golden["claims"]]
            return [*claims, *(extra_claims or [])]
        return ScriptedRunner(claims=build)

    def engine(self, extra_claims: list[JsonObject] | None = None) -> ResearchEngine:
        return make_engine(FakeModel(intent_company="Basecamp"), FakeSearch(self.golden["pages"]),
                           self.runner_for(extra_claims))

    def test_golden_claims_are_accepted_with_expected_coverage_and_rejection(self):
        brief, evidence = self.engine().research("Basecamp", "https://basecamp.com", ignore_progress)
        expected = self.golden["expected"]
        self.assertEqual(brief["coverage"], expected["coverage"])
        self.assertEqual(brief["gaps"], expected["gaps"])
        self.assertEqual(brief["rejected_sources"],
                         [{"url": expected["rejected_url"], "reason": expected["rejected_reason"]}])
        self.assertEqual([s["kind"] for s in brief["sources"]], ["first_party", "first_party", "forum"])
        self.assertNotIn("cookies", " ".join(s["text"] for s in evidence))

    def test_cookie_banner_cannot_be_cited_as_evidence(self):
        banner = {"text": "The company says it uses cookies to understand its ads.", "basis": "fact",
                  "category": "company", "source_id": "s2",
                  "quote": "We\u2019d like to use cookies to help understand if our ads are working or not."}
        runner = self.runner_for([banner])
        brief, _ = make_engine(FakeModel(intent_company="Basecamp"), FakeSearch(self.golden["pages"]),
                               runner).research("Basecamp", "https://basecamp.com", ignore_progress)
        self.assertIn("cookie, navigation, or sign-in", str(runner.results[-1]["rejected"]))
        self.assertEqual(brief["coverage"]["company"], self.golden["expected"]["coverage"]["company"])


class RenderTests(unittest.TestCase):
    def test_brief_markdown_groups_claims_escapes_text_and_lists_gaps(self):
        brief = make_engine().research("Acme Cloud", SITE, ignore_progress)[0]
        brief["claims"][0]["text"] = "Uses *bold* markdown"
        rendered = brief_markdown(brief)
        self.assertIn("**Company:** [Acme Cloud](https://acme.example.com)", rendered)
        self.assertNotIn("**Gaps", rendered)
        self.assertIn("\\*bold\\*", rendered)
        self.assertIn("**Sources:**", rendered)
        self.assertNotIn("ICP", rendered)
        for category in CATEGORIES:
            if brief["coverage"][category]:
                self.assertIn(f"**{category.capitalize()}**", rendered)


@unittest.skipUnless(TestClient is not None, "install the chat and test extras to run API tests")
class ResearchApiTests(unittest.TestCase):
    def client(self, model: FakeModel | None = None, search: FakeSearch | None = None,
               runner: ScriptedRunner | None = None):
        assert TestClient is not None and create_app is not None
        return TestClient(create_app(make_engine(model, search, runner)))

    @staticmethod
    def wait_for_job(client, job_id: str) -> JsonObject:  # type: ignore[no-untyped-def]
        deadline = monotonic() + 3
        while monotonic() < deadline:
            result = client.get(f"/api/jobs/{job_id}").json()
            if result["status"] != "running":
                return result
            sleep(0.01)
        raise AssertionError("Background job did not finish in time.")

    def test_research_brief_progress_and_grounded_follow_up(self):
        client = self.client()
        session_id = client.post("/api/sessions").json()["session_id"]
        response = client.post(f"/api/sessions/{session_id}/messages", json={"message": "Acme Cloud"})
        self.assertEqual(response.status_code, 202)
        first = self.wait_for_job(client, response.json()["job_id"])
        self.assertEqual(first["status"], "succeeded")
        result = cast(JsonObject, first["result"])
        self.assertEqual(result["kind"], "brief")
        events = cast(list[JsonObject], first["events"])
        self.assertEqual({e["module"] for e in events},
                         {"understanding", "collecting", "analyzing", "validating", "complete"})
        self.assertTrue(all("input" in e and "output" in e for e in events))
        second = self.wait_for_job(client, client.post(
            f"/api/sessions/{session_id}/messages", json={"message": "Who uses it?"}).json()["job_id"])
        answer = cast(JsonObject, second["result"])
        self.assertEqual(answer["claim_ids"], ["c1"])
        session = client.get(f"/api/sessions/{session_id}").json()
        self.assertEqual(len(session["history"]), 2)
        self.assertEqual(session["brief"]["company"]["name"], "Acme Cloud")

    def test_unknown_session_and_job_are_rejected(self):
        client = self.client()
        self.assertEqual(client.get("/api/sessions/missing").status_code, 404)
        self.assertEqual(client.get("/api/jobs/missing").status_code, 404)
        self.assertEqual(client.post("/api/sessions/missing/messages", json={"message": "x"}).status_code, 404)

    def test_session_rejects_overlapping_research_jobs(self):
        search = BlockingSearch()
        client = self.client(search=search)
        session_id = client.post("/api/sessions").json()["session_id"]
        first = client.post(f"/api/sessions/{session_id}/messages", json={"message": "Acme Cloud"})
        self.assertTrue(search.started.wait(timeout=1))
        second = client.post(f"/api/sessions/{session_id}/messages", json={"message": "Other Co"})
        search.release.set()
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.wait_for_job(client, first.json()["job_id"])["status"], "succeeded")

    def test_invalid_brief_fails_the_job_with_one_validation_failure_event(self):
        def too_few(claims: list[JsonObject], _w: ResearchWorkspace) -> list[JsonObject]:
            return claims[:2]
        client = self.client(runner=ScriptedRunner(edit=too_few))
        session_id = client.post("/api/sessions").json()["session_id"]
        submitted = client.post(f"/api/sessions/{session_id}/messages", json={"message": "Acme Cloud"})
        result = self.wait_for_job(client, submitted.json()["job_id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("3 to 30 distinct claims", str(result["error"]))
        failures = [e for e in cast(list[JsonObject], result["events"])
                    if e["module"] == "validating" and e["status"] == "failure"]
        self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
