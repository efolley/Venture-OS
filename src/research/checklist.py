"""The coverage checklist, computed in code from evidence tags. The model never decides it.

Missing entries use tag names (for example `market.trends`). Competitor details add the
competitor name after a colon (for example `competitors.pricing:Asana`), so a gap list
from the PM agent can name exactly what to research again.
"""

from .contracts import CompanyField, Competitor, FieldCoverage

MIN_COMPETITORS = 3
MAX_COMPETITORS = 5
REQUIRED: dict[str, dict[str, int]] = {
    "market": {"category": 1, "size_growth": 1, "trends": 2},
    "sales": {"target_customer": 1, "buyer_role": 1, "pricing_model": 1, "channel": 1},
}
# Company items required for a complete pack. Vision is collected when published, but many
# companies publish only a mission, so a missing vision does not make the pack partial.
COMPANY_REQUIRED = ("offering", "mission", "problem")
OPTIONAL_TAGS = ("sales.buying_signals", "company.vision")


def _field(missing: list[str]) -> FieldCoverage:
    return {"status": "partial" if missing else "complete", "missing": missing}


def company_missing(company: CompanyField) -> list[str]:
    missing = [f"company.{key}" for key in ("name", "website") if not company[key]]
    missing += [f"company.{key}" for key in COMPANY_REQUIRED if not company[key]]
    return missing


def competitors_missing(competitors: list[Competitor]) -> list[str]:
    missing: list[str] = []
    if len(competitors) < MIN_COMPETITORS:
        missing.append("competitors.alternative")
    # Details are required for the top 3 only; extra competitors are listed by name.
    for competitor in competitors[:MIN_COMPETITORS]:
        if not competitor["website"]:
            missing.append(f"competitors.website:{competitor['name']}")
        if not competitor["positioning"]:
            missing.append(f"competitors.positioning:{competitor['name']}")
        if competitor["pricing_status"] == "not_checked":
            missing.append(f"competitors.pricing:{competitor['name']}")
    return missing


def items_missing(field: str, values: dict[str, list[str]]) -> list[str]:
    return [
        f"{field}.{key}" for key, needed in REQUIRED[field].items()
        if len(values.get(key, [])) < needed
    ]


def coverage(
    company: CompanyField,
    market: dict[str, list[str]],
    competitors: list[Competitor],
    sales: dict[str, list[str]],
) -> dict[str, FieldCoverage]:
    return {
        "company": _field(company_missing(company)),
        "market": _field(items_missing("market", market)),
        "competitors": _field(competitors_missing(competitors)),
        "sales": _field(items_missing("sales", sales)),
    }


def all_missing(cov: dict[str, FieldCoverage]) -> list[str]:
    return [entry for field in cov.values() for entry in field["missing"]]


def matches_gap(entry: str, gap: str) -> bool:
    """A requested gap matches a field (`market`), a tag (`market.trends`), or an exact entry."""
    gap = gap.strip()
    if not gap:
        return False
    if entry == gap:
        return True
    base = entry.split(":", 1)[0]
    return base == gap or base.split(".", 1)[0] == gap
