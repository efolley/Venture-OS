"""Central planning boundary. This scaffold never executes external actions."""
from ventureos.logging_utils import logged

from .agents import AGENTS
from .contracts import BusinessBrief, WorkflowPlan, WorkflowStep


class AgentHarness:
    @logged
    def plan(self, brief: BusinessBrief) -> WorkflowPlan:
        """Return a fixed reference workflow, not an AI-generated execution plan."""
        research, strategy, sales, proposal, product, automation = AGENTS
        return WorkflowPlan(brief, (
            WorkflowStep("research", research.id, research.deliverable),
            WorkflowStep("strategy", strategy.id, strategy.deliverable, ("research",)),
            WorkflowStep("offer", sales.id, sales.deliverable, ("strategy",)),
            WorkflowStep("review", "human", "Accept or revise evidence and offer", ("offer",)),
            WorkflowStep("proposal", proposal.id, proposal.deliverable, ("review",), "offer approved"),
            WorkflowStep("validation", "human", "Customer feedback and proceed/revise decision", ("proposal",)),
            WorkflowStep("prototype", product.id, product.deliverable, ("validation",), "customer evidence supports proceeding"),
            WorkflowStep("operations", automation.id, automation.deliverable, ("prototype",), "delivery and external actions approved"),
            WorkflowStep("outcomes", "human", "Compare outcomes to baseline; revise strategy", ("operations",)),
        ))

    @logged
    def execute(self, plan: WorkflowPlan) -> None:
        raise NotImplementedError(
            "Preview only: providers, evaluation, approvals, and durable execution are not implemented."
        )
