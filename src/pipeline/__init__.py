"""VentureOS pipeline: runs Research, the GTM orchestrator, and the PM agent in order, and
keeps chats (stored transcripts) that a person can reopen and continue."""

from .runner import PipelineResult, run_pipeline

__all__ = ["PipelineResult", "run_pipeline"]
__version__ = "0.4.0"
