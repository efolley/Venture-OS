"""FastAPI backend. All processing happens here; the UI only sends input and shows output.

Chat sessions and jobs live in memory; runs, rounds, evidence, and packs live in the store
(PostgreSQL when RESEARCH_DATABASE_URL is set). Bind to loopback only: there is no auth.
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .agent import ResearchAgent
from .chat import Chat, ChatSession, new_session, reply
from .contracts import JsonObject
from .logs import logger, setup_logging
from .store import Store

MAX_EVENTS = 200


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=300)


@dataclass
class Job:
    id: str
    session_id: str
    status: str = "running"
    events: list[JsonObject] = field(default_factory=list)
    reply: JsonObject | None = None
    created: float = field(default_factory=time.time)

    def progress(self, step: str, data: JsonObject, status: str) -> None:
        if len(self.events) < MAX_EVENTS:
            self.events.append({"step": step, "status": status, "data": data, "at": time.time()})


def create_app(agent: ResearchAgent, store: Store, *, run_inline: bool = False) -> FastAPI:
    """Build the app. run_inline=True runs jobs synchronously (for tests)."""
    app = FastAPI(title="VentureOS Research agent", version="0.2.0")
    chat = Chat(agent)
    sessions: dict[str, ChatSession] = {}
    jobs: dict[str, Job] = {}

    def run_job(job: Job, session: ChatSession, request: MessageRequest) -> None:
        with session.lock:
            session.history.append({"role": "user", "content": request.message})
            try:
                answer = chat.handle(session, request.message, request.instructions, job.progress)
                job.status = "done"
            except ValueError as error:
                answer = reply("error", str(error)[:300])
                job.status = "failed"
            except Exception as error:  # report, never crash the server thread
                logger.exception("job failed: %s", type(error).__name__)
                answer = reply("error", "The research run failed. Check the server log.")
                job.status = "failed"
            session.history.append({"role": "assistant", **answer})
            job.reply = answer

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "store": type(store).__name__}

    @app.post("/api/sessions")
    def create_session() -> dict[str, str]:
        session = new_session()
        sessions[session.id] = session
        return {"session_id": session.id}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> JsonObject:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Unknown session.")
        return {"session_id": session.id, "history": session.history,
                "pending": session.pending["kind"] if session.pending else None}

    @app.post("/api/sessions/{session_id}/messages")
    def send_message(session_id: str, request: MessageRequest) -> dict[str, str]:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Unknown session.")
        if session.lock.locked():
            raise HTTPException(409, "A research run is already in progress for this chat.")
        job = Job(str(uuid.uuid4()), session_id)
        jobs[job.id] = job
        if run_inline:
            run_job(job, session, request)
        else:
            threading.Thread(target=run_job, args=(job, session, request), daemon=True).start()
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, after: int = Query(default=0, ge=0)) -> JsonObject:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return {"job_id": job.id, "status": job.status, "events": job.events[after:],
                "next": len(job.events), "reply": job.reply}

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=500)) -> JsonObject:
        return {"runs": cast(object, store.list_runs(limit))}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> JsonObject:
        try:
            uuid.UUID(run_id)
        except ValueError as error:
            raise HTTPException(404, "Unknown run.") from error
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Unknown run.")
        return {"run": cast(object, run), "pack": cast(object, store.get_pack(run_id))}

    @app.get("/api/runs/{run_id}/rounds")
    def get_rounds(run_id: str) -> JsonObject:
        get_run(run_id)
        coverage = dict(store.get_coverage(run_id))
        rounds = [{**r, "coverage": coverage.get(r["number"])} for r in store.list_rounds(run_id)]
        sources = [{"url": s["url"], "round": s["round"], "rejection_reason": s["rejection_reason"],
                    "id": s["source"]["id"] if s["source"] else None,
                    "kind": s["source"]["kind"] if s["source"] else None}
                   for s in store.get_sources(run_id)]
        return {"rounds": cast(object, rounds), "sources": cast(object, sources)}

    return app


def _default_app() -> FastAPI:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass
    setup_logging()
    from .providers import TavilySearch, default_model
    from .store import default_store

    store = default_store()
    return create_app(ResearchAgent(default_model(), TavilySearch(), store), store)


def main() -> None:
    import uvicorn

    port = int(os.getenv("RESEARCH_API_PORT", "8000"))
    uvicorn.run(_default_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
