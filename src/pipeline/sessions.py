"""Chat sessions: every chat and its full transcript, so a person can reopen it later.

PostgreSQL when RESEARCH_DATABASE_URL is set (schema `ventureos`), otherwise in memory.
A transcript message is 1 of: the user's text, an assistant reply (text or a website question),
a finished step (Research, GTM, or PM with its progress events), or a result card (evidence
pack, strategy pack, or PM result) that carries its JSON, so a reopened chat shows everything.
"""

from __future__ import annotations  # the stores define a `list` method; keep `list[...]` the builtin

import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, cast

from research.contracts import JsonObject

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
Role = Literal["user", "assistant"]
KINDS = ("text", "clarify", "step", "pack", "strategy", "pm", "error")
_CHAT_FIELDS = ("title", "pending", "active_job_id")


class ChatRecord(TypedDict):
    id: str
    title: str
    pending: JsonObject | None
    active_job_id: str | None
    created_at: str
    updated_at: str


class ChatSummary(ChatRecord):
    message_count: int


class ChatMessage(TypedDict):
    id: str
    seq: int
    role: Role
    kind: str
    text: str
    run_id: str | None
    payload: JsonObject
    created_at: str


class SessionStore(Protocol):
    def create(self) -> ChatRecord: ...
    def get(self, chat_id: str) -> ChatRecord | None: ...
    def list(self, limit: int = 50) -> list[ChatSummary]: ...
    def messages(self, chat_id: str) -> list[ChatMessage]: ...
    def append(self, chat_id: str, role: Role, kind: str, text: str, *,
               run_id: str | None = None, payload: JsonObject | None = None) -> ChatMessage: ...
    def update(self, chat_id: str, **changes: Any) -> None: ...


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_chat_id(chat_id: str) -> str:
    """Return the canonical UUID text, or raise ValueError for anything else."""
    return str(uuid.UUID(chat_id))


