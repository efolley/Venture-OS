"""Load and validate Research evidence packs for downstream GTM analysis."""

import json
from pathlib import Path
from typing import cast

from research.pack import validate_pack

from research.contracts import JsonObject


def as_object(value: object, message: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(message)
    entries = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in entries):
        raise ValueError(message)
    return cast(JsonObject, entries)


def load_research_pack(path: str | Path) -> JsonObject:
    """Read a JSON Research pack and validate its schema and cross-references."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Could not read Research input: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Research input is not valid JSON: {error}") from error

    return validate_research_pack(value)


def validate_research_pack(value: object) -> JsonObject:
    """Validate an already-loaded Research pack before any sub-agent receives it."""
    pack = as_object(value, "Research input must be a JSON object.")
    validate_pack(pack)

    evidence = pack.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("Research input evidence must be a list.")
    evidence_ids: list[str] = []
    for value in cast(list[object], evidence):
        item = as_object(value, "Research evidence item must be an object.")
        evidence_id = item.get("id")
        if not isinstance(evidence_id, str):
            raise ValueError("Every evidence item must have a string ID.")
        evidence_ids.append(evidence_id)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("Research input contains duplicate evidence IDs.")

    return pack


def evidence_id_index(pack: JsonObject) -> dict[str, JsonObject]:
    """Create the evidence-ID lookup used for citation validation."""
    evidence = pack.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("Research input evidence must be a list.")
    index: dict[str, JsonObject] = {}
    for value in cast(list[object], evidence):
        item = as_object(value, "Research evidence item must be an object.")
        evidence_id = item.get("id")
        if not isinstance(evidence_id, str) or evidence_id in index:
            raise ValueError("Research input evidence IDs must be unique strings.")
        index[evidence_id] = item
    return index
