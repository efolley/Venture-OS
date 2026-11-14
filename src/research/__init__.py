"""VentureOS Research agent: collects verified web evidence about a company into an evidence pack."""

from .agent import ResearchAgent, RunResult
from .contracts import Limits
from .store import MemoryStore, PostgresStore, default_store

__all__ = ["Limits", "MemoryStore", "PostgresStore", "ResearchAgent", "RunResult", "default_store"]
__version__ = "0.1.0"
