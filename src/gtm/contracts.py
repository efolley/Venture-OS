"""Structured contracts and validators for GTM sub-agent results."""

from typing import Literal, TypedDict, cast

from research.contracts import JsonObject

SUB_AGENTS = ("market_analysis", "competitive_strategy", "challenger_salesman")
RANKED_SUB_AGENT = "competitive_strategy"
SUB_SCORE_KEYS = ("pain", "gap_size", "competitor_weakness", "fit")
STRATEGY_SCHEMA_VERSION = 4
RecommendationBasis = Literal["evidence_based", "hypothesis"]


class _RecommendationBase(TypedDict):
    title: str
    recommendation: str
    rationale: str
    basis: RecommendationBasis
    evidence_ids: list[str]


class Recommendation(_RecommendationBase, total=False):
    # Competitive strategy only: the model proposes sub_scores, code computes score and rank.
    sub_scores: dict[str, int]
    disconfirming_evidence: str
    validation_question: str
    score: int
    rank: int


class SuccessfulSubAgentResult(TypedDict):
    name: str
    status: Literal["complete"]
    recommendations: list[Recommendation]
    gaps: list[str]


class FailedSubAgentResult(TypedDict):
    name: str
    status: Literal["failed"]
    recommendations: list[Recommendation]
    gaps: list[str]
    error: str


SubAgentResult = SuccessfulSubAgentResult | FailedSubAgentResult


class StrategyPack(TypedDict):
    schema_version: int
    input_run_id: str
    company: dict[str, str]
    research_status: str
    status: str
    research_gaps: list[str]
    gaps: list[str]
    sub_agents: dict[str, SubAgentResult]
    recommendations: list[dict[str, object]]
    themes: list[dict[str, object]]
    merge: dict[str, str]
    snapshot: dict[str, object]


