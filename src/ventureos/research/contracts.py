"""Typed contracts for the Research agent: sources, claims, and the evidence brief.

The Research agent gathers and cites evidence only. ICP, positioning, and strategy
belong to later agents, which should cite the claim IDs defined here.
"""

from typing import Protocol, TypedDict


JsonObject = dict[str, object]

BASES: tuple[str, ...] = ("fact", "inference")
CATEGORIES: tuple[str, ...] = (
    "company",
    "product",
    "pricing",
    "customers",
    "market",
    "competitors",
    "trends",
    "signals",
    "risks",
)
SOURCE_KINDS: tuple[str, ...] = (
    "first_party",
    "aggregator",
    "review",
    "forum",
    "reference",
    "news",
    "other",
)


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


class SourceRef(TypedDict):
    id: str
    url: str
    title: str
    kind: str
    retrieved_at: str
    published_at: str | None


class Claim(TypedDict):
    id: str
    text: str
    basis: str
    category: str
    source_id: str
    quote: str
    published_at: str | None
    dated: bool


class RejectedSource(TypedDict):
    url: str
    reason: str


class Company(TypedDict):
    name: str
    website: str


class Brief(TypedDict):
    schema_version: int
    company: Company
    sources: list[SourceRef]
    claims: list[Claim]
    coverage: dict[str, int]
    gaps: list[str]
    uncertainties: list[str]
    rejected_sources: list[RejectedSource]


class HistoryTurn(TypedDict):
    user: str
    assistant: JsonObject


class SessionState(TypedDict, total=False):
    history: list[HistoryTurn]
    brief: Brief
    evidence: list[Source]
    target: Company


class Model(Protocol):
    def json(self, system: str, prompt: str) -> JsonObject: ...


class SearchProvider(Protocol):
    def search(
        self, query: str, limit: int = 5, *, include_domains: list[str] | None = None
    ) -> list[SearchResult]: ...


class Progress(Protocol):
    def __call__(self, module: str, input_data: object, output_data: object, status: str) -> None: ...
