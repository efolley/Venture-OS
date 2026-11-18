"""Contracts for the PM agent: the GTM strategy pack it reads and the PM result it writes.

The PM agent is self-contained. It does not import the GTM or Research packages; it only
reads a GTM strategy pack (schema v4) as JSON and validates the parts it uses.
"""

from typing import Literal, Protocol, TypedDict, cast

JsonObject = dict[str, object]

INPUT_SCHEMA_VERSION = 4  # GTM strategy pack
RESULT_SCHEMA_VERSION = 2  # PM result (v2: one_pager and mvp_idea)
SUB_AGENTS = ("market_analysis", "competitive_strategy", "challenger_salesman")
SNAPSHOT_LINES = (
    "mission", "vision", "problem", "target_market", "icp", "product", "client_value",
    "market_brief", "competitive_landscape",
)

PMStatus = Literal["complete", "partial", "hitl_required", "research_requested"]
Decision = Literal["proceed", "research"]


class Model(Protocol):
    def json(self, system: str, prompt: str) -> JsonObject: ...


class Check(TypedDict):
    id: str
    label: str
    passed: bool
    required: bool
    detail: str


class Baseline(TypedDict):
    status: Literal["pass", "fail"]
    checks: list[Check]
    missing: list[str]
    research_gaps: list[str]


class Part(TypedDict):
    text: str
    based_on: list[str]


class Alternative(TypedDict):
    statement: str
    why_not: str


class UseCase(TypedDict):
    """The 1 use case PM establishes before anything is built."""
    icp: Part
    core_problem: Part
    mvp_solution: Part
    statement: str  # built in code: "Help {icp} solve {core_problem} with {mvp_solution}."
    why: str
    why_based_on: list[str]
    key_assumption: str
    alternatives: list[Alternative]


class Action(TypedDict):
    id: str
    purpose: str
    title: str
    description: str
    owner: str
    priority: int
    horizon: str
    success_metric: str
    based_on: list[str]


class Feature(TypedDict):
    name: str
    why: str
    based_on: list[str]


class OnePager(TypedDict):
    headline: str
    problem: str
    value_proposition: str
    target_customer: str
    key_points: list[str]
    proof_points: list[str]
    call_to_action: str
    based_on: list[str]


class MVPIdea(TypedDict):
    product_goal: str
    target_user: str
    core_job: str
    must_have_features: list[Feature]
    out_of_scope: list[str]
    success_criteria: list[str]
    demo_scenario: str
    based_on: list[str]


class Progress(Protocol):
    def __call__(self, step: str, data: JsonObject, status: str) -> None: ...


def no_progress(step: str, data: JsonObject, status: str) -> None:
    del step, data, status


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid GTM strategy pack: {message}")


def validate_strategy_pack(value: object) -> JsonObject:
    """Check the parts of a GTM strategy pack the PM agent reads. Raise ValueError if unusable."""
    _require(isinstance(value, dict), "it must be a JSON object")
    pack = cast(JsonObject, value)
    _require(pack.get("schema_version") == INPUT_SCHEMA_VERSION,
             f"schema_version must be {INPUT_SCHEMA_VERSION}")
    company = pack.get("company")
    _require(isinstance(company, dict) and isinstance(cast(JsonObject, company).get("name"), str),
             "company.name is required")
    for key in ("input_run_id", "status", "research_status"):
        _require(isinstance(pack.get(key), str), f"{key} is required")
    _require(isinstance(pack.get("gaps"), list), "gaps must be a list")
    snapshot = pack.get("snapshot")
    _require(isinstance(snapshot, dict), "snapshot is required")
    lines = cast(JsonObject, snapshot).get("lines")
    _require(isinstance(lines, dict), "snapshot.lines is required")
    for key in SNAPSHOT_LINES:
        line = cast(JsonObject, lines).get(key)
        _require(isinstance(line, dict) and cast(JsonObject, line).get("status") in ("found", "unknown"),
                 f"snapshot line {key} is missing or invalid")
    sub_agents = pack.get("sub_agents")
    _require(isinstance(sub_agents, dict) and set(cast(JsonObject, sub_agents)) == set(SUB_AGENTS),
             "sub_agents must list the 3 GTM sub-agents")
    recommendations = pack.get("recommendations")
    _require(isinstance(recommendations, list), "recommendations must be a list")
    seen: set[str] = set()
    for item in cast(list[object], recommendations):
        _require(isinstance(item, dict), "each recommendation must be an object")
        rec = cast(JsonObject, item)
        rec_id = rec.get("id")
        _require(isinstance(rec_id, str) and rec_id not in seen, "recommendation IDs must be unique")
        seen.add(cast(str, rec_id))
        _require(rec.get("agent") in SUB_AGENTS, f"recommendation {rec_id} has an unknown agent")
        for key in ("title", "recommendation"):
            _require(isinstance(rec.get(key), str), f"recommendation {rec_id} needs {key}")
    return pack


def recommendations(pack: JsonObject, agent: str | None = None) -> list[JsonObject]:
    items = cast(list[JsonObject], pack.get("recommendations") or [])
    return [item for item in items if agent is None or item.get("agent") == agent]


def citable_ids(pack: JsonObject) -> set[str]:
    """IDs a PM output may cite: recommendation IDs and every evidence ID the pack cites."""
    ids = {cast(str, item["id"]) for item in recommendations(pack)}
    for item in recommendations(pack):
        ids |= {i for i in cast(list[object], item.get("evidence_ids") or []) if isinstance(i, str)}
    lines = cast(dict[str, JsonObject], cast(JsonObject, pack["snapshot"])["lines"])
    for line in lines.values():
        for key in ("evidence_ids", "recommendation_ids"):
            ids |= {i for i in cast(list[object], line.get(key) or []) if isinstance(i, str)}
    return ids
