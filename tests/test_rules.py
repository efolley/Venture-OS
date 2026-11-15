"""Deterministic rules: URL safety, cleaning, wrong-company filter, item checks, checklist, pack."""

import json
import unittest
from pathlib import Path

from research import checklist
from research.contracts import TAGS, Source
from research.evidence import check_item
from research.pack import build_pack, schema, validate_pack
from research.sources import (
    classify_source, clean_text, normalize_website, off_target_reason, public_https_url, same_company,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "basecamp_pages.json").read_text())


def _source(sid: str, url: str, text: str, kind: str = "first_party") -> Source:
    return {"id": sid, "url": url, "title": "", "kind": kind, "text": text,
            "retrieved_at": "2026-11-14T00:00:00+00:00", "published_at": None, "round": 1}


class SourceRules(unittest.TestCase):
    def test_website_normalization(self) -> None:
        self.assertEqual(normalize_website("http://Acme.com"), ("https://acme.com/", "http://Acme.com"))
        self.assertEqual(normalize_website("acme.com/x"), ("https://acme.com/x", "acme.com/x"))
        self.assertEqual(normalize_website("https://acme.com"), ("https://acme.com/", None))

    def test_unsafe_urls_rejected(self) -> None:
        for url in ("ftp://acme.com", "https://localhost/", "https://10.0.0.1/", "https://u:p@acme.com",
                    "https://acme.com:8443/", "https://intranet/", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_https_url(url)

    def test_name_matching_is_tolerant(self) -> None:
        self.assertTrue(same_company("Acme Cloud Inc.", "acme cloud"))
        self.assertFalse(same_company("Acme Cloud", "Beta Docs"))

    def test_cookie_text_removed(self) -> None:
        cleaned = clean_text(FIXTURE["pages"][0]["text"])
        self.assertNotIn("cookies", cleaned)
        self.assertIn("nearly a million people", cleaned)

    def test_wrong_company_page_rejected(self) -> None:
        jobs = FIXTURE["pages"][2]
        kind = classify_source(jobs["url"], "basecamp.com")
        self.assertEqual(off_target_reason(kind, jobs["title"], jobs["text"], "Basecamp", "basecamp.com"),
                         "does not mention the company website")
        self.assertIsNone(off_target_reason("first_party", "", "", "Basecamp", "basecamp.com"))


class ItemRules(unittest.TestCase):
    TEXT = "Acme Cloud pricing is per seat, starting at $12 per user per month."

    def check(self, kind: str = "first_party", has_first_party: bool = True, **changes: object):  # type: ignore[no-untyped-def]
        raw = {"statement": "Pricing is per seat from $12 per user per month.",
               "excerpt": self.TEXT, "basis": "fact", "source_id": "s1",
               "tags": ["sales.pricing_model"], "competitor": None, **changes}
        return check_item(raw, sources={"s1": _source("s1", "https://acme.com/p", self.TEXT, kind)},
                          company="Acme Cloud", has_first_party=has_first_party, used_excerpts=set())

    def test_valid_item(self) -> None:
        item, notes = self.check()
        self.assertEqual(item["tags"], ["sales.pricing_model"])
        self.assertEqual(notes, [])

    def test_excerpt_must_be_verbatim(self) -> None:
        with self.assertRaisesRegex(ValueError, "verbatim"):
            self.check(excerpt="Acme Cloud pricing is per seat, starting at $10 per user per month.")

    def test_statement_entities_must_be_in_excerpt(self) -> None:
        with self.assertRaisesRegex(ValueError, "Gartner"):
            self.check(statement="Pricing is per seat according to Gartner.")
        with self.assertRaisesRegex(ValueError, "99"):
            self.check(statement="Pricing is per seat from $99 per user.")

    def test_first_party_tags_need_own_site(self) -> None:
        with self.assertRaisesRegex(ValueError, "own website"):
            self.check(kind="news")
        item, notes = self.check(kind="news", tags=["sales.pricing_model", "market.category"])
        self.assertEqual(item["tags"], ["market.category"])
        self.assertTrue(notes)

    def test_mission_and_vision_must_cite_the_company_site(self) -> None:
        for tag in ("company.mission", "company.vision"):
            with self.subTest(tag=tag):
                item, notes = self.check(kind="news", tags=[tag, "market.category"])
                self.assertEqual(item["tags"], ["market.category"])
                self.assertIn(f"dropped {tag}: must cite the company's own website", notes)
        item, _ = self.check(kind="news", tags=["company.problem"])
        self.assertEqual(item["tags"], ["company.problem"])

    def test_forum_fact_becomes_inference(self) -> None:
        item, _ = self.check(kind="forum", has_first_party=False)
        self.assertEqual(item["basis"], "inference")

    def test_competitor_tags_need_competitor(self) -> None:
        with self.assertRaisesRegex(ValueError, "competitor"):
            self.check(tags=["competitors.pricing"])
        with self.assertRaisesRegex(ValueError, "researched company"):
            self.check(tags=["competitors.pricing"], competitor={"name": "Acme Cloud Inc"})

    def test_duplicate_excerpt_and_bad_tags(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown tags"):
            self.check(tags=["strategy.icp"])
        with self.assertRaisesRegex(ValueError, "distinct"):
            check_item({"statement": "Pricing is per seat from $12 per user per month.",
                        "excerpt": self.TEXT, "basis": "fact", "source_id": "s1",
                        "tags": ["sales.pricing_model"]},
                       sources={"s1": _source("s1", "https://acme.com/p", self.TEXT)},
                       company="Acme Cloud", has_first_party=True,
                       used_excerpts={self.TEXT.casefold() + "|"})


class ChecklistAndPack(unittest.TestCase):
    def test_empty_pack_lists_every_gap(self) -> None:
        cov = checklist.coverage({"name": "Acme", "website": "https://acme.com/", "offering": [],
                                  "mission": [], "vision": [], "problem": []},
                                 {}, [], {})
        # Vision is optional: many companies publish only a mission.
        self.assertEqual(cov["company"]["missing"],
                         ["company.offering", "company.mission", "company.problem"])
        self.assertEqual(cov["market"]["missing"],
                         ["market.category", "market.size_growth", "market.trends"])
        self.assertEqual(cov["competitors"]["missing"], ["competitors.alternative"])
        self.assertNotIn("sales.buying_signals", cov["sales"]["missing"])

    def test_trends_need_2_and_pricing_status(self) -> None:
        cov = checklist.coverage(
            {"name": "A", "website": "https://a.com/", "offering": ["e1"], "mission": ["e1"],
             "vision": [], "problem": ["e1"]},
            {"category": ["e1"], "size_growth": ["e1"], "trends": ["e1"]},
            [{"name": n, "website": "https://x.com/", "evidence_ids": ["e1"], "positioning": ["e1"],
              "pricing": [], "pricing_status": s}
             for n, s in (("B", "not_published"), ("C", "found"), ("D", "not_checked"))],
            {"target_customer": ["e1"], "buyer_role": ["e1"], "pricing_model": ["e1"], "channel": ["e1"]},
        )
        self.assertEqual(cov["market"]["missing"], ["market.trends"])
        self.assertEqual(cov["competitors"]["missing"], ["competitors.pricing:D"])
        self.assertEqual(cov["sales"]["status"], "complete")

    def test_gap_matching(self) -> None:
        self.assertTrue(checklist.matches_gap("competitors.pricing:Beta", "competitors"))
        self.assertTrue(checklist.matches_gap("competitors.pricing:Beta", "competitors.pricing"))
        self.assertFalse(checklist.matches_gap("market.trends", "sales"))

    def test_pack_validation_rejects_unknown_ids(self) -> None:
        pack = build_pack(run_id="r", parent_run_id=None, name="Acme", website="https://acme.com/",
                          evidence=[], sources=[], pricing_checked=set(), known_websites={},
                          rejected=[], uncertainties=[], limits_hit=["rounds"])
        self.assertEqual(pack["status"], "partial")
        broken = json.loads(json.dumps(pack))
        broken["market"]["trends"] = ["e9"]
        with self.assertRaisesRegex(ValueError, "unknown evidence id"):
            validate_pack(broken)

    def test_schema_file_matches_tags(self) -> None:
        self.assertEqual(schema()["$defs"]["tag"]["enum"], list(TAGS))


if __name__ == "__main__":
    unittest.main()
