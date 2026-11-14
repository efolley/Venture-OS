"""Storage for runs and every intermediate result: rounds, sources, evidence, coverage, packs.

`Store` is the interface. `PostgresStore` is the default service; `MemoryStore` keeps the
same behavior in process for tests and for runs without a database.
"""

import copy
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

from .contracts import EvidenceItem, EvidencePack, FieldCoverage, JsonObject, RUN_STATUSES, Source
from .logs import logged

MIGRATIONS = Path(__file__).with_name("migrations")


class RunRecord(TypedDict):
    id: str
    parent_run_id: str | None
    company: str
    website: str
    instructions: str
    gaps: list[str]
    status: str
    limits: dict[str, int]
    usage: dict[str, int]
    candidates: list[JsonObject]
    notes: list[str]
    error: str | None


class RunSummary(TypedDict):
    id: str
    parent_run_id: str | None
    company: str
    website: str
    status: str
    usage: dict[str, int]
    created_at: str
    updated_at: str


class RoundRecord(TypedDict):
    number: int
    gap: str
    query: str
    site: str
    model_calls: int
    dropped: list[str]
    error: str | None


class StoredSource(TypedDict):
    url: str
    round: int
    source: Source | None
    rejection_reason: str | None


class Store(Protocol):
    def create_run(self, run: RunRecord) -> None: ...
    def update_run(self, run_id: str, **changes: Any) -> None: ...
    def save_round(
        self, run_id: str, round_record: RoundRecord, sources: list[StoredSource],
        items: list[EvidenceItem], coverage: dict[str, FieldCoverage] | None,
    ) -> None: ...
    def save_pack(self, run_id: str, pack: EvidencePack, usage: dict[str, int]) -> None: ...
    def get_run(self, run_id: str) -> RunRecord | None: ...
    def list_rounds(self, run_id: str) -> list[RoundRecord]: ...
    def get_sources(self, run_id: str) -> list[StoredSource]: ...
    def get_evidence(self, run_id: str) -> list[EvidenceItem]: ...
    def get_coverage(self, run_id: str) -> list[tuple[int, dict[str, FieldCoverage]]]: ...
    def get_pack(self, run_id: str) -> EvidencePack | None: ...
    def list_runs(self, limit: int = 50) -> list["RunSummary"]: ...


_RUN_FIELDS = ("company", "website", "status", "usage", "candidates", "notes", "error")


def _check_changes(changes: dict[str, Any]) -> None:
    unknown = set(changes) - set(_RUN_FIELDS)
    if unknown:
        raise ValueError(f"Unknown run fields: {', '.join(sorted(unknown))}")
    if "status" in changes and changes["status"] not in RUN_STATUSES:
        raise ValueError("Unknown run status.")


