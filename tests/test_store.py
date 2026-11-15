"""Store contract tests, run against MemoryStore and (when configured) PostgreSQL."""

import os
import unittest
import uuid

from research.contracts import Limits
from research.store import MemoryStore, PostgresStore, RunRecord, StoredSource

DSN = os.getenv("RESEARCH_TEST_DATABASE_URL", "")


def _run(parent: str | None = None) -> RunRecord:
    return {"id": str(uuid.uuid4()), "parent_run_id": parent, "company": "Acme", "website": "",
            "instructions": "", "gaps": ["market"], "status": "running",
            "limits": Limits().as_dict(), "usage": {}, "candidates": [], "notes": [], "error": None}


def _source(url: str, sid: str | None) -> StoredSource:
    return {"url": url, "round": 1, "rejection_reason": None if sid else "off target",
            "source": {"id": sid, "url": url, "title": "t", "kind": "other", "text": "body",
                       "retrieved_at": "2026-11-14T00:00:00+00:00", "published_at": None,
                       "round": 1} if sid else None}


ITEM = {"id": "e1", "statement": "s" * 20, "excerpt": "x" * 30, "basis": "fact",
        "tags": ["market.trends"], "source_id": "s1", "url": "https://a.com/", "retrieved_at": "t",
        "published_at": None, "competitor": None, "round": 1}
ROUND = {"number": 1, "gap": "market", "query": "q", "site": "", "model_calls": 1,
         "dropped": [], "error": None}
COVERAGE = {"market": {"status": "partial", "missing": ["market.trends"]}}


class StoreContract:
    store: MemoryStore | PostgresStore

    def test_run_round_trip(self) -> None:
        run = _run()
        self.store.create_run(run)
        self.store.update_run(run["id"], status="partial", website="https://a.com/")
        self.store.save_round(run["id"], ROUND, [_source("https://a.com/", "s1"),
                                                _source("https://b.com/", None)], [ITEM], COVERAGE)
        stored = self.store.get_run(run["id"])
        assert stored is not None
        self.assertEqual((stored["status"], stored["website"], stored["gaps"]),
                         ("partial", "https://a.com/", ["market"]))
        self.assertEqual(self.store.list_rounds(run["id"])[0]["query"], "q")
        sources = self.store.get_sources(run["id"])
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["source"]["text"], "body")  # type: ignore[index]
        self.assertEqual(sources[1]["rejection_reason"], "off target")
        self.assertEqual(self.store.get_evidence(run["id"])[0]["tags"], ["market.trends"])
        self.assertEqual(self.store.get_coverage(run["id"]), [(1, COVERAGE)])

    def test_list_runs_newest_first(self) -> None:
        first, second = _run(), _run()
        self.store.create_run(first)
        self.store.create_run(second)
        ids = [r["id"] for r in self.store.list_runs(500)]
        self.assertLess(ids.index(second["id"]), ids.index(first["id"]))
        self.assertTrue(self.store.list_runs(500)[0]["created_at"])

    def test_round_is_atomic(self) -> None:
        run = _run()
        self.store.create_run(run)
        self.store.save_round(run["id"], ROUND, [_source("https://a.com/", "s1")], [], None)
        with self.assertRaises(Exception):
            self.store.save_round(run["id"], {**ROUND, "number": 2},  # type: ignore[arg-type]
                                  [_source("https://c.com/", "s2"), _source("https://a.com/", "s3")],
                                  [], None)
        self.assertEqual([r["number"] for r in self.store.list_rounds(run["id"])], [1])
        self.assertEqual(len(self.store.get_sources(run["id"])), 1)

    def test_unknown_parent_and_status_rejected(self) -> None:
        with self.assertRaises(Exception):
            self.store.create_run(_run(parent=str(uuid.uuid4())))
        run = _run()
        self.store.create_run(run)
        with self.assertRaises(ValueError):
            self.store.update_run(run["id"], status="done")


class MemoryStoreTest(StoreContract, unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()


@unittest.skipUnless(DSN, "set RESEARCH_TEST_DATABASE_URL to a disposable PostgreSQL database")
class PostgresStoreTest(StoreContract, unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresStore(DSN)
        self.store.migrate()

    def test_migrate_is_repeatable(self) -> None:
        self.store.migrate()


if __name__ == "__main__":
    unittest.main()