def _text(value: object, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value.strip()


def _text_list(value: object, message: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(message)
    items = cast(list[object], value)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise ValueError(message)
    return [item.strip() for item in cast(list[str], items)]


def _sub_scores(value: object, label: str) -> dict[str, int]:
    message = f"{label} needs sub_scores {', '.join(SUB_SCORE_KEYS)} as integers 1 to 5."
    if not isinstance(value, dict):
        raise ValueError(message)
    raw = cast(dict[object, object], value)
    if set(raw) != set(SUB_SCORE_KEYS):
        raise ValueError(message)
    scores: dict[str, int] = {}
    for key in SUB_SCORE_KEYS:
        score = raw[key]
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError(message)
        scores[key] = score
    return scores


def rank_hypotheses(hypotheses: list[Recommendation]) -> list[Recommendation]:
    """Score and rank in code: score is the sum of the 4 sub-scores (4 to 20).

    Ties break by pain, then by evidence count, then by the model's original order.
    Any score or rank the model supplied is ignored.
    """
    scored: list[Recommendation] = []
    for hypothesis in hypotheses:
        sub_scores = hypothesis["sub_scores"]
        scored.append({**hypothesis, "score": sum(sub_scores[key] for key in SUB_SCORE_KEYS)})
    ordered = sorted(
        enumerate(scored),
        key=lambda pair: (
            -pair[1]["score"],
            -pair[1]["sub_scores"]["pain"],
            -len(pair[1]["evidence_ids"]),
            pair[0],
        ),
    )
    return [{**hypothesis, "rank": rank} for rank, (_, hypothesis) in enumerate(ordered, start=1)]


def validate_sub_agent_result(
    name: str,
    value: object,
    allowed_evidence_ids: set[str],
) -> SubAgentResult:
    """Validate one model result and reject missing or invented evidence citations."""
    if name not in SUB_AGENTS:
        raise ValueError(f"Unknown GTM sub-agent: {name}.")
    if not isinstance(value, dict):
        raise ValueError(f"{name} returned a non-object result.")
    raw = cast(dict[object, object], value)
    recommendations_value = raw.get("recommendations")
    if not isinstance(recommendations_value, list):
        raise ValueError(f"{name} recommendations must be a list.")

    recommendations: list[Recommendation] = []
    for index, item in enumerate(cast(list[object], recommendations_value)):
        if not isinstance(item, dict):
            raise ValueError(f"{name} recommendation {index + 1} must be an object.")
        recommendation = cast(dict[object, object], item)
        basis = recommendation.get("basis")
        if basis not in ("evidence_based", "hypothesis"):
            raise ValueError(f"{name} recommendation {index + 1} has an invalid basis.")
        evidence_ids = _text_list(
            recommendation.get("evidence_ids"),
            f"{name} recommendation {index + 1} must cite evidence IDs.",
        )
        if not evidence_ids:
            raise ValueError(f"{name} recommendation {index + 1} must cite evidence IDs.")
        unknown = set(evidence_ids) - allowed_evidence_ids
        if unknown:
            raise ValueError(
                f"{name} recommendation {index + 1} cites unknown evidence IDs: "
                f"{', '.join(sorted(unknown))}."
            )
        clean: Recommendation = {
            "title": _text(
                recommendation.get("title"),
                f"{name} recommendation {index + 1} needs a title.",
            ),
            "recommendation": _text(
                recommendation.get("recommendation"),
                f"{name} recommendation {index + 1} needs a recommendation.",
            ),
            "rationale": _text(
                recommendation.get("rationale"),
                f"{name} recommendation {index + 1} needs a rationale.",
            ),
            "basis": basis,
            "evidence_ids": evidence_ids,
        }
        if name == RANKED_SUB_AGENT:
            label = f"{name} hypothesis {index + 1}"
            clean["sub_scores"] = _sub_scores(recommendation.get("sub_scores"), label)
            clean["disconfirming_evidence"] = _text(
                recommendation.get("disconfirming_evidence"),
                f"{label} needs disconfirming_evidence.",
            )
            clean["validation_question"] = _text(
                recommendation.get("validation_question"),
                f"{label} needs a validation_question.",
            )
        recommendations.append(clean)

    if name == RANKED_SUB_AGENT:
        recommendations = rank_hypotheses(recommendations)
    gaps = _text_list(raw.get("gaps", []), f"{name} gaps must be a list of strings.")
    return {
        "name": name,
        "status": "complete",
        "recommendations": recommendations,
        "gaps": gaps,
    }


def validate_strategy_pack(value: object, allowed_evidence_ids: set[str]) -> StrategyPack:
    """Validate the merged pack's top-level shape and all recommendation citations."""
    if not isinstance(value, dict):
        raise ValueError("GTM strategy pack must be a JSON object.")
    raw = cast(dict[object, object], value)
    if raw.get("schema_version") != STRATEGY_SCHEMA_VERSION:
        raise ValueError("GTM strategy pack has an unsupported schema version.")

    sub_agents_value = raw.get("sub_agents")
    if not isinstance(sub_agents_value, dict):
        raise ValueError("GTM strategy pack sub_agents must be an object.")
    sub_agents_raw = cast(dict[object, object], sub_agents_value)
    if set(sub_agents_raw) != set(SUB_AGENTS):
        raise ValueError("GTM strategy pack must include all 3 sub-agents.")
    sub_agents: dict[str, SubAgentResult] = {}
    for name in SUB_AGENTS:
        result_value = sub_agents_raw[name]
        if not isinstance(result_value, dict):
            raise ValueError(f"GTM sub-agent {name} result must be an object.")
        result_object = cast(JsonObject, result_value)
        result_raw = cast(dict[object, object], result_object)
        if result_raw.get("status") == "failed":
            error = _text(result_raw.get("error"), f"Failed sub-agent {name} needs an error.")
            sub_agents[name] = {
                "name": name,
                "status": "failed",
                "recommendations": [],
                "gaps": _text_list(
                    result_raw.get("gaps", []),
                    f"{name} gaps must be a list of strings.",
                ),
                "error": error,
            }
        else:
            sub_agents[name] = validate_sub_agent_result(
                name,
                result_object,
                allowed_evidence_ids,
            )

    merged = raw.get("recommendations")
    if not isinstance(merged, list):
        raise ValueError("GTM strategy pack recommendations must be a list.")
    recommendation_ids: list[str] = []
    for item in cast(list[object], merged):
        if not isinstance(item, dict):
            raise ValueError("Merged recommendations must be objects.")
        recommendation = cast(dict[object, object], item)
        agent = recommendation.get("agent")
        if not isinstance(agent, str) or agent not in SUB_AGENTS:
            raise ValueError("Merged recommendation has an unknown agent.")
        recommendation_id = recommendation.get("id")
        if not isinstance(recommendation_id, str) or recommendation_id in recommendation_ids:
            raise ValueError("Merged recommendations need unique string IDs.")
        recommendation_ids.append(recommendation_id)
        recommendation_value: JsonObject = {
            str(key): field
            for key, field in recommendation.items()
            if key not in ("id", "agent", "score", "rank")
        }
        sub_agent_value: JsonObject = {"recommendations": [recommendation_value]}
        validate_sub_agent_result(
            agent,
            sub_agent_value,
            allowed_evidence_ids,
        )

    themes_value = raw.get("themes")
    if not isinstance(themes_value, list):
        raise ValueError("GTM strategy pack themes must be a list.")
    themed: list[str] = []
    for item in cast(list[object], themes_value):
        if not isinstance(item, dict):
            raise ValueError("Each theme must be an object.")
        theme = cast(dict[object, object], item)
        _text(theme.get("title"), "Each theme needs a title.")
        themed.extend(_text_list(theme.get("recommendation_ids"), "Theme IDs must be a list."))
    if sorted(themed) != sorted(recommendation_ids):
        raise ValueError("Every recommendation must belong to exactly 1 theme.")
    merge_value = raw.get("merge")
    if not isinstance(merge_value, dict) or cast(dict[object, object], merge_value).get(
        "status"
    ) not in ("merged", "fallback"):
        raise ValueError("GTM strategy pack merge status must be merged or fallback.")

    snapshot_value = raw.get("snapshot")
    if not isinstance(snapshot_value, dict) or cast(dict[object, object], snapshot_value).get(
        "status"
    ) not in ("complete", "partial", "fallback"):
        raise ValueError("GTM strategy pack snapshot status must be complete, partial, or fallback.")

    company_value = raw.get("company")
    if not isinstance(company_value, dict):
        raise ValueError("GTM strategy pack company must be an object.")
    company_raw = cast(dict[object, object], company_value)
    company = {
        "name": _text(company_raw.get("name"), "GTM strategy pack needs a company name."),
        "website": _text(company_raw.get("website"), "GTM strategy pack needs a company website."),
    }
    research_gaps = _text_list(raw.get("research_gaps"), "research_gaps must be a list.")
    gaps = _text_list(raw.get("gaps"), "gaps must be a list.")
    if raw.get("status") not in ("complete", "partial"):
        raise ValueError("GTM strategy pack status must be complete or partial.")
    if raw.get("research_status") not in ("complete", "partial"):
        raise ValueError("GTM strategy pack research_status must be complete or partial.")

    return cast(StrategyPack, {
        "schema_version": STRATEGY_SCHEMA_VERSION,
        "input_run_id": _text(raw.get("input_run_id"), "GTM strategy pack needs input_run_id."),
        "company": company,
        "research_status": raw["research_status"],
        "status": raw["status"],
        "research_gaps": research_gaps,
        "gaps": gaps,
        "sub_agents": sub_agents,
        "recommendations": cast(list[dict[str, object]], merged),
        "themes": cast(list[dict[str, object]], themes_value),
        "merge": cast(dict[str, str], merge_value),
        "snapshot": cast(dict[str, object], snapshot_value),
    })
