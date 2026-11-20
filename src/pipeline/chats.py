"""Chat turns, run on the server: 1 message becomes Research, then GTM, then PM.

The API accepts a message, stores it, takes the chat's lock, and queues a turn. A worker (the
API's own thread pool, or `ventureos-worker` reading Kafka) runs the turn: it answers with
Research's chat logic (a website question, a re-run offer, or an evidence pack), runs GTM and
PM on a new pack, and appends every step and result card to the chat's transcript. Progress
events go to the short-term store, so the browser can follow a turn that runs in another process.

This module only orders the agents and records what they return; it adds no claims.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from gtm.orchestrator import GTMOrchestrator
from pm.agent import PMAgent
from research.agent import ResearchAgent
from research.chat import Chat, ChatSession, company_from_message
from research.contracts import JsonObject
from research.logs import logger

from .results import ResultFiles
from .sessions import ChatRecord, SessionStore
from .shortterm import ShortTerm

Phase = Literal["research", "gtm", "pm"]
PHASE_TEXT: dict[str, tuple[str, str]] = {
    "research": ("Research finished", "Research failed"),
    "gtm": ("GTM strategy ready", "GTM failed"),
    "pm": ("PM plan ready", "PM failed"),
}
PM_TEXT = {
    "hitl_required": "The strategy pack misses required information. Choose how to continue.",
    "research_requested": "Gaps sent back to Research. Start a new research run in the chat to fill them.",
}
STEP_EVENTS = 60  # progress events kept with a finished step in the transcript


class ChatBusy(Exception):
    """A turn is already queued or running for this chat."""


class UnknownChat(KeyError):
    pass


class Submitter(Protocol):
    """Anything that runs a turn later: the in-process queue or Kafka."""

    def submit(self, turn: JsonObject) -> None: ...


@dataclass
class _Step:
    service: "ChatService"
    job_id: str
    chat_id: str
    phase: Phase
    started: float = field(default_factory=time.perf_counter)
    events: list[JsonObject] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.service.short_term.add_event(
            self.job_id, {"step": "phase", "status": "running", "data": {"phase": self.phase},
                          "at": time.time()})

    def progress(self, step: str, data: JsonObject, status: str) -> None:
        event: JsonObject = {"step": step, "status": status, "data": data, "at": time.time()}
        if len(self.events) < STEP_EVENTS:
            self.events.append(event)
        self.service.short_term.add_event(self.job_id, event)

    def finish(self, ok: bool, text: str | None = None) -> None:
        status = "done" if ok else "failed"
        duration = round(time.perf_counter() - self.started, 1)
        done_text, failed_text = PHASE_TEXT[self.phase]
        self.service.sessions.append(
            self.chat_id, "assistant", "step", text or (done_text if ok else failed_text),
            payload={"phase": self.phase, "status": status, "duration_s": duration,
                     "events": self.events})
        self.service.short_term.add_event(
            self.job_id, {"step": "phase", "status": status,
                          "data": {"phase": self.phase, "duration_s": duration}, "at": time.time()})


class ChatService:
    def __init__(self, agent: ResearchAgent, gtm: GTMOrchestrator, pm: PMAgent | None,
                 sessions: SessionStore, short_term: ShortTerm,
                 results: ResultFiles | None = None) -> None:
        self.chat = Chat(agent)
        self.gtm = gtm
        self.pm = pm
        self.sessions = sessions
        self.short_term = short_term
        self.results = results or ResultFiles()

    # ---- API side: accept a turn and queue it -------------------------------------------

    def create(self) -> ChatRecord:
        return self.sessions.create()

    def submit_message(self, chat_id: str, text: str, instructions: str,
                       queue: Submitter) -> str:
        record = self._record(chat_id)
        turn: JsonObject = {"kind": "message", "chat_id": chat_id, "text": text,
                            "instructions": instructions}
        title = "" if record["title"] else company_from_message(text)[:80]
        return self._submit(record, turn, text, queue, title)

    def submit_decision(self, chat_id: str, run_id: str, decision: str, instructions: str,
                        queue: Submitter) -> str:
        record = self._record(chat_id)
        turn: JsonObject = {"kind": "decision", "chat_id": chat_id, "run_id": run_id,
                            "decision": decision, "instructions": instructions}
        label = "Proceed with gaps" if decision == "proceed" else "Research more"
        return self._submit(record, turn, label, queue, "")

    def _record(self, chat_id: str) -> ChatRecord:
        record = self.sessions.get(chat_id)
        if record is None:
            raise UnknownChat(chat_id)
        return record

    def _submit(self, record: ChatRecord, turn: JsonObject, user_text: str, queue: Submitter,
                title: str) -> str:
        chat_id = record["id"]
        job_id = str(uuid.uuid4())
        if not self.short_term.acquire(chat_id, job_id):
            raise ChatBusy(chat_id)
        turn["job_id"] = job_id
        try:
            self.short_term.put_job(job_id, {"id": job_id, "chat_id": chat_id, "status": "queued",
                                             "error": "", "created": time.time()})
            self.sessions.append(chat_id, "user", "text", user_text)
            changes: dict[str, Any] = {"active_job_id": job_id}
            if title:
                changes["title"] = title
            self.sessions.update(chat_id, **changes)
            queue.submit(turn)
        except Exception:
            self.short_term.put_job(job_id, {"id": job_id, "chat_id": chat_id, "status": "failed",
                                             "error": "The turn could not be queued."})
            self.sessions.update(chat_id, active_job_id=None)
            self.short_term.release(chat_id, job_id)
            raise
        return job_id

    def job(self, job_id: str, after: int = 0) -> JsonObject | None:
        job = self.short_term.get_job(job_id)
        if job is None:
            return None
        events = self.short_term.events(job_id, after)
        return {**job, "events": events, "next": after + len(events)}

    def view(self, chat_id: str) -> JsonObject | None:
        record = self.sessions.get(chat_id)
        if record is None:
            return None
        job_id = record["active_job_id"]
        job = self.short_term.get_job(job_id) if job_id else None
        running = job_id if job and job.get("status") in ("queued", "running") else None
        pending = record["pending"]
        return {"chat": {**record, "active_job_id": running,
                         "pending": pending.get("kind") if pending else None},
                "messages": self.sessions.messages(chat_id)}

    # ---- worker side: run a queued turn -------------------------------------------------

    def run(self, turn: JsonObject) -> str:
        """Run 1 queued turn and record everything in the transcript. Returns the job status."""
        job_id, chat_id = str(turn["job_id"]), str(turn["chat_id"])
        job = self.short_term.get_job(job_id) or {"id": job_id, "chat_id": chat_id}
        self.short_term.put_job(job_id, {**job, "status": "running", "started": time.time()})
        status, error = "done", ""
        try:
            if turn.get("kind") == "decision":
                ok = self._decision(job_id, chat_id, str(turn.get("run_id") or ""),
                                    str(turn.get("decision") or ""), str(turn.get("instructions") or ""))
            else:
                ok = self._message(job_id, chat_id, str(turn.get("text") or ""),
                                   str(turn.get("instructions") or ""))
            if not ok:
                status = "failed"
        except Exception as exc:  # noqa: BLE001 - record it, never crash the worker
            logger.exception("chat turn failed: %s", type(exc).__name__)
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]
            self._safe_append(chat_id, "The run failed. Check the server log.")
        finally:
            try:
                self.sessions.update(chat_id, active_job_id=None)
            except Exception:  # noqa: BLE001 - the chat may have been removed
                logger.exception("could not clear the running job of chat %s", chat_id)
            self.short_term.put_job(job_id, {**job, "status": status, "error": error,
                                             "finished": time.time()})
            self.short_term.release(chat_id, job_id)
        return status

    def _safe_append(self, chat_id: str, text: str) -> None:
        try:
            self.sessions.append(chat_id, "assistant", "error", text)
        except Exception:  # noqa: BLE001
            logger.exception("could not record the failure in chat %s", chat_id)

    def _message(self, job_id: str, chat_id: str, text: str, instructions: str) -> bool:
        record = self._record(chat_id)
        session = ChatSession(chat_id, pending=record["pending"])
        step = _Step(self, job_id, chat_id, "research")
        try:
            reply = self.chat.handle(session, text, instructions, step.progress)
        except ValueError as error:
            reply = {"kind": "error", "message": str(error)[:300]}
        self.sessions.update(chat_id, pending=session.pending)
        kind = reply["kind"]
        if step.events or kind == "pack":
            step.finish(kind != "error")
        if kind == "clarify":
            self.sessions.append(chat_id, "assistant", "clarify", reply["message"],
                                 run_id=reply.get("run_id"),
                                 payload={"candidates": reply.get("candidates") or []})
            return True
        if kind != "pack":
            self.sessions.append(chat_id, "assistant", "error" if kind == "error" else "text",
                                 reply["message"])
            return kind != "error"

        pack = cast(JsonObject, reply["pack"])
        run_id = str(reply["run_id"])
        name = str(cast(JsonObject, pack["company"]).get("name") or "")
        if name and record["title"] in ("", company_from_message(text)[:80]):
            self.sessions.update(chat_id, title=name[:80])
        quick = ["yes"] if session.pending and session.pending.get("kind") == "rerun" else []
        self.sessions.append(chat_id, "assistant", "pack", reply["message"], run_id=run_id,
                             payload={"pack": pack, "quick": quick})

        step = _Step(self, job_id, chat_id, "gtm")
        try:
            strategy = cast(JsonObject, self.gtm.run(dict(pack), instructions=instructions))
        except Exception as exc:  # noqa: BLE001 - keep the evidence pack in the chat
            logger.exception("GTM failed in chat %s", chat_id)
            step.finish(False)
            self.sessions.append(chat_id, "assistant", "error",
                                 f"GTM failed: {type(exc).__name__}: {exc}"[:300])
            return False
        self.results.save_strategy(run_id, strategy)
        step.finish(True)
        self.sessions.append(chat_id, "assistant", "strategy", "Here is the GTM strategy and company snapshot.",
                             run_id=run_id, payload={"strategy": strategy})
        return self._plan(job_id, chat_id, run_id, strategy, instructions, None)

    def _decision(self, job_id: str, chat_id: str, run_id: str, decision: str,
                  instructions: str) -> bool:
        strategy = self._strategy_for(chat_id, run_id)
        if strategy is None or decision not in ("proceed", "research"):
            self.sessions.append(chat_id, "assistant", "error",
                                 "This chat has no GTM strategy for that run to plan from.")
            return False
        return self._plan(job_id, chat_id, run_id, strategy, instructions,
                          cast(Literal["proceed", "research"], decision))

    def _strategy_for(self, chat_id: str, run_id: str) -> JsonObject | None:
        try:
            saved = self.results.load_strategy(run_id)
        except ValueError:
            return None
        if saved is not None:
            return saved
        for message in reversed(self.sessions.messages(chat_id)):
            if message["kind"] == "strategy" and message["run_id"] == run_id:
                return cast(JsonObject, message["payload"].get("strategy"))
        return None

    def _plan(self, job_id: str, chat_id: str, run_id: str, strategy: JsonObject,
              instructions: str, decision: Literal["proceed", "research"] | None) -> bool:
        if self.pm is None:
            return True
        step = _Step(self, job_id, chat_id, "pm")
        try:
            result = cast(JsonObject, self.pm.run(strategy, decision=decision,
                                                  instructions=instructions,
                                                  progress=step.progress))
        except Exception as exc:  # noqa: BLE001 - keep the strategy in the chat
            logger.exception("PM failed in chat %s", chat_id)
            step.finish(False)
            self.sessions.append(chat_id, "assistant", "error",
                                 f"PM failed: {type(exc).__name__}: {exc}"[:300])
            return False
        self.results.save_pm(run_id, result)
        status = str(result.get("status"))
        labels = {"hitl_required": "PM needs your decision",
                  "research_requested": "PM sent the gaps back to Research"}
        step.finish(True, labels.get(status))
        self.sessions.append(chat_id, "assistant", "pm",
                             PM_TEXT.get(status, "Here is the use case and action plan."),
                             run_id=run_id, payload={"result": result})
        return True