@dataclass
class MemoryStore:
    runs: dict[str, RunRecord] = field(default_factory=dict)
    rounds: dict[str, dict[int, RoundRecord]] = field(default_factory=dict)
    sources: dict[str, dict[str, StoredSource]] = field(default_factory=dict)
    evidence: dict[str, dict[str, EvidenceItem]] = field(default_factory=dict)
    coverage: dict[str, dict[int, dict[str, FieldCoverage]]] = field(default_factory=dict)
    packs: dict[str, EvidencePack] = field(default_factory=dict)
    times: dict[str, list[str]] = field(default_factory=dict)

    def create_run(self, run: RunRecord) -> None:
        if run["id"] in self.runs:
            raise ValueError("Run already exists.")
        if run["parent_run_id"] and run["parent_run_id"] not in self.runs:
            raise ValueError("Parent run does not exist.")
        self.runs[run["id"]] = copy.deepcopy(run)
        self.times[run["id"]] = [now_iso(), now_iso()]
        for table in (self.rounds, self.sources, self.evidence, self.coverage):
            table[run["id"]] = {}  # type: ignore[index]

    def update_run(self, run_id: str, **changes: Any) -> None:
        _check_changes(changes)
        self.runs[run_id].update(copy.deepcopy(changes))  # type: ignore[typeddict-item]
        self.times[run_id][1] = now_iso()

    def save_round(self, run_id, round_record, sources, items, coverage) -> None:  # type: ignore[no-untyped-def]
        if round_record["number"] in self.rounds[run_id]:
            raise ValueError("Round already stored.")
        staged_sources = dict(self.sources[run_id])
        for entry in sources:
            if entry["url"] in staged_sources:
                raise ValueError("Source URL already stored for this run.")
            staged_sources[entry["url"]] = copy.deepcopy(entry)
        staged_items = dict(self.evidence[run_id])
        for item in items:
            if item["id"] in staged_items:
                raise ValueError("Evidence id already stored for this run.")
            staged_items[item["id"]] = copy.deepcopy(item)
        self.rounds[run_id][round_record["number"]] = copy.deepcopy(round_record)
        self.sources[run_id] = staged_sources
        self.evidence[run_id] = staged_items
        if coverage is not None:
            self.coverage[run_id][round_record["number"]] = copy.deepcopy(coverage)

    def save_pack(self, run_id: str, pack: EvidencePack, usage: dict[str, int]) -> None:
        self.packs[run_id] = copy.deepcopy(pack)
        self.update_run(run_id, status=pack["status"], usage=usage)

    def get_run(self, run_id: str) -> RunRecord | None:
        return copy.deepcopy(self.runs.get(run_id))

    def list_rounds(self, run_id: str) -> list[RoundRecord]:
        return [copy.deepcopy(r) for _, r in sorted(self.rounds.get(run_id, {}).items())]

    def get_sources(self, run_id: str) -> list[StoredSource]:
        return copy.deepcopy(list(self.sources.get(run_id, {}).values()))

    def get_evidence(self, run_id: str) -> list[EvidenceItem]:
        return copy.deepcopy(list(self.evidence.get(run_id, {}).values()))

    def get_coverage(self, run_id: str) -> list[tuple[int, dict[str, FieldCoverage]]]:
        return copy.deepcopy(sorted(self.coverage.get(run_id, {}).items()))

    def get_pack(self, run_id: str) -> EvidencePack | None:
        return copy.deepcopy(self.packs.get(run_id))

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        ordered = sorted(self.runs.values(), key=lambda r: self.times[r["id"]][0], reverse=True)
        return [{
            "id": r["id"], "parent_run_id": r["parent_run_id"], "company": r["company"],
            "website": r["website"], "status": r["status"], "usage": dict(r["usage"]),
            "created_at": self.times[r["id"]][0], "updated_at": self.times[r["id"]][1],
        } for r in ordered[:limit]]


