"""Local FastAPI service for the Research agent; session and job state are held in memory."""

import copy
import threading
import uuid
from dataclasses import dataclass, field

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .contracts import JsonObject, SessionState
from .engine import ResearchEngine
from .logs import logged, logged_debug, logger, setup_logging
from .providers import GeminiModel, TavilySearch

load_dotenv()
setup_logging()


@logged_debug
def _new_state() -> SessionState:
    return {"history": []}


@logged_debug
def _new_events() -> list[JsonObject]:
    return []


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@dataclass
class Session:
    state: SessionState = field(default_factory=_new_state)
    lock: threading.RLock = field(default_factory=threading.RLock)
    active_job: str | None = None


@dataclass
class Job:
    status: str = "running"
    events: list[JsonObject] = field(default_factory=_new_events)
    result: JsonObject | None = None
    error: str | None = None
    active_module: str | None = None
    active_input: object | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    @logged_debug
    def progress(
        self,
        module: str,
        input_data: object,
        output_data: object,
        status: str,
    ) -> None:
        with self.lock:
            if status == "running":
                self.active_module = module
                self.active_input = input_data
            elif self.active_module == module:
                self.active_module = None
                self.active_input = None
            self._append_event(module, input_data, output_data, status)

    @logged_debug
    def finish(
        self,
        status: str,
        result: JsonObject | None,
        error: str | None,
        message: str,
    ) -> None:
        with self.lock:
            self.status = status
            self.result = result
            self.error = error
            if status == "failed":
                self._append_event(
                    self.active_module or "request",
                    self.active_input if self.active_input is not None else {"message": message},
                    error or "Research failed.",
                    "failure",
                )
            self.active_module = None
            self.active_input = None
            self._append_event(
                "complete", {"message": message}, result if result is not None else error,
                "success" if status == "succeeded" else "failure",
            )

    @logged_debug
    def _append_event(
        self,
        module: str,
        input_data: object,
        output_data: object,
        status: str,
    ) -> None:
        self.events.append({
            "sequence": len(self.events),
            "module": module,
            "input": input_data,
            "output": output_data,
            "status": status,
        })


@logged
def create_app(engine: ResearchEngine | None = None) -> FastAPI:
    if engine is None:
        engine = ResearchEngine(GeminiModel(), TavilySearch())
    app = FastAPI(title="VentureOS Research API")
    sessions: dict[str, Session] = {}
    jobs: dict[str, Job] = {}
    registry_lock = threading.Lock()

    @app.post("/api/sessions", status_code=201)
    @logged
    def create_session() -> dict[str, str]:
        session_id = uuid.uuid4().hex
        with registry_lock:
            sessions[session_id] = Session()
        return {"session_id": session_id}

    @app.get("/api/sessions/{session_id}")
    @logged_debug
    def get_session(session_id: str) -> dict[str, object]:
        with registry_lock:
            session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Session not found.")
        with session.lock:
            history = copy.deepcopy(session.state.get("history", []))
            return {
                "history": history,
                "brief": copy.deepcopy(session.state.get("brief")),
            }

    @app.post("/api/sessions/{session_id}/messages", status_code=202)
    @logged
    def submit_message(session_id: str, request: MessageRequest) -> dict[str, str]:
        message = request.message.strip()
        if not message:
            raise HTTPException(422, "Enter a company, website, or question.")
        with registry_lock:
            session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Session not found.")
        with session.lock:
            if session.active_job:
                previous = jobs.get(session.active_job)
                if previous and previous.status == "running":
                    raise HTTPException(409, "Wait for the current research step to finish.")
            job_id = uuid.uuid4().hex
            logger.info("job=%s submitted chars=%d", job_id[:8], len(message))
            job = Job()
            with registry_lock:
                jobs[job_id] = job
            session.active_job = job_id
            state = copy.deepcopy(session.state)

        @logged
        def run():
            try:
                result = engine.turn(message, state, job.progress)
                state["history"] = [
                    *state.get("history", []),
                    {"user": message, "assistant": result},
                ]
                with session.lock:
                    session.state = state
                    job.finish("succeeded", result, None, message)
            except Exception as error:
                logger.error("job=%s failed %s: %s", job_id[:8], type(error).__name__, error)
                with session.lock:
                    job.finish("failed", None, f"{type(error).__name__}: {error}", message)
            finally:
                with session.lock:
                    if session.active_job == job_id:
                        session.active_job = None

        threading.Thread(target=run, name=f"research-{job_id[:8]}", daemon=True).start()
        return {"job_id": job_id, "status": "running"}

    @app.get("/api/jobs/{job_id}")
    @logged_debug
    def get_job(job_id: str, after: int = Query(default=0, ge=0)) -> dict[str, object]:
        with registry_lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        with job.lock:
            events: list[JsonObject] = job.events[after:]
            return {
                "job_id": job_id,
                "status": job.status,
                "events": events,
                "next_cursor": after + len(events),
                "result": copy.deepcopy(job.result),
                "error": job.error,
            }

    return app


app = create_app()


@logged
def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
