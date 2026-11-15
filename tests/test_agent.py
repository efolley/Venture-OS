"""The bounded research loop with provider doubles. No live calls."""

import os
import unittest

from doubles import FULL_ITEMS, FULL_ROUTES, G2, HOME, FakeSearch, WorldModel, page
from research import Limits, MemoryStore, PostgresStore, ResearchAgent
from research.store import Store

DSN = os.getenv("RESEARCH_TEST_DATABASE_URL", "")


class AgentLoop(unittest.TestCase):
    def make_store(self) -> Store:
        return MemoryStore()

    def agent(self, routes=None, model=None, limits=None, store=None):  # type: ignore[no-untyped-def]
        self.store = store or self.make_store()
        self.search = FakeSearch(routes if routes is not None else FULL_ROUTES)
        self.model = model or WorldModel(FULL_ITEMS)
        return ResearchAgent(self.model, self.search, self.store, limits=limits)

    def test_full_pack_in_3_rounds(self) -> None:
        result = self.agent().run("Acme Cloud", "http://acmecloud.com")
        pack = result.pack
        assert pack is not None
        self.assertEqual(result.status, "complete", pack["coverage"])
        self.assertEqual(pack["company"]["website"], "https://acmecloud.com/")
        self.assertIn("upgraded", pack["uncertainties"][0])
        self.assertEqual([c["name"] for c in pack["competitors"]], ["Beta Docs", "Gamma Boards", "Delta Desk"])
        self.assertTrue(all(c["pricing_status"] == "found" for c in pack["competitors"]))
        self.assertEqual(len(pack["market"]["trends"]), 2)
        self.assertEqual(self.search.calls[0], ("Acme Cloud product what it does", ["acmecloud.com"]))
        self.assertEqual(len(self.model.calls), 5)  # 2 reason steps + 3 extractions
        rounds = self.store.list_rounds(result.run_id)
        self.assertEqual([r["number"] for r in rounds], [0, 1, 2, 3])
        self.assertEqual(len(self.store.get_evidence(result.run_id)), len(pack["evidence"]))
        self.assertEqual(len(self.store.get_coverage(result.run_id)), 3)
        self.assertEqual(self.store.get_pack(result.run_id)["status"], "complete")  # type: ignore[index]
        self.assertEqual(self.store.get_run(result.run_id)["status"], "complete")  # type: ignore[index]

    def test_limit_returns_partial_pack(self) -> None:
        result = self.agent(limits=Limits(rounds=1)).run("Acme Cloud", "acmecloud.com")
        pack = result.pack
        assert pack is not None
        self.assertEqual((result.status, pack["limits_hit"]), ("partial", ["rounds"]))
        self.assertEqual(pack["coverage"]["company"]["status"], "complete")
        self.assertIn("market.trends", pack["coverage"]["market"]["missing"])

    def test_model_call_limit(self) -> None:
        result = self.agent(limits=Limits(model_calls=1)).run("Acme Cloud", "acmecloud.com")
        self.assertEqual(result.pack["limits_hit"], ["model_calls"])  # type: ignore[index]

    def test_ambiguous_name_asks_to_clarify(self) -> None:
        routes = {"official website": [page("https://basecamp.com/", "Basecamp", "Project tool"),
                                       page("https://basecampoutdoor.com/", "Basecamp Outdoor", "Jobs")]}
        model = WorldModel(resolve={"status": "ambiguous", "candidates": [
            {"name": "Basecamp", "website": "https://basecamp.com", "reason": "software"},
            {"name": "Basecamp Outdoor", "website": "https://basecampoutdoor.com", "reason": "jobs"},
            {"name": "Invented", "website": "https://not-in-results.com", "reason": "x"}]})
        result = self.agent(routes, model).run("Basecamp")
        self.assertEqual(result.status, "clarify")
        self.assertEqual([c["website"] for c in result.candidates],
                         ["https://basecamp.com/", "https://basecampoutdoor.com/"])
        self.assertEqual(self.store.get_run(result.run_id)["status"], "clarify")  # type: ignore[index]

    def test_name_only_proposes_corrected_name_and_websites(self) -> None:
        routes = {"official website": [page("https://www.acmecloud.com/", "Acme Cloud", "home"),
                                       page("https://g2.com/acme", "Acme Cloud reviews", "x")],
                  **FULL_ROUTES}
        model = WorldModel(FULL_ITEMS, resolve={"corrected_name": "Acme Cloud", "candidates": [
            {"name": "Acme Cloud", "website": "acmecloud.com", "reason": "official site"}]})
        result = self.agent(routes, model).run("Acme Clowd")
        self.assertEqual(result.status, "clarify")
        self.assertEqual(result.corrected_name, "Acme Cloud")
        self.assertEqual(result.message, "Did you mean Acme Cloud? Pick the website to research:")
        self.assertEqual(result.candidates[0]["website"], "https://acmecloud.com/")
        self.assertEqual(len(self.search.calls), 1)  # no research before the user chooses
        self.assertEqual(len(self.model.calls), 1)

    def test_rerun_researches_only_gaps(self) -> None:
        first = self.agent(limits=Limits(rounds=2)).run("Acme Cloud", "acmecloud.com")
        self.assertEqual(first.pack["coverage"]["competitors"]["missing"],  # type: ignore[index]
                         ["competitors.alternative"])
        agent = self.agent(store=self.store)
        second = agent.run(parent_run_id=first.run_id, gaps=["competitors"])
        pack = second.pack
        assert pack is not None
        self.assertEqual(second.status, "complete")
        self.assertEqual(pack["parent_run_id"], first.run_id)
        self.assertEqual([q for q, _ in self.search.calls], ["Acme Cloud competitors alternatives acmecloud.com"])
        old_ids = [i["id"] for i in first.pack["evidence"]]  # type: ignore[index]
        self.assertEqual([i["id"] for i in pack["evidence"]][:len(old_ids)], old_ids)
        self.assertEqual(len({i["id"] for i in pack["evidence"]}), len(pack["evidence"]))

    def test_duplicate_and_unsafe_urls_skipped(self) -> None:
        routes = dict(FULL_ROUTES)
        routes["market category size growth"] = [
            page(HOME, "dup", "Acme Cloud again"), page("http://acmecloud.com/x", "http", "x"),
            *FULL_ROUTES["market category size growth"]]
        result = self.agent(routes).run("Acme Cloud", "acmecloud.com")
        urls = [s["url"] for s in result.pack["sources"]]  # type: ignore[index]
        self.assertEqual(urls.count(HOME), 1)
        self.assertNotIn("http://acmecloud.com/x", urls)

    def test_corrective_retry_fixes_bad_item(self) -> None:
        bad = {"items": [{"statement": "Acme Cloud sells a workspace for agencies.",
                          "excerpt": "Acme Cloud sells the best workspace for agencies.",
                          "basis": "fact", "source_id": "s1", "tags": ["company.offering"]}]}

        extract_calls = []

        def override(system, payload, number):  # type: ignore[no-untyped-def]
            if "sources" not in payload:
                return None  # the reason step
            extract_calls.append(payload)
            if len(extract_calls) == 1:
                return bad
            if len(extract_calls) == 2:
                self.assertIn("fix_these", payload)
                self.assertIn("verbatim", payload["fix_these"][0]["error"])
            return None

        result = self.agent(model=WorldModel(FULL_ITEMS, override=override),
                            limits=Limits(rounds=1)).run("Acme Cloud", "acmecloud.com")
        self.assertEqual(result.pack["coverage"]["company"]["status"], "complete")  # type: ignore[index]
        self.assertEqual(self.store.list_rounds(result.run_id)[1]["model_calls"], 2)

    def test_model_can_reject_off_target_source(self) -> None:
        def override(system, payload, number):  # type: ignore[no-untyped-def]
            if any(s["url"] == G2 for s in payload.get("sources", [])):
                return {"items": [], "rejected_sources": [{"source_id": payload["sources"][0]["id"],
                                                           "reason": "a different Acme"}]}
            return None

        result = self.agent(model=WorldModel(FULL_ITEMS, override=override)).run(
            "Acme Cloud", "acmecloud.com")
        pack = result.pack
        assert pack is not None
        self.assertNotIn(G2, [s["url"] for s in pack["sources"]])
        self.assertIn(G2, [r["url"] for r in pack["rejected_sources"]])
        self.assertEqual(pack["status"], "partial")

    def test_search_failure_is_recorded_not_fatal(self) -> None:
        class Broken(FakeSearch):
            def search(self, query, limit=5, *, include_domains=None):  # type: ignore[no-untyped-def]
                raise ValueError("Web search returned HTTP 500.")

        store = self.make_store()
        agent = ResearchAgent(WorldModel(), Broken({}), store, limits=Limits(rounds=2))
        result = agent.run("Acme Cloud", "acmecloud.com")
        self.assertEqual(result.status, "partial")
        self.assertIn("HTTP 500", store.list_rounds(result.run_id)[1]["error"])  # type: ignore[operator]


    def test_pricing_pages_have_their_own_company_page_limit(self) -> None:
        pages = [page(f"https://acmecloud.com/p{n}", "Acme Cloud", f"Acme Cloud page {n} text.")
                 for n in range(3)]
        routes = {"product what it does": pages + [page("https://acmecloud.com/x", "Acme", "x")],
                  "pricing plans customers": [
                      page("https://acmecloud.com/careers", "Jobs", "Join Acme Cloud."),
                      page("https://acmecloud.com/pricing", "Pricing", "Acme Cloud pricing."),
                      page("https://acmecloud.com/customers", "Customers", "Acme Cloud customers."),
                      page("https://acmecloud.com/customers/big", "Big", "Acme Cloud case."),
                      page("https://acmecloud.com/customers/huge", "Huge", "Acme Cloud case 2."),
                      page("https://www.acmecloud.com/pricing/", "Dup", "Acme Cloud pricing.")]}
        result = self.agent(routes, WorldModel(), limits=Limits(rounds=3)).run(
            "Acme Cloud", "acmecloud.com")
        urls = [s["url"] for s in result.pack["sources"]]  # type: ignore[index]
        self.assertNotIn("https://acmecloud.com/x", urls)
        self.assertEqual(len(self.search.calls[1]), 2)
        self.assertIn("https://acmecloud.com/pricing", urls)
        self.assertIn("https://acmecloud.com/customers", urls)
        self.assertIn("https://acmecloud.com/customers/big", urls)
        self.assertNotIn("https://acmecloud.com/customers/huge", urls)
        rejected = {r["url"]: r["reason"] for r in result.pack["rejected_sources"]}  # type: ignore[index]
        self.assertEqual(rejected["https://acmecloud.com/careers"], "low-value page")

    def test_typo_name_is_corrected_and_competitor_sites_kept(self) -> None:
        listing = ("Top Acme Cloud alternatives include Beta Docs, Gamma Boards, and Delta Desk "
                   "for agency teams.")
        routes = {"official website": [page(HOME, "Acme Cloud", "Acme Cloud home")],
                  "product what it does": FULL_ROUTES["product what it does"],
                  "competitors alternatives": [page(G2, "Acme Cloud alternatives", listing)],
                  "Beta Docs pricing": [page("https://betadocs.com/pricing", "Pricing",
                                             "Beta Docs costs $8 per user per month for teams.")]}
        items = dict(FULL_ITEMS)
        items[G2] = [{"statement": f"{n} is an alternative to Acme Cloud.", "excerpt": listing,
                      "tags": ["competitors.alternative"], "competitor": {"name": n}}
                     for n in ("Beta Docs", "Gamma Boards", "Delta Desk")]
        model = WorldModel(items)
        result = self.agent(routes, model, limits=Limits(rounds=4)).run(
            "Acme Cloud", "acmecloud.com", aliases=["Acme Clowd"])
        pack = result.pack
        assert pack is not None
        self.assertEqual(pack["company"]["name"], "Acme Cloud")
        self.assertIn("corrected from Acme Clowd", pack["uncertainties"][0])
        self.assertEqual([c["name"] for c in pack["competitors"]],
                         ["Beta Docs", "Gamma Boards", "Delta Desk"])
        beta = [s for s in pack["sources"] if s["url"] == "https://betadocs.com/pricing"]
        self.assertEqual(beta[0]["kind"], "competitor")
        self.assertEqual(pack["competitors"][0]["website"], "https://betadocs.com/")

    def test_reason_step_site_operator_moves_to_site_setting(self) -> None:
        routes = dict(FULL_ROUTES)
        routes["product what it does"] = [FULL_ROUTES["product what it does"][0]]
        routes["Acme Cloud plans"] = [FULL_ROUTES["product what it does"][1]]

        def reason(payload):  # type: ignore[no-untyped-def]
            if payload["field"] == "sales":
                return {"thought": "Pricing is on the company site.", "gap": "sales.pricing_model",
                        "query": "Acme Cloud plans site:acmecloud.com", "site": ""}
            return {"thought": "Follow.", **payload["suggested"]}

        result = self.agent(routes, WorldModel(FULL_ITEMS, reason=reason)).run(
            "Acme Cloud", "acmecloud.com")
        self.assertIn(("Acme Cloud plans", ["acmecloud.com"]), self.search.calls)
        self.assertEqual(result.status, "complete")

    def test_round_without_new_pages_rereads_pricing_page(self) -> None:
        from doubles import PRICING
        seen = []

        def override(system, payload, number):  # type: ignore[no-untyped-def]
            urls = [src["url"] for src in payload.get("sources", [])]
            if PRICING in urls and PRICING not in seen and "fix_these" not in payload:
                seen.append(PRICING)  # the first read misses the pricing model
                items = [{**i, "source_id": next(src["id"] for src in payload["sources"]
                                                  if src["url"] == HOME), "basis": "fact"}
                         for i in FULL_ITEMS[HOME]]
                return {"items": items}
            return None

        result = self.agent(model=WorldModel(FULL_ITEMS, override=override)).run(
            "Acme Cloud", "acmecloud.com")
        pack = result.pack
        assert pack is not None
        self.assertTrue(pack["sales"]["pricing_model"])
        notes = [n for r in self.store.list_rounds(result.run_id) for n in r["dropped"]]
        self.assertTrue(any(n.startswith("no new pages; re-read") for n in notes), notes)

    def test_only_direct_competitors_with_a_price_signal_count(self) -> None:
        listing = ("Acme Cloud alternatives: Beta Docs is a wiki. Chipco makes servers for data centers. "
                   "Delta Desk costs $15 per seat. Gamma Boards is a great visual tool.")
        routes = {"product what it does": FULL_ROUTES["product what it does"],
                  "competitors alternatives": [page(G2, "Acme Cloud alternatives", listing),
                                               page("https://acmecloud.com/jobs/engineer", "Jobs", "Join Acme Cloud."),
                                               page("https://x.com/benefits.pdf", "Benefits", "Acme Cloud.")]}

        def item(statement, excerpt, tags, name, relation="direct"):  # type: ignore[no-untyped-def]
            return {"statement": statement, "excerpt": excerpt, "tags": tags, "basis": "fact",
                    "competitor": {"name": name, "relation": relation}}

        items = {**FULL_ITEMS, G2: [
            item("Beta Docs is a wiki.", "Acme Cloud alternatives: Beta Docs is a wiki.",
                 ["competitors.alternative"], "Beta Docs"),
            item("Chipco makes servers for data centers.", "Chipco makes servers for data centers.",
                 ["competitors.alternative"], "Chipco", "adjacent"),
            item("Delta Desk costs $15 per seat for teams.", "Delta Desk costs $15 per seat.",
                 ["competitors.alternative", "competitors.pricing"], "Delta Desk"),
            item("Gamma Boards is a great visual tool.", "Gamma Boards is a great visual tool.",
                 ["competitors.alternative", "competitors.pricing"], "Gamma Boards")]}
        result = self.agent(routes, WorldModel(items), limits=Limits(rounds=3)).run(
            "Acme Cloud", "acmecloud.com")
        pack = result.pack
        assert pack is not None
        rivals = {c["name"]: c for c in pack["competitors"]}
        self.assertNotIn("Chipco", rivals)  # adjacent: dropped, not retried
        self.assertEqual(rivals["Delta Desk"]["pricing_status"], "found")
        self.assertEqual(rivals["Gamma Boards"]["pricing"], [])  # "is great" is not a price
        notes = [n for r in self.store.list_rounds(result.run_id) for n in r["dropped"]]
        self.assertTrue(any("adjacent" in n for n in notes))
        self.assertTrue(any("states no price" in n for n in notes))
        reasons = {r["url"]: r["reason"] for r in pack["rejected_sources"]}
        self.assertEqual(reasons["https://acmecloud.com/jobs/engineer"], "low-value page")
        self.assertEqual(reasons["https://x.com/benefits.pdf"], "low-value page")

    def test_empty_round_retries_and_fields_rotate(self) -> None:
        routes = {"product what it does": FULL_ROUTES["product what it does"],
                  "market size forecast": FULL_ROUTES["market category size growth"]}
        result = self.agent(routes, limits=Limits(rounds=3)).run("Acme Cloud", "acmecloud.com")
        queries = [q for q, _ in self.search.calls]
        self.assertEqual(queries[1], "Acme Cloud market category size growth acmecloud.com")
        self.assertEqual(queries[2], "Acme Cloud industry trends acmecloud.com")
        self.assertTrue(queries[3].startswith("Acme Cloud competitors alternatives"))
        rounds = self.store.list_rounds(result.run_id)
        self.assertIn(" || ", rounds[2]["query"])
        self.assertEqual(len(rounds), 4)


@unittest.skipUnless(DSN, "set RESEARCH_TEST_DATABASE_URL to a disposable PostgreSQL database")
class AgentLoopPostgres(AgentLoop):
    def make_store(self) -> Store:
        store = PostgresStore(DSN)
        store.migrate()
        return store


if __name__ == "__main__":
    unittest.main()
