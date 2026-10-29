"""Role registry. Agent implementations and tool adapters are not connected."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    deliverable: str


AGENTS = (
    AgentSpec("web_intelligence", "Web Intelligence", "Sourced evidence brief"),
    AgentSpec("competitive_strategy", "Competitive Strategy", "Opportunity assessment"),
    AgentSpec("challenger_salesman", "Challenger Salesman", "ICP, offer, and outreach drafts"),
    AgentSpec("presentation_builder", "Presentation Builder", "Reviewed proposal"),
    AgentSpec("product_builder", "Product Builder", "Scoped and tested prototype"),
    AgentSpec("workflow_automation", "Workflow Automation", "Action records and outcome data"),
)
