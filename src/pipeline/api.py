"""Pipeline API: every Research endpoint, plus GTM runs on stored evidence packs and PM runs
on saved GTM strategy packs.

The UI talks only to this backend. Research stays unaware of GTM: this module builds the
Research app and adds GTM endpoints next to it. A GTM run reads the stored evidence pack
for a Research run and writes the strategy pack to `runs/gtm/<research run id>.json`; a PM
run reads that strategy pack and writes `runs/pm/<research run id>.json`, so results survive
a restart. Bind to loopback only: there is no auth.
"""

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from gtm.orchestrator import GTMOrchestrator
from pm.agent import PMAgent
from research.agent import ResearchAgent
from research.api import create_app as create_research_app
from research.contracts import JsonObject
from research.logs import logger, setup_logging
from research.store import Store

DEFAULT_RESULTS_DIR = Path("runs") / "gtm"
DEFAULT_PM_RESULTS_DIR = Path("runs") / "pm"


class GTMRequest(BaseModel):
    research_run_id: str = Field(min_length=1, max_length=64)
    instructions: str = Field(default="", max_length=300)


class PMRequest(BaseModel):
    research_run_id: str = Field(min_length=1, max_length=64)
    decision: Literal["proceed", "research"] | None = None
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
) -> FastAPI:
    """Build the Research app and add GTM and PM endpoints. run_inline=True is for tests."""
    app = create_research_app(agent, store, run_inline=run_inline)
    app.title = "VentureOS pipeline: Research, GTM, and PM"
    jobs: dict[str, GTMJob] = {}
    running: dict[str, str] = {}  # research run ID -> GTM job ID
    lock = threading.Lock()

    def result_path(research_run_id: str) -> Path:
        return results_dir / f"{research_run_id}.json"

    def load_result(research_run_id: str) -> JsonObject | None:
        path = result_path(research_run_id)
        if not path.exists():
            return None
        return cast(JsonObject, json.loads(path.read_text(encoding="utf-8")))

    def checked_run_id(research_run_id: str) -> str:
        try:
            return str(uuid.UUID(research_run_id))
        except ValueError as error:
            raise HTTPException(404, "Unknown research run.") from error

    def run_job(job: GTMJob, pack: JsonObject, instructions: str) -> None:
        try:
            strategy = gtm.run(pack, instructions=instructions)
            results_dir.mkdir(parents=True, exist_ok=True)
            result_path(job.research_run_id).write_text(
                json.dumps(strategy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
        strategy = load_result(job.research_run_id) if job.status == "done" else None
        return {"job_id": job.id, "research_run_id": job.research_run_id, "status": job.status,
                "error": job.error, "strategy": cast(object, strategy)}

    @app.get("/api/gtm/runs/{research_run_id}")
    def get_gtm_result(research_run_id: str) -> JsonObject:
        run_id = checked_run_id(research_run_id)
        with lock:
            job_id = running.get(run_id)
        return {"research_run_id": run_id, "running_job_id": job_id,
                "strategy": cast(object, load_result(run_id))}

    pm_jobs: dict[str, GTMJob] = {}
    pm_running: dict[str, str] = {}

    def pm_path(research_run_id: str) -> Path:
        return pm_results_dir / f"{research_run_id}.json"

    def load_pm(research_run_id: str) -> JsonObject | None:
        path = pm_path(research_run_id)
        if not path.exists():
            return None
        return cast(JsonObject, json.loads(path.read_text(encoding="utf-8")))

    def run_pm_job(job: GTMJob, strategy: JsonObject, request: PMRequest) -> None:
        try:
            assert pm is not None
            result = pm.run(strategy, decision=request.decision, instructions=request.instructions)
            pm_results_dir.mkdir(parents=True, exist_ok=True)
            pm_path(job.research_run_id).write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
        strategy = load_result(run_id)
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
        result = load_pm(job.research_run_id) if job.status == "done" else None
        return {"job_id": job.id, "research_run_id": job.research_run_id, "status": job.status,
                "error": job.error, "result": cast(object, result)}

    @app.get("/api/pm/runs/{research_run_id}")
    def get_pm_result(research_run_id: str) -> JsonObject:
        run_id = checked_run_id(research_run_id)
        with lock:
            job_id = pm_running.get(run_id)
        return {"research_run_id": run_id, "running_job_id": job_id,
                "result": cast(object, load_pm(run_id))}

    return app


def _default_app() -> FastAPI:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass
    setup_logging()
    from research.providers import TavilySearch, default_model
    from research.store import default_store

    store = default_store()
    model = default_model()
    from .runner import default_pm

    return create_app(ResearchAgent(model, TavilySearch(), store), store, GTMOrchestrator(model),
                      default_pm(model))


def main() -> None:
    import uvicorn

    port = int(os.getenv("RESEARCH_API_PORT", "8000"))
    uvicorn.run(_default_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
