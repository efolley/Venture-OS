"""Pick the next search in code: the field with the biggest gap, from fixed query templates.

Company basics always go first, because every other search depends on them.
"""

from dataclasses import dataclass

from . import checklist
from .contracts import FIELDS, Competitor
from .sources import host, name_key


@dataclass(frozen=True)
class Step:
    field: str
    gap: str
    query: str
    site: str = ""
    pricing_check: str = ""  # name key of the competitor whose pricing this search checks
    anchor: bool = True  # add the company domain to open-web searches to avoid same-name noise


def _with_instructions(query: str, instructions: str) -> str:
    return f"{query} {instructions}".strip()[:300] if instructions else query[:300]


def _candidates(field: str, missing: list[str], name: str, company_host: str,
                competitors: list[Competitor]) -> list[Step]:
    if field == "company":
        return [
            Step("company", "company.offering", f"{name} product what it does", company_host),
            Step("company", "company.offering", f"{name} company overview"),
        ]
    if field == "market":
        return [
            Step("market", "market", f"{name} market category size growth"),
            Step("market", "market.trends", f"{name} industry trends"),
            Step("market", "market.size_growth", f"{name} market size forecast"),
        ]
    if field == "sales":
        steps = [Step("sales", "sales", f"{name} pricing plans customers", company_host)]
        steps.append(Step("sales", "sales", f"{name} target customers buyers case studies"))
        steps.append(Step("sales", "sales.channel", f"{name} sales team partners free trial"))
        return steps
    steps: list[Step] = []
    if "competitors.alternative" in missing:
        steps.append(Step("competitors", "competitors.alternative", f"{name} competitors alternatives"))
        steps.append(Step("competitors", "competitors.alternative", f"{name} vs alternatives comparison"))
    for competitor in competitors:
        key = name_key(competitor["name"])
        wanted = [e for e in missing if e.endswith(f":{competitor['name']}")]
        if not wanted:
            continue
        rival_host = host(competitor["website"]) if competitor["website"] else ""
        if any(e.startswith("competitors.pricing:") for e in wanted) and rival_host:
            steps.append(Step("competitors", wanted[0], f"{competitor['name']} pricing plans",
                              rival_host, pricing_check=key, anchor=False))
        steps.append(Step("competitors", wanted[0],
                          f"{competitor['name']} pricing plans positioning", rival_host, anchor=False))
    return steps


def next_step(
    missing: list[str],
    *,
    name: str,
    company_host: str,
    competitors: list[Competitor],
    instructions: str,
    used: set[tuple[str, str]],
    attempts: dict[str, int] | None = None,
    only_field: str = "",
) -> Step | None:
    """Return the next unused search, or None when nothing is left to try.

    Company basics go first. Then fields rotate: the field searched least so far goes next,
    and among equals the one with the most missing items. `only_field` restricts the choice
    (used to retry a round that kept no pages).
    """
    attempts = attempts or {}
    by_field = {field: [e for e in missing if e.startswith(f"{field}.")] for field in FIELDS}
    order = sorted(
        (field for field in FIELDS if by_field[field] and (not only_field or field == only_field)),
        key=lambda f: (f != "company", attempts.get(f, 0), -len(by_field[f]), FIELDS.index(f)),
    )
    for field in order:
        for step in _candidates(field, by_field[field], name, company_host, competitors):
            query = step.query
            if not step.site:
                if step.anchor and company_host and company_host not in query:
                    query = f"{query} {company_host}"
                query = _with_instructions(query, instructions)
            if (query, step.site) in used:
                continue
            return Step(step.field, step.gap, query, step.site, step.pricing_check, step.anchor)
    return None


def filter_missing(missing: list[str], gaps: list[str]) -> list[str]:
    """Keep only missing entries that a requested gap names; all of them when no gaps given."""
    if not gaps:
        return missing
    return [e for e in missing if any(checklist.matches_gap(e, gap) for gap in gaps)]
