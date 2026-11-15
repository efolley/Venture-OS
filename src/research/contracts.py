"""Typed contracts for the Research agent: sources, evidence items, and the evidence pack.

The agent gathers and organizes evidence only. Downstream agents cite the evidence
IDs defined here; anything they write without a citation is a hypothesis.
"""

from dataclasses import asdict, dataclass
from typing import Protocol, TypedDict

JsonObject = dict[str, object]

SCHEMA_VERSION = 4
BASES: tuple[str, ...] = ("fact", "inference")
SOURCE_KINDS: tuple[str, ...] = (
    "first_party", "competitor", "market_report", "aggregator", "review", "forum", "reference", "news", "other",
)
FIELDS: tuple[str, ...] = ("company", "market", "competitors", "sales")
TAGS: tuple[str, ...] = (
    "company.offering",
    "company.mission",
    "company.vision",
    "company.problem",
    "market.category",
    "market.size_growth",
    "market.trends",
    "competitors.alternative",
    "competitors.positioning",
    "competitors.pricing",
    "sales.target_customer",
    "sales.buyer_role",
    "sales.pricing_model",
    "sales.channel",
    "sales.buying_signals",
)
TAG_HELP: dict[str, str] = {
    "company.offering": "what the researched company sells",
    "company.mission": "the researched company's stated mission: what it exists to do (often on "
                       "its about or company page, for example 'our mission is to ...')",
    "company.vision": "the researched company's stated vision: the future it wants to create "
                      "(for example 'we envision a world where ...')",
    "company.problem": "the problem the researched company says it solves for its customers "
                       "(for example 'teams waste hours switching between tools')",
    "market.category": "the market category the company competes in",
    "market.size_growth": "a market size, growth rate, or growth signal",
    "market.trends": "a trend shaping this market",
    "competitors.alternative": "a named product that buyers compare with or use instead of the "
                               "researched company's main product, in the same category (not an "
                               "integration, partner, acquired company, or the page's publisher)",
    "competitors.positioning": "how a named competitor positions itself",
    "competitors.pricing": "a named competitor's price or plan",
    "sales.target_customer": "the researched company's target customer or segment "
                             "(for example: startups, enterprises, software teams of 50 to 500)",
    "sales.buyer_role": "the role or team that uses, champions, or buys it (for example: "
                        "'built for engineering teams', 'product managers', 'CTOs', 'for developers')",
    "sales.pricing_model": "the researched company's pricing model (per seat, flat, usage, free tier)",
    "sales.channel": "how customers buy (self-serve: 'start for free', 'sign up', free trial; "
                     "sales-led: 'contact sales', 'book a demo', enterprise plan; partners, marketplaces)",
    "sales.buying_signals": "hiring, funding, launches, or other buying signals",
}
RUN_STATUSES: tuple[str, ...] = ("running", "clarify", "complete", "partial", "failed")
PRICING_STATUSES: tuple[str, ...] = ("found", "not_published", "not_checked")


@dataclass(frozen=True)
class Limits:
    rounds: int = 12
    sources: int = 36
    model_calls: int = 36

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class _SearchResultRequired(TypedDict):
    url: str
    title: str
    text: str


class SearchResult(_SearchResultRequired, total=False):
    published_at: str


class Source(TypedDict):
    id: str
    url: str
    title: str
    kind: str
    text: str
    retrieved_at: str
    published_at: str | None
    round: int


class SourceRef(TypedDict):
    id: str
    url: str
    title: str
    kind: str
    retrieved_at: str
    published_at: str | None


class RejectedSource(TypedDict):
    url: str
    reason: str
    round: int


class CompetitorRef(TypedDict):
    name: str
    website: str


class EvidenceItem(TypedDict):
    id: str
    statement: str
    excerpt: str
    basis: str
    tags: list[str]
    source_id: str
    url: str
    retrieved_at: str
    published_at: str | None
    competitor: CompetitorRef | None
    round: int


class Competitor(TypedDict):
    name: str
    website: str
    evidence_ids: list[str]
    positioning: list[str]
    pricing: list[str]
    pricing_status: str


class FieldCoverage(TypedDict):
    status: str
    missing: list[str]


class CompanyField(TypedDict):
    name: str
    website: str
    offering: list[str]
    mission: list[str]
    vision: list[str]
    problem: list[str]


class EvidencePack(TypedDict):
    schema_version: int
    run_id: str
    parent_run_id: str | None
    status: str
    company: CompanyField
    market: dict[str, list[str]]
    competitors: list[Competitor]
    sales: dict[str, list[str]]
    evidence: list[EvidenceItem]
    sources: list[SourceRef]
    coverage: dict[str, FieldCoverage]
    limits_hit: list[str]
    uncertainties: list[str]
    rejected_sources: list[RejectedSource]


class Model(Protocol):
    def json(self, system: str, prompt: str) -> JsonObject: ...


class SearchProvider(Protocol):
    def search(
        self, query: str, limit: int = 5, *, include_domains: list[str] | None = None
    ) -> list[SearchResult]: ...


class Progress(Protocol):
    def __call__(self, step: str, data: JsonObject, status: str) -> None: ...


def no_progress(step: str, data: JsonObject, status: str) -> None:
    del step, data, status
