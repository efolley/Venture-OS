"""VentureOS pipeline: runs Research, the GTM orchestrator, and the PM agent in order."""

from .runner import PipelineResult, run_pipeline

__all__ = ["PipelineResult", "run_pipeline"]
__version__ = "0.3.0"
