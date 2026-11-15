"""Assemble and validate the evidence pack. Values are evidence IDs, never free text."""

import json
from pathlib import Path
from typing import cast

from . import checklist
from .contracts import (
    FIELDS, PRICING_STATUSES, SCHEMA_VERSION, TAGS, CompanyField, Competitor, EvidenceItem,
    EvidencePack, FieldCoverage, JsonObject, RejectedSource, Source, SourceRef,
)
from .sources import name_key, public_https_url

SCHEMA_PATH = Path(__file__).with_name("pack.schema.json")


def _ids(evidence: list[EvidenceItem], tag: str) -> list[str]:
    return [item["id"] for item in evidence if tag in item["tags"]]


def competitors(
    evidence: list[EvidenceItem], pricing_checked: set[str], known_websites: dict[str, str]
) -> list[Competitor]:
    """Group competitor-tagged items by name, then keep the 5 named by the most sources.

    Ranking by distinct sources (ties by first seen) keeps direct rivals named across several
    alternatives pages ahead of a name that appears on a single list.
    """
    grouped: dict[str, Competitor] = {}
    sources_by: dict[str, set[str]] = {}
    for item in evidence:
        ref = item["competitor"]
        if ref is None:
            continue
        key = name_key(ref["name"])
        if key not in grouped:
            grouped[key] = {
                "name": ref["name"], "website": "", "evidence_ids": [],
                "positioning": [], "pricing": [], "pricing_status": "not_checked",
            }
            sources_by[key] = set()
        entry = grouped[key]
        sources_by[key].add(item["source_id"])
        entry["website"] = entry["website"] or ref["website"]
        entry["evidence_ids"].append(item["id"])
        if "competitors.positioning" in item["tags"]:
            entry["positioning"].append(item["id"])
        if "competitors.pricing" in item["tags"]:
            entry["pricing"].append(item["id"])
    order = list(grouped)
    ranked = sorted(order, key=lambda k: (-len(sources_by[k]), order.index(k)))
    grouped = {key: grouped[key] for key in ranked[:checklist.MAX_COMPETITORS]}
    for key, entry in grouped.items():
        entry["website"] = entry["website"] or known_websites.get(key, "")
        if entry["pricing"]:
            entry["pricing_status"] = "found"
        elif key in pricing_checked:
            entry["pricing_status"] = "not_published"
    return list(grouped.values())


def fields(
    name: str, website: str, evidence: list[EvidenceItem],
    pricing_checked: set[str], known_websites: dict[str, str],
) -> tuple[CompanyField, dict[str, list[str]], list[Competitor], dict[str, list[str]]]:
    company: CompanyField = {
        "name": name, "website": website,
        **{key: _ids(evidence, f"company.{key}") for key in ("offering", "mission", "vision", "problem")},
    }  # type: ignore[typeddict-item]
    market = {key: _ids(evidence, f"market.{key}") for key in ("category", "size_growth", "trends")}
    sales = {key: _ids(evidence, f"sales.{key}") for key in (
        "target_customer", "buyer_role", "pricing_model", "channel", "buying_signals")}
    return company, market, competitors(evidence, pricing_checked, known_websites), sales


def build_pack(
    *,
    run_id: str,
    parent_run_id: str | None,
    name: str,
    website: str,
    evidence: list[EvidenceItem],
    sources: list[Source],
    pricing_checked: set[str],
    known_websites: dict[str, str],
    rejected: list[RejectedSource],
    uncertainties: list[str],
    limits_hit: list[str],
) -> EvidencePack:
    company, market, rivals, sales = fields(name, website, evidence, pricing_checked, known_websites)
    cov = checklist.coverage(company, market, rivals, sales)
    complete = all(field["status"] == "complete" for field in cov.values())
    refs: list[SourceRef] = [{
        "id": s["id"], "url": s["url"], "title": s["title"], "kind": s["kind"],
        "retrieved_at": s["retrieved_at"], "published_at": s["published_at"],
    } for s in sources]
    pack: EvidencePack = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "status": "complete" if complete else "partial",
        "company": company,
        "market": market,
        "competitors": rivals,
        "sales": sales,
        "evidence": evidence,
        "sources": refs,
        "coverage": cov,
        "limits_hit": limits_hit,
        "uncertainties": uncertainties[:20],
        "rejected_sources": rejected,
    }
    validate_pack(cast(JsonObject, pack))
    return pack


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid evidence pack: {message}")