class PostgresStore:
    """PostgreSQL store using psycopg 3. Each public method is 1 transaction."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("RESEARCH_DATABASE_URL", "")
        if not self.dsn:
            raise ValueError("Set RESEARCH_DATABASE_URL to use PostgreSQL storage.")
        try:
            import psycopg  # noqa: F401
        except ImportError as error:
            raise ValueError("psycopg is not installed. Run: pip install -e '.[research]'") from error

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _json(value: object) -> Any:
        from psycopg.types.json import Jsonb

        return Jsonb(value)

    @logged
    def migrate(self) -> None:
        with self._connect() as conn:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))

    def create_run(self, run: RunRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research.runs (id, parent_run_id, company, website, instructions,"
                " gaps, status, limits, usage, candidates, notes, error)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run["id"], run["parent_run_id"], run["company"], run["website"],
                 run["instructions"], run["gaps"], run["status"], self._json(run["limits"]),
                 self._json(run["usage"]), self._json(run["candidates"]),
                 self._json(run["notes"]), run["error"]),
            )

    def update_run(self, run_id: str, **changes: Any) -> None:
        _check_changes(changes)
        if not changes:
            return
        json_fields = {"usage", "candidates", "notes"}
        assignments = ", ".join(f"{key} = %s" for key in changes)
        values = [self._json(v) if k in json_fields else v for k, v in changes.items()]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE research.runs SET {assignments}, updated_at = now() WHERE id = %s",
                (*values, run_id),
            )

    def save_round(self, run_id, round_record, sources, items, coverage) -> None:  # type: ignore[no-untyped-def]
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO research.rounds (run_id, number, gap, query, site, model_calls,"
                " dropped, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, round_record["number"], round_record["gap"], round_record["query"],
                 round_record["site"], round_record["model_calls"],
                 self._json(round_record["dropped"]), round_record["error"]),
            )
            for entry in sources:
                source = entry["source"]
                conn.execute(
                    "INSERT INTO research.sources (run_id, url, round_number, source_id, title,"
                    " domain, kind, text, published_at, retrieved_at, rejection_reason)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (run_id, entry["url"], entry["round"],
                     source["id"] if source else None,
                     source["title"] if source else "",
                     source["url"].split("/")[2] if source else "",
                     source["kind"] if source else "other",
                     source["text"] if source else "",
                     source["published_at"] if source else None,
                     source["retrieved_at"] if source else None,
                     entry["rejection_reason"]),
                )
            for item in items:
                conn.execute(
                    "INSERT INTO research.evidence_items (run_id, item_id, round_number,"
                    " source_id, item, tags) VALUES (%s, %s, %s, %s, %s, %s)",
                    (run_id, item["id"], item["round"], item["source_id"],
                     self._json(item), item["tags"]),
                )
            if coverage is not None:
                conn.execute(
                    "INSERT INTO research.coverage_snapshots (run_id, round_number, coverage)"
                    " VALUES (%s, %s, %s)",
                    (run_id, round_record["number"], self._json(coverage)),
                )

    def save_pack(self, run_id: str, pack: EvidencePack, usage: dict[str, int]) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO research.packs (run_id, schema_version, status, pack)"
                " VALUES (%s, %s, %s, %s)",
                (run_id, pack["schema_version"], pack["status"], self._json(pack)),
            )
            conn.execute(
                "UPDATE research.runs SET status = %s, usage = %s, updated_at = now()"
                " WHERE id = %s",
                (pack["status"], self._json(usage), run_id),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM research.runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            return None
        return cast(RunRecord, {
            "id": str(row["id"]),
            "parent_run_id": str(row["parent_run_id"]) if row["parent_run_id"] else None,
            **{key: row[key] for key in (
                "company", "website", "instructions", "status", "limits", "usage",
                "candidates", "notes", "error")},
            "gaps": list(row["gaps"]),
        })

    def list_rounds(self, run_id: str) -> list[RoundRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT number, gap, query, site, model_calls, dropped, error"
                " FROM research.rounds WHERE run_id = %s ORDER BY number", (run_id,),
            ).fetchall()
        return [cast(RoundRecord, dict(row)) for row in rows]

    def get_sources(self, run_id: str) -> list[StoredSource]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research.sources WHERE run_id = %s"
                " ORDER BY round_number, source_id NULLS LAST, url", (run_id,),
            ).fetchall()
        result: list[StoredSource] = []
        for row in rows:
            source: Source | None = None
            if row["source_id"]:
                retrieved = row["retrieved_at"]
                source = {
                    "id": row["source_id"], "url": row["url"], "title": row["title"],
                    "kind": row["kind"], "text": row["text"],
                    "retrieved_at": retrieved.isoformat() if isinstance(retrieved, datetime)
                    else str(retrieved),
                    "published_at": row["published_at"], "round": row["round_number"],
                }
            result.append({"url": row["url"], "round": row["round_number"], "source": source,
                           "rejection_reason": row["rejection_reason"]})
        return result

    def get_evidence(self, run_id: str) -> list[EvidenceItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT item FROM research.evidence_items WHERE run_id = %s"
                " ORDER BY round_number, length(item_id), item_id", (run_id,),
            ).fetchall()
        return [cast(EvidenceItem, row["item"]) for row in rows]

    def get_coverage(self, run_id: str) -> list[tuple[int, dict[str, FieldCoverage]]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT round_number, coverage FROM research.coverage_snapshots"
                " WHERE run_id = %s ORDER BY round_number", (run_id,),
            ).fetchall()
        return [(row["round_number"], row["coverage"]) for row in rows]

    def get_pack(self, run_id: str) -> EvidencePack | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pack FROM research.packs WHERE run_id = %s", (run_id,)
            ).fetchone()
        return cast(EvidencePack, row["pack"]) if row else None

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, parent_run_id, company, website, status, usage, created_at, updated_at"
                " FROM research.runs ORDER BY created_at DESC LIMIT %s", (max(1, min(limit, 500)),),
            ).fetchall()
        return [{
            "id": str(row["id"]),
            "parent_run_id": str(row["parent_run_id"]) if row["parent_run_id"] else None,
            "company": row["company"], "website": row["website"], "status": row["status"],
            "usage": row["usage"], "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        } for row in rows]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_store() -> Store:
    """PostgreSQL when RESEARCH_DATABASE_URL is set, otherwise in memory."""
    if os.getenv("RESEARCH_DATABASE_URL"):
        store = PostgresStore()
        store.migrate()
        return store
    return MemoryStore()


__all__ = ["MemoryStore", "PostgresStore", "RoundRecord", "RunRecord", "RunSummary", "Store", "StoredSource",
           "default_store", "now_iso"]
