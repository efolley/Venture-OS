"""Typed contracts shared by the research engine and its provider adapters."""

from typing import Protocol, TypedDict


JsonObject = dict[str, object]


class SearchResult(TypedDict):
    url: str
    title: str
    text: str


class Evidence(SearchResult):
    retrieved_at: str


class Company(TypedDict):
    name: str
    website: str
    description: str


class Problem(TypedDict):
    statement: str
    pain_points: list[str]


class Market(TypedDict):
    industry: str
    category: str
    business_model: str


class ICP(TypedDict):
    primary: str
    buyer: str
    users: list[str]


class Solution(TypedDict):
    product: str
    approach: str


class Positioning(TypedDict):
    who: str
    what: str
    how: str
    statement: str


class Report(TypedDict):
    company: Company
    problem: Problem
    market: Market
    icp: ICP
    solution: Solution
    positioning: Positioning
    sources: list[str]


class HistoryTurn(TypedDict):
    user: str
    assistant: JsonObject


class SessionState(TypedDict, total=False):
    history: list[HistoryTurn]
    report: Report
    evidence: list[Evidence]
    target: Company


class Model(Protocol):
    def json(self, system: str, prompt: str) -> JsonObject: ...


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class Progress(Protocol):
    def __call__(self, module: str, input_data: object, output_data: object, status: str) -> None: ...