def _id_list(value: object, known: set[str], where: str) -> None:
    _require(isinstance(value, list), f"{where} must be a list")
    for item in cast(list[object], value):
        _require(isinstance(item, str) and item in known, f"{where} cites an unknown evidence id")


def validate_pack(pack: JsonObject) -> None:
    """Structural and cross-reference checks matching pack.schema.json."""
    _require(pack.get("schema_version") == SCHEMA_VERSION, "wrong schema_version")
    _require(pack.get("status") in ("complete", "partial"), "status must be complete or partial")
    sources = pack.get("sources")
    _require(isinstance(sources, list), "sources must be a list")
    source_ids: set[str] = set()
    for source in cast(list[JsonObject], sources):
        public_https_url(source.get("url"))
        _require(isinstance(source.get("id"), str), "source id must be a string")
        source_ids.add(cast(str, source["id"]))
    evidence = pack.get("evidence")
    _require(isinstance(evidence, list), "evidence must be a list")
    evidence_ids: set[str] = set()
    for item in cast(list[JsonObject], evidence):
        _require(item.get("source_id") in source_ids, "evidence cites an unknown source")
        tags = item.get("tags")
        _require(isinstance(tags, list) and bool(tags) and all(t in TAGS for t in tags),
                 "evidence has invalid tags")
        _require(item.get("id") not in evidence_ids, "duplicate evidence id")
        evidence_ids.add(cast(str, item["id"]))
    company = cast(JsonObject, pack.get("company"))
    for key in ("offering", "mission", "vision", "problem"):
        _id_list(company.get(key), evidence_ids, f"company.{key}")
    for field in ("market", "sales"):
        values = pack.get(field)
        _require(isinstance(values, dict), f"{field} must be an object")
        for key, ids in cast(JsonObject, values).items():
            _require(f"{field}.{key}" in TAGS, f"{field}.{key} is not a known item")
            _id_list(ids, evidence_ids, f"{field}.{key}")
    rivals = pack.get("competitors")
    _require(isinstance(rivals, list) and len(rivals) <= checklist.MAX_COMPETITORS,
             "competitors must be a list of at most 5")
    for rival in cast(list[JsonObject], rivals):
        for key in ("evidence_ids", "positioning", "pricing"):
            _id_list(rival.get(key), evidence_ids, f"competitors.{key}")
        _require(rival.get("pricing_status") in PRICING_STATUSES, "invalid pricing_status")
    coverage = cast(dict[str, FieldCoverage], pack.get("coverage"))
    _require(isinstance(coverage, dict) and set(coverage) == set(FIELDS),
             "coverage must list every field")


def schema() -> JsonObject:
    return cast(JsonObject, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def gtm_gaps(pack: EvidencePack) -> list[str]:
    """What still blocks a GTM agent: every section needs at least 1 cited item, the company
    needs offering, mission, and problem, and 3 competitors need positioning. Buying signals
    and vision are optional. Empty means ready."""
    problems = [f"company.{key}" for key in checklist.COMPANY_REQUIRED if not pack["company"][key]]
    for field_name in ("market", "sales"):
        values = cast(dict[str, list[str]], pack[field_name])  # type: ignore[literal-required]
        problems += [f"{field_name}.{key}" for key, ids in values.items()
                     if key != "buying_signals" and not ids]
    described = [c for c in pack["competitors"] if c["positioning"]]
    if len(described) < checklist.MIN_COMPETITORS:
        problems.append(f"competitors ({len(described)} of {checklist.MIN_COMPETITORS} described)")
    return problems
