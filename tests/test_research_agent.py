"""Runs the real DeepAgents loop with a scripted chat model (no network, no API key)."""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Callable, cast

sys.path.insert(0, str(Path(__file__).parent))

from test_research import SITE, FakeSearch, ignore_progress, make_claims  # noqa: E402

from ventureos.research import ResearchEngine  # noqa: E402
from ventureos.research.workspace import ResearchWorkspace  # noqa: E402

try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from ventureos.research.agent import build_tools, deepagents_runner
    import deepagents  # noqa: F401
except ImportError:  # needs Python 3.11+ and the agent extra
    BaseChatModel = None  # type: ignore[assignment,misc]


Step = Callable[[], Any]


if BaseChatModel is not None:

    class ScriptedChat(BaseChatModel):  # type: ignore[misc]
        steps: list[Any]
        calls: int = 0

        def bind_tools(self, tools: Any, **_kwargs: Any) -> "ScriptedChat":
            return self

        @property
        def _llm_type(self) -> str:
            return "scripted"

        def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **_kwargs: Any) -> Any:
            step = self.steps[min(self.calls, len(self.steps) - 1)]
            self.calls += 1
            message = step() if callable(step) else step
            return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, number: int, **args: object) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"call-{name}-{number}"}


@unittest.skipIf(BaseChatModel is None, "deepagents is not installed (needs Python 3.11+)")
class DeepAgentsLoopTests(unittest.TestCase):
    def workspace(self) -> ResearchWorkspace:
        workspace = ResearchWorkspace("Acme Cloud", SITE, FakeSearch())
        workspace.seed_main_site()
        return workspace

    def test_tools_have_clear_names_and_signatures(self):
        names = [tool.__name__ for tool in build_tools(self.workspace())]
        self.assertEqual(names, ["field_status", "search_web", "read_source", "add_claim",
                                 "reject_source", "note_uncertainty", "set_company"])

    def test_agent_searches_records_claims_and_fills_every_field(self):
        workspace = self.workspace()

        def claim_calls() -> Any:
            usable = cast(list, workspace.evidence)
            claims = make_claims(usable, 3)
            return AIMessage(content="", tool_calls=[
                tool_call("add_claim", i, **claim) for i, claim in enumerate(claims)])

        model = ScriptedChat(steps=[
            AIMessage(content="", tool_calls=[tool_call("search_web", 1, query="acme market competitors trends")]),
            claim_calls,
            AIMessage(content="All fields are filled."),
        ])
        events: list[str] = []
        runner = deepagents_runner(model)
        runner(workspace, lambda module, _i, _o, _s: events.append(module))
        status = workspace.field_status()
        self.assertTrue(status["complete"], status)
        self.assertEqual(status["missing_categories"], [])
        self.assertGreaterEqual(len(status["external_sites"]), 3)  # type: ignore[arg-type]
        self.assertEqual(events, ["collecting", "analyzing"])
        brief, _ = workspace.finish()
        self.assertEqual(brief["gaps"], [])

    def test_loop_reprompts_until_no_progress_when_fields_stay_empty(self):
        workspace = self.workspace()
        model = ScriptedChat(steps=[
            AIMessage(content="", tool_calls=[tool_call("search_web", 1, query="acme")]),
            AIMessage(content="I am done."),
        ])
        events: list[str] = []
        deepagents_runner(model)(workspace, lambda module, _i, _o, _s: events.append(module))
        self.assertFalse(workspace.field_status()["complete"])
        # pass 1 searched (progress), pass 2 changed nothing (stop)
        self.assertEqual(events.count("collecting"), 2)

    def test_engine_runs_the_deepagents_loop_end_to_end(self):
        holder: dict[str, ResearchWorkspace] = {}
        search = FakeSearch()

        def claim_calls() -> Any:
            claims = make_claims(cast(list, holder["ws"].evidence), 3)
            return AIMessage(content="", tool_calls=[tool_call("add_claim", i, **c) for i, c in enumerate(claims)])

        model = ScriptedChat(steps=[
            AIMessage(content="", tool_calls=[tool_call("search_web", 1, query="acme market")]),
            claim_calls,
            AIMessage(content="Done."),
        ])
        real_init = ResearchWorkspace.__init__

        def capture(self: ResearchWorkspace, *args: Any, **kwargs: Any) -> None:
            real_init(self, *args, **kwargs)
            holder["ws"] = self

        from unittest.mock import patch
        from test_research import FakeModel
        with patch.object(ResearchWorkspace, "__init__", capture):
            engine = ResearchEngine(FakeModel(), search, chat_model=model)
            brief, evidence = engine.research("Acme Cloud", SITE, ignore_progress)
        self.assertEqual(brief["gaps"], [])
        self.assertEqual(json.dumps(search.calls[0][1]), '["acme.example.com"]')
        self.assertEqual(len(evidence), 4)


if __name__ == "__main__":
    unittest.main()
