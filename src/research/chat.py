"""Chat sessions: turn user messages into research runs and follow-up questions.

The chat is deterministic. A message is a company name or a website. The agent asks
follow-up questions in 2 cases, and the next message answers them:

- clarify: the name matched more than 1 organization; reply with a number, name, or website.
- re-run: the pack is partial; reply "yes" to research only the missing items.
"""

import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import cast

from . import checklist
from .agent import ResearchAgent, RunResult
from .contracts import JsonObject, Progress, no_progress
from .sources import host, name_key, norm

_WEBSITE = re.compile(r"^(?:https?://\S+|(?:[\w-]+\.)+[A-Za-z]{2,}(?:/\S*)?)$")
_REQUEST_PREFIX = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+)?(?:research|look up|lookup|find|search|analy[sz]e|"
    r"investigate|check|tell me about|what about|info(?:rmation)? (?:on|about)|find info(?:rmation)? "
    r"(?:on|about))\s+(?:for\s+(?:me|us)\s+)?(?:(?:information|info|data)\s+(?:on|about|for)\s+)?"
    r"(?:the\s+)?",
    re.IGNORECASE,
)
_COMPANY_SUFFIX = re.compile(
    r"(?:\s+(?:for me|for us|please|pls|thanks|thank you|now|today))+$|"
    r"\s+(?:company|startup|business|firm|brand|website|site)$", re.IGNORECASE)
_YES = {"yes", "y", "yes please", "ok", "okay", "sure", "continue", "go", "research the gaps"}
_NO = {"no", "n", "no thanks", "cancel", "stop", "skip"}


@dataclass
class ChatSession:
    id: str
    history: list[JsonObject] = field(default_factory=list)
    pending: JsonObject | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def reply(kind: str, message: str, **extra: object) -> JsonObject:
    return {"kind": kind, "message": message, **extra}


class Chat:
    def __init__(self, agent: ResearchAgent) -> None:
        self.agent = agent

    def handle(self, session: ChatSession, message: str, instructions: str = "",
               progress: Progress = no_progress) -> JsonObject:
        text = norm(message)[:300]
        if not text:
            return reply("text", "Send a company name or website to research.")
        pending, session.pending = session.pending, None
        if pending and pending.get("kind") == "clarify":
            answer = self._answer_clarify(pending, text)
            if answer == "cancel":
                return reply("text", "OK. Send another company name or website.")
            if answer:
                chosen_name, chosen_site = answer
                typed = cast(str, pending["company"])
                return self._research(session, chosen_name, chosen_site, instructions, progress,
                                      aliases=[typed])
        if pending and pending.get("kind") == "rerun":
            lowered = text.casefold().strip(".! ")
            if lowered in _YES:
                return self._research(session, "", "", instructions, progress,
                                      parent_run_id=cast(str, pending["run_id"]))
            if lowered in _NO:
                return reply("text", "OK. The partial pack is saved. Send another company to research.")
        target = company_from_message(text)
        if _WEBSITE.match(target):
            return self._research(session, "", target, instructions, progress)
        return self._research(session, target, "", instructions, progress)

    @staticmethod
    def _answer_clarify(pending: JsonObject, text: str) -> tuple[str, str] | str | None:
        """Return (name, website) for the chosen option, "cancel", or None for a new request."""
        candidates = cast(list[JsonObject], pending.get("candidates") or [])
        corrected = cast(str, pending.get("corrected_name") or pending.get("company") or "")
        lowered = text.casefold().strip(".! ")
        if lowered in _NO:
            return "cancel"
        if lowered.isdigit() and 1 <= int(lowered) <= len(candidates):
            chosen = candidates[int(lowered) - 1]
            return cast(str, chosen["name"]) or corrected, cast(str, chosen["website"])
        for candidate in candidates:
            website = cast(str, candidate["website"])
            if name_key(text) == name_key(cast(str, candidate["name"])) or host(
                    text if "://" in text else f"https://{text}") == host(website):
                return cast(str, candidate["name"]) or corrected, website
        if _WEBSITE.match(text):
            return corrected, text
        return None

    def _research(self, session: ChatSession, company: str, website: str, instructions: str,
                  progress: Progress, parent_run_id: str | None = None,
                  aliases: list[str] | None = None) -> JsonObject:
        result = self.agent.run(company, website, instructions=instructions,
                                parent_run_id=parent_run_id, aliases=aliases, progress=progress)
        return self._result_reply(session, result, company)

    @staticmethod
    def _result_reply(session: ChatSession, result: RunResult, company: str) -> JsonObject:
        if result.status == "clarify":
            session.pending = {"kind": "clarify", "company": company, "candidates": result.candidates,
                               "corrected_name": result.corrected_name}
            lines = [result.message]
            lines += [f"{n}. {c['name']}: {c['website']}" for n, c in enumerate(result.candidates, 1)]
            lines.append("Reply with a number, a name, or a website." if result.candidates
                         else "Reply with the website.")
            return reply("clarify", "\n".join(lines), run_id=result.run_id,
                         candidates=result.candidates)
        pack = result.pack
        assert pack is not None
        name = pack["company"]["name"]
        if pack["status"] == "complete":
            message = f"Here is the evidence pack for {name}. Every field is complete."
        else:
            missing = checklist.all_missing(pack["coverage"])
            session.pending = {"kind": "rerun", "run_id": result.run_id, "gaps": missing}
            hit = f" Limit reached: {', '.join(pack['limits_hit'])}." if pack["limits_hit"] else ""
            message = (f"Here is a partial evidence pack for {name}.{hit} Missing: "
                       f"{', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}. "
                       "Reply yes to research only the missing items, or send another company.")
        return reply("pack", message, run_id=result.run_id, pack=pack)


def company_from_message(text: str) -> str:
    """Strip request phrasing: "Research Linear company" -> "Linear"."""
    target = text.strip().strip("?.!\"'")
    stripped = _REQUEST_PREFIX.sub("", target, count=1).strip()
    for _ in range(2):  # "Baseten company for me" needs both suffixes removed
        stripped = _COMPANY_SUFFIX.sub("", stripped).strip().strip("?.!\"',")
    return stripped or target


def new_session() -> ChatSession:
    return ChatSession(str(uuid.uuid4()))
