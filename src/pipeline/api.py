"""Pipeline API: chats you can come back to, plus every Research, GTM, and PM endpoint.

The UI talks only to this backend (directly, or through `ventureos-gateway`).

- **Chats** (`/api/chats`): each message becomes a turn that runs Research, then GTM, then PM
  on the server. The transcript is stored (PostgreSQL when RESEARCH_DATABASE_URL is set), so a
  person can reopen any chat and keep talking to it. Turns wait in Kafka for
  `ventureos-worker` when KAFKA_BOOTSTRAP_SERVERS is set, otherwise they run in this process.
  Short-term state (locks, job progress, open chats) lives in Redis when REDIS_URL is set.
- **Runs**: the Research endpoints, GTM on a stored evidence pack, and PM on a saved strategy
  pack. Strategy packs and PM results are saved to `runs/gtm/` and `runs/pm/`.

When the built web UI is present (`src/pipeline/static/`, built from `UI/`), it is served at
`/`, so 1 command starts everything. Bind to loopback only: there is no auth here; put the
gateway in front to add an API key and rate limits.
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from gtm.orchestrator import GTMOrchestrator
from pm.agent import PMAgent
from research.agent import ResearchAgent
from research.api import create_app as create_research_app
from research.contracts import JsonObject
from research.logs import logger, setup_logging
from research.store import Store

from .chats import ChatBusy, ChatService, Submitter, UnknownChat
from .jobqueue import InProcessQueue
from .results import DEFAULT_PM_RESULTS_DIR, DEFAULT_RESULTS_DIR, ResultFiles
from .sessions import MemorySessionStore, SessionStore, check_chat_id
from .shortterm import MemoryShortTerm, ShortTerm

STATIC_DIR = Path(__file__).resolve().parent / "static"


class GTMRequest(BaseModel):
    research_run_id: str = Field(min_length=1, max_length=64)
    instructions: str = Field(default="", max_length=300)


class PMRequest(BaseModel):
    research_run_id: str = Field(min_length=1, max_length=64)
    decision: Literal["proceed", "research"] | None = None
    instructions: str = Field(default="", max_length=300)


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=300)


class ChatDecisionRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)
    decision: Literal["proceed", "research"]
    instructions: str = Field(default="", max_length=300)


@dataclass
class GTMJob:
    id: str
    research_run_id: str
    status: str = "running"
    error: str = ""
    created: float = field(default_factory=time.time)


def create_app(
    agent: ResearchAgent,
    store: Store,
    gtm: GTMOrchestrator,
    pm: PMAgent | None = None,
    *,
    run_inline: bool = False,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    pm_results_dir: Path = DEFAULT_PM_RESULTS_DIR,
    static_dir: Path | None = STATIC_DIR,
    sessions: SessionStore | None = None,
    short_term: ShortTerm | None = None,
    queue: Submitter | None = None,
) -> FastAPI:
    """Build the Research app and add chat, GTM, and PM endpoints. run_inline=True is for tests.

    Without `queue`, chat turns run on a thread pool in this process.
    """
    app = create_research_app(agent, store, run_inline=run_inline)
    app.title = "VentureOS pipeline: chats, Research, GTM, and PM"
    results = ResultFiles(results_dir, pm_results_dir)
    sessions = sessions if sessions is not None else MemorySessionStore()
    short_term = short_term if short_term is not None else MemoryShortTerm()
    service = ChatService(agent, gtm, pm, sessions, short_term, results)
    turns: Submitter = queue if queue is not None else InProcessQueue(service.run, inline=run_inline)
    jobs: dict[str, GTMJob] = {}
    running: dict[str, str] = {}  # research run ID -> GTM job ID
    lock = threading.Lock()

    def checked_run_id(research_run_id: str) -> str:
        try:
            return str(uuid.UUID(research_run_id))
        except ValueError as error:
            raise HTTPException(404, "Unknown research run.") from error

    def checked_chat_id(chat_id: str) -> str:
        try:
            return check_chat_id(chat_id)
        except ValueError as error:
            raise HTTPException(404, "Unknown chat.") from error

    # The Research app's health check is replaced by 1 that also names the chat backends.
    app.router.routes = [route for route in app.router.routes
                         if getattr(route, "path", "") != "/api/health"]

    @app.get("/api/health")
    def health() -> dict[str, str]:
        backing = getattr(sessions, "store", sessions)
        return {"status": "ok", "store": type(store).__name__,
                "sessions": type(backing).__name__, "short_term": type(short_term).__name__,
                "queue": type(turns).__name__}

    # ---- chats ---------------------------------------------------------------------------

    @app.post("/api/chats")
    def create_chat() -> dict[str, str]:
        return {"chat_id": service.create()["id"]}

    @app.get("/api/chats")
    def list_chats(limit: int = Query(default=50, ge=1, le=200)) -> JsonObject:
        return {"chats": cast(object, sessions.list(limit))}

    @app.get("/api/chats/{chat_id}")
    def get_chat(chat_id: str) -> JsonObject:
        view = service.view(checked_chat_id(chat_id))
        if view is None:
            raise HTTPException(404, "Unknown chat.")
        return view

    def submit(call: Any) -> dict[str, str]:
        try:
            return {"job_id": call()}
        except UnknownChat as error:
            raise HTTPException(404, "Unknown chat.") from error
        except ChatBusy as error:
            raise HTTPException(409, "This chat is still working on the last message.") from error
        except Exception as error:  # the queue is down: tell the user, keep the server up
            logger.exception("could not queue a chat turn: %s", type(error).__name__)
            raise HTTPException(503, "The job queue is not available. Try again shortly.") from error

    @app.post("/api/chats/{chat_id}/messages")
    def send_chat_message(chat_id: str, request: ChatMessageRequest) -> dict[str, str]:
        chat_id = checked_chat_id(chat_id)
        return submit(lambda: service.submit_message(chat_id, request.message,
                                                     request.instructions, turns))

    @app.post("/api/chats/{chat_id}/decisions")
    def send_chat_decision(chat_id: str, request: ChatDecisionRequest) -> dict[str, str]:
        chat_id = checked_chat_id(chat_id)
        run_id = checked_run_id(request.run_id)
        return submit(lambda: service.submit_decision(chat_id, run_id, request.decision,
                                                      request.instructions, turns))

    @app.get("/api/chat-jobs/{job_id}")
    def get_chat_job(job_id: str, after: int = Query(default=0, ge=0)) -> JsonObject:
        job = service.job(job_id, after)
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return job

    # ---- GTM and PM on stored runs (the Stored research view) ------------------------------

    def run_job(job: GTMJob, pack: JsonObject, instructions: str) -> None:
        try:
            strategy = gtm.run(pack, instructions=instructions)
            results.save_strategy(job.research_run_id, strategy)
            job.status = "done"
        except Exception as error:  # report, never crash the server thread
            logger.exception("GTM job failed: %s", type(error).__name__)
            job.status, job.error = "failed", f"{type(error).__name__}: {error}"[:300]
        finally:
            with lock:
                running.pop(job.research_run_id, None)

    @app.post("/api/gtm/runs")
    def start_gtm(request: GTMRequest) -> dict[str, str]:
        run_id = checked_run_id(request.research_run_id)
        pack = store.get_pack(run_id)
        if pack is None:
            raise HTTPException(409, "This research run has no evidence pack to analyze.")
        with lock:
            if run_id in running:
                raise HTTPException(409, "A GTM run is already in progress for this research run.")
            job = GTMJob(str(uuid.uuid4()), run_id)
            jobs[job.id] = job
            running[run_id] = job.id
        if run_inline:
            run_job(job, cast(JsonObject, pack), request.instructions)
        else:
            threading.Thread(target=run_job, args=(job, cast(JsonObject, pack), request.instructions),
                             daemon=True).start()
        return {"job_id": job.id}

    @app.get("/api/gtm/jobs/{job_id}")
    def get_gtm_job(job_id: str) -> JsonObject:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown GTM job.")
        strategy = results.load_strategy(job.research_run_id) if job.status == "done" else None
        return {"job_id": job.id, "research_run_id": job.research_run_id, "status": job.status,
                "error": job.error, "strategy": cast(object, strategy)}

    @app.get("/api/gtm/runs/{research_run_id}")
    def get_gtm_result(research_run_id: str) -> JsonObject:
        run_id = checked_run_id(research_run_id)
        with lock:
            job_id = running.get(run_id)
        return {"research_run_id": run_id, "running_job_id": job_id,
                "strategy": cast(object, results.load_strategy(run_id))}

    pm_jobs: dict[str, GTMJob] = {}
    pm_running: dict[str, str] = {}

    def run_pm_job(job: GTMJob, strategy: JsonObject, request: PMRequest) -> None:
        try:
            assert pm is not None
            result = pm.run(strategy, decision=request.decision, instructions=request.instructions)
            results.save_pm(job.research_run_id, result)
            job.status = "done"
        except Exception as error:  # report, never crash the server thread
            logger.exception("PM job failed: %s", type(error).__name__)
            job.status, job.error = "failed", f"{type(error).__name__}: {error}"[:300]
        finally:
            with lock:
                pm_running.pop(job.research_run_id, None)

    @app.post("/api/pm/runs")
    def start_pm(request: PMRequest) -> dict[str, str]:
        if pm is None:
            raise HTTPException(503, "The PM agent is not configured.")
        run_id = checked_run_id(request.research_run_id)
        strategy = results.load_strategy(run_id)
        if strategy is None:
            raise HTTPException(409, "This research run has no GTM strategy to plan from. Run GTM first.")
        with lock:
            if run_id in pm_running:
                raise HTTPException(409, "A PM run is already in progress for this research run.")
            job = GTMJob(str(uuid.uuid4()), run_id)
            pm_jobs[job.id] = job
            pm_running[run_id] = job.id
        if run_inline:
            run_pm_job(job, strategy, request)
        else:
            threading.Thread(target=run_pm_job, args=(job, strategy, request), daemon=True).start()
        return {"job_id": job.id}

    @app.get("/api/pm/jobs/{job_id}")
    def get_pm_job(job_id: str) -> JsonObject:
        job = pm_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown PM job.")
        result = results.load_pm(job.research_run_id) if job.status == "done" else None
        return {"job_id": job.id, "research_run_id": job.research_run_id, "status": job.status,
                "error": job.error, "result": cast(object, result)}

    @app.get("/api/pm/runs/{research_run_id}")
    def get_pm_result(research_run_id: str) -> JsonObject:
        run_id = checked_run_id(research_run_id)
        with lock:
            job_id = pm_running.get(run_id)
        return {"research_run_id": run_id, "running_job_id": job_id,
                "result": cast(object, results.load_pm(run_id))}

    if static_dir is not None and (static_dir / "index.html").is_file():
        # Mounted last so every /api route above wins.
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app


@dataclass
class Backends:
    agent: ResearchAgent
    store: Store
    gtm: GTMOrchestrator
    pm: PMAgent
    sessions: SessionStore
    short_term: ShortTerm
    kafka: bool


def load_backends() -> Backends:
    """Pick every backend from the environment (.env in the current folder is read first)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass
    from research.providers import TavilySearch, default_model
    from research.store import default_store

    from .runner import default_pm
    from .sessions import CachedSessionStore, default_session_store
    from .shortterm import default_short_term

    kafka = bool(os.getenv("KAFKA_BOOTSTRAP_SERVERS"))
    if kafka and not (os.getenv("REDIS_URL") and os.getenv("RESEARCH_DATABASE_URL")):
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS needs REDIS_URL and RESEARCH_DATABASE_URL too: "
                         "the worker runs in another process and shares state through them.")
    store = default_store()
    sessions = default_session_store()
    short_term = default_short_term()
    if not isinstance(short_term, MemoryShortTerm):
        sessions = CachedSessionStore(sessions, short_term)
    model = default_model()
    return Backends(ResearchAgent(model, TavilySearch(), store), store, GTMOrchestrator(model),
                    default_pm(model), sessions, short_term, kafka)


def build_service(*, require_queue: bool = False) -> ChatService:
    """The chat service a worker runs turns with: the same backends as the API."""
    backends = load_backends()
    if require_queue and not backends.kafka:
        raise SystemExit("Set KAFKA_BOOTSTRAP_SERVERS to run a worker. Without Kafka, "
                         "ventureos-api runs chat turns itself.")
    return ChatService(backends.agent, backends.gtm, backends.pm, backends.sessions,
                       backends.short_term)


def _default_app() -> FastAPI:
    setup_logging()
    backends = load_backends()
    queue: Submitter | None = None
    if backends.kafka:
        from .jobqueue import KafkaQueue, ensure_topics

        ensure_topics()
        queue = KafkaQueue()
    return create_app(backends.agent, backends.store, backends.gtm, backends.pm,
                      sessions=backends.sessions, short_term=backends.short_term, queue=queue)


def main() -> None:
    import uvicorn

    host = os.getenv("RESEARCH_API_HOST", "127.0.0.1")
    port = int(os.getenv("RESEARCH_API_PORT", "8000"))
    app = _default_app()
    if (STATIC_DIR / "index.html").is_file():
        print(f"VentureOS is running: open http://127.0.0.1:{port}", flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
