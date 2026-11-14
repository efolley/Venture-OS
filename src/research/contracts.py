"""Typed contracts for the Research agent: sources, evidence items, and the evidence pack.

The agent gathers and organizes evidence only. Downstream agents cite the evidence
IDs defined here; anything they write without a citation is a hypothesis.
"""

from dataclasses import asdict, dataclass
from typing import Protocol, TypedDict

JsonObject = dict[str, object]

SCHEMA_VERSION = 3
BASES: tuple[str, ...] = ("fact", "inference")
SOURCE_KINDS: tuple[str, ...] = (
    "first_party", "competitor", "aggregator", "review", "forum", "reference", "news", "other",
)
FIELDS: tuple[str, ...] = ("company", "market", "competitors", "sales")
TAGS: tuple[str, ...] = (
    "company.offering",
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
    "market.category": "the market category the company competes in",
    "market.size_growth": "a market size, growth rate, or growth signal",
    "market.trends": "a trend shaping this market",
    "competitors.alternative": "a named alternative or competitor product",
    "competitors.positioning": "how a named competitor positions itself",
    "competitors.pricing": "a named competitor's price or plan",
    "sales.target_customer": "the researched company's target customer or segment",
    "sales.buyer_role": "the role that buys or champions the product",
    "sales.pricing_model": "the researched company's pricing model (per seat, flat, usage, free tier)",
    "sales.channel": "how the company sells (self-serve, sales-led, partners)",
    "sales.buying_signals": "hiring, funding, launches, or other buying signals",
}
RUN_STATUSES: tuple[str, ...] = ("running", "clarify", "complete", "partial", "failed")
PRICING_STATUSES: tuple[str, ...] = ("found", "not_published", "not_checked")


@dataclass(frozen=True)
class Limits:
    rounds: int = 5
    sources: int = 15
    model_calls: int = 10

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