def _check(kind: str, changes: dict[str, Any]) -> None:
    if kind not in KINDS:
        raise ValueError(f"Unknown message kind: {kind}")
    unknown = set(changes) - set(_CHAT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown chat fields: {', '.join(sorted(unknown))}")


@dataclass
class MemorySessionStore:
    chats: dict[str, ChatRecord] = field(default_factory=dict)
    transcripts: dict[str, list[ChatMessage]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def create(self) -> ChatRecord:
        stamp = now()
        record: ChatRecord = {"id": str(uuid.uuid4()), "title": "", "pending": None,
                              "active_job_id": None, "created_at": stamp, "updated_at": stamp}
        with self.lock:
            self.chats[record["id"]] = record
            self.transcripts[record["id"]] = []
        return dict(record)  # type: ignore[return-value]

    def get(self, chat_id: str) -> ChatRecord | None:
        with self.lock:
            record = self.chats.get(chat_id)
            return dict(record) if record else None  # type: ignore[return-value]

    def list(self, limit: int = 50) -> list[ChatSummary]:
        with self.lock:
            records = sorted(self.chats.values(), key=lambda r: r["updated_at"], reverse=True)
            return [cast(ChatSummary, {**r, "message_count": len(self.transcripts[r["id"]])})
                    for r in records[:limit]]

    def messages(self, chat_id: str) -> list[ChatMessage]:
        with self.lock:
            return [dict(m) for m in self.transcripts.get(chat_id, [])]  # type: ignore[misc]

    def append(self, chat_id: str, role: Role, kind: str, text: str, *,
               run_id: str | None = None, payload: JsonObject | None = None) -> ChatMessage:
        _check(kind, {})
        with self.lock:
            if chat_id not in self.chats:
                raise KeyError(chat_id)
            transcript = self.transcripts[chat_id]
            message: ChatMessage = {"id": str(uuid.uuid4()), "seq": len(transcript) + 1,
                                    "role": role, "kind": kind, "text": text, "run_id": run_id,
                                    "payload": payload or {}, "created_at": now()}
            transcript.append(message)
            self.chats[chat_id]["updated_at"] = message["created_at"]
            return dict(message)  # type: ignore[return-value]

    def update(self, chat_id: str, **changes: Any) -> None:
        _check("text", changes)
        with self.lock:
            if chat_id not in self.chats:
                raise KeyError(chat_id)
            self.chats[chat_id].update(changes)  # type: ignore[typeddict-item]
            self.chats[chat_id]["updated_at"] = now()


def _iso(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


class PostgresSessionStore:
    """PostgreSQL session store (psycopg 3). Each public method is 1 transaction."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("RESEARCH_DATABASE_URL", "")
        if not self.dsn:
            raise ValueError("Set RESEARCH_DATABASE_URL to store chats in PostgreSQL.")
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

    def migrate(self) -> None:
        with self._connect() as conn:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))

    @staticmethod
    def _record(row: dict[str, Any]) -> ChatRecord:
        return {"id": str(row["id"]), "title": row["title"], "pending": row["pending"],
                "active_job_id": row["active_job_id"], "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"])}

    def create(self) -> ChatRecord:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO ventureos.sessions (id) VALUES (%s) RETURNING *", (str(uuid.uuid4()),)
            ).fetchone()
        return self._record(row)

    def get(self, chat_id: str) -> ChatRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ventureos.sessions WHERE id = %s",
                               (chat_id,)).fetchone()
        return self._record(row) if row else None

    def list(self, limit: int = 50) -> list[ChatSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT s.*, (SELECT count(*) FROM ventureos.messages m WHERE m.session_id = s.id)"
                " AS message_count FROM ventureos.sessions s ORDER BY s.updated_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [cast(ChatSummary, {**self._record(row), "message_count": row["message_count"]})
                for row in rows]

    def messages(self, chat_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ventureos.messages WHERE session_id = %s ORDER BY seq", (chat_id,)
            ).fetchall()
        return [{"id": str(r["id"]), "seq": r["seq"], "role": r["role"], "kind": r["kind"],
                 "text": r["text"], "run_id": str(r["run_id"]) if r["run_id"] else None,
                 "payload": r["payload"], "created_at": _iso(r["created_at"])} for r in rows]

    def append(self, chat_id: str, role: Role, kind: str, text: str, *,
               run_id: str | None = None, payload: JsonObject | None = None) -> ChatMessage:
        _check(kind, {})
        with self._connect() as conn, conn.transaction():
            # Lock the session row so concurrent appends get consecutive seq numbers.
            found = conn.execute("SELECT id FROM ventureos.sessions WHERE id = %s FOR UPDATE",
                                 (chat_id,)).fetchone()
            if found is None:
                raise KeyError(chat_id)
            row = conn.execute(
                "INSERT INTO ventureos.messages (id, session_id, seq, role, kind, text, run_id,"
                " payload) VALUES (%s, %s, (SELECT coalesce(max(seq), 0) + 1 FROM"
                " ventureos.messages WHERE session_id = %s), %s, %s, %s, %s, %s) RETURNING *",
                (str(uuid.uuid4()), chat_id, chat_id, role, kind, text, run_id,
                 self._json(payload or {})),
            ).fetchone()
            conn.execute("UPDATE ventureos.sessions SET updated_at = now() WHERE id = %s",
                         (chat_id,))
        return {"id": str(row["id"]), "seq": row["seq"], "role": row["role"], "kind": row["kind"],
                "text": row["text"], "run_id": run_id, "payload": row["payload"],
                "created_at": _iso(row["created_at"])}

    def update(self, chat_id: str, **changes: Any) -> None:
        _check("text", changes)
        if not changes:
            return
        assignments = ", ".join(f"{key} = %s" for key in changes)
        values = [self._json(v) if k == "pending" and v is not None else v
                  for k, v in changes.items()]
        with self._connect() as conn:
            updated = conn.execute(
                f"UPDATE ventureos.sessions SET {assignments}, updated_at = now() WHERE id = %s",
                (*values, chat_id),
            ).rowcount
        if not updated:
            raise KeyError(chat_id)


MAX_CACHED_MESSAGES = 40


class CachedSessionStore:
    """Read-through, write-through cache of open chats in the short-term store (Redis).

    The chat record (title, pending question, running job) is always cached. Its transcript is
    cached while it has at most MAX_CACHED_MESSAGES messages; longer chats read from the store.
    """

    def __init__(self, store: SessionStore, short_term: Any) -> None:
        self.store = store
        self.short_term = short_term

    def _load(self, chat_id: str) -> JsonObject | None:
        cached = self.short_term.cached_chat(chat_id)
        if cached is not None:
            return cached
        record = self.store.get(chat_id)
        if record is None:
            return None
        messages = self.store.messages(chat_id)
        value: JsonObject = {"chat": dict(record),
                             "messages": messages if len(messages) <= MAX_CACHED_MESSAGES else None}
        self.short_term.cache_chat(chat_id, value)
        return value

    def create(self) -> ChatRecord:
        record = self.store.create()
        self.short_term.cache_chat(record["id"], {"chat": dict(record), "messages": []})
        return record

    def get(self, chat_id: str) -> ChatRecord | None:
        value = self._load(chat_id)
        return cast(ChatRecord, value["chat"]) if value else None

    def list(self, limit: int = 50) -> list[ChatSummary]:
        return self.store.list(limit)

    def messages(self, chat_id: str) -> list[ChatMessage]:
        value = self._load(chat_id)
        if value and value["messages"] is not None:
            return cast(list[ChatMessage], value["messages"])
        return self.store.messages(chat_id)

    def append(self, chat_id: str, role: Role, kind: str, text: str, *,
               run_id: str | None = None, payload: JsonObject | None = None) -> ChatMessage:
        message = self.store.append(chat_id, role, kind, text, run_id=run_id, payload=payload)
        value = self.short_term.cached_chat(chat_id)
        if value is None:
            return message
        messages = value.get("messages")
        if isinstance(messages, list) and len(messages) < MAX_CACHED_MESSAGES:
            messages.append(dict(message))
        else:
            value["messages"] = None
        cast(JsonObject, value["chat"])["updated_at"] = message["created_at"]
        self.short_term.cache_chat(chat_id, value)
        return message

    def update(self, chat_id: str, **changes: Any) -> None:
        self.store.update(chat_id, **changes)
        value = self.short_term.cached_chat(chat_id)
        if value is not None:
            cast(JsonObject, value["chat"]).update(changes)
            self.short_term.cache_chat(chat_id, value)


MIGRATION_LOCK = 0x76656E74  # any fixed 64-bit number shared by the API and every worker


@contextmanager
def migration_lock(dsn: str | None = None) -> Iterator[None]:
    """Hold a PostgreSQL advisory lock while migrations run.

    The API and every worker migrate at startup. `CREATE SCHEMA IF NOT EXISTS` and
    `CREATE TABLE IF NOT EXISTS` are not safe when 2 processes run them at the same moment,
    so they take turns. Without a database URL this does nothing.
    """
    dsn = dsn or os.getenv("RESEARCH_DATABASE_URL", "")
    if not dsn:
        yield
        return
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def default_session_store() -> SessionStore:
    """PostgreSQL when RESEARCH_DATABASE_URL is set, otherwise in memory."""
    if os.getenv("RESEARCH_DATABASE_URL"):
        store = PostgresSessionStore()
        store.migrate()
        return store
    return MemorySessionStore()
