"""Deterministic checks for evidence items proposed by the model.

An item is accepted only when its excerpt is verbatim in a collected source. Quote
matching proves provenance, not that the statement follows from the excerpt.
"""

import re
from typing import cast

from .contracts import BASES, TAGS, CompetitorRef, EvidenceItem, JsonObject, Source
from .sources import host, is_boilerplate, name_key, norm, public_https_url, same_company

MIN_EXCERPT = 25
MAX_EXCERPT = 400
MIN_STATEMENT = 15
MAX_STATEMENT = 400
# Tags about the researched company itself must cite its own site when one was collected.
FIRST_PARTY_TAGS = ("company.offering", "sales.pricing_model")
_ENTITY_STOP = {
    "the", "a", "an", "it", "its", "this", "that", "these", "they", "their", "in", "on",
    "as", "at", "by", "for", "according", "source", "company", "users", "customers", "we",
}


def unsupported_entities(statement: str, excerpt: str, skip_names: list[str]) -> list[str]:
    """Capitalized names and numbers in the statement that the excerpt does not contain."""
    lowered = excerpt.casefold()
    digits = lowered.replace(",", "")
    skip = set(_ENTITY_STOP)
    for name in skip_names:
        skip |= set(name_key(name).split())
    missing: list[str] = []
    for match in re.finditer(r"\d[\d,]*(?:\.\d+)?|[A-Z][\w&'-]*", statement):
        token = match.group(0)
        if token[0].isdigit():
            if token.replace(",", "") not in digits:
                missing.append(token)
            continue
        sentence_start = match.start() == 0 or re.search(r"[.!?:]\s*$", statement[:match.start()])
        if not sentence_start and token.casefold() not in skip and token.casefold() not in lowered:
            missing.append(token)
    return missing


class DroppedItem(ValueError):
    """An item dropped by a rule the model cannot fix by rewording. No corrective retry."""


class AdjacentCompetitor(DroppedItem):
    """The model labeled the competitor adjacent."""


_LIST_PAGE = re.compile(r"alternativ|competitor|\bvs\.?\b|versus|compar|review|similar|top \d+|best ",
                        re.IGNORECASE)


_PRICE = re.compile(
    r"[$€£]\s?\d|\d\s?(?:usd|eur|gbp)\b|\bfree\b|\bper\s+(?:user|seat|month|year|token|hour|gpu|"
    r"million|1m|minute)|/\s?(?:mo|month|yr|year|user|seat|hour|hr)\b", re.IGNORECASE)


def _competitor(value: object, company: str) -> CompetitorRef | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("competitor must be an object with name and website.")
    entry = cast(JsonObject, value)
    name = entry.get("name")
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
        raise ValueError("competitor needs a name of 2 to 100 characters.")
    if any(same_company(name, alias) for alias in company.split("|") if alias):
        raise ValueError("competitor is the researched company itself.")
    if str(entry.get("relation") or "direct").lower() == "adjacent":
        raise AdjacentCompetitor(f"{norm(name)} dropped: adjacent, not a direct competitor")
    website = entry.get("website") or ""
    if website:
        try:
            website = public_https_url(website)
        except ValueError as error:
            raise ValueError("competitor website must be a public HTTPS URL.") from error
    return {"name": norm(name)[:100], "website": cast(str, website)}


def excerpt_key(excerpt: str, competitor: CompetitorRef | None) -> str:
    """1 excerpt supports 1 item, except that a list of competitors may support 1 item each."""
    return norm(excerpt).casefold() + "|" + (name_key(competitor["name"]) if competitor else "")


def check_item(
    raw: object,
    *,
    sources: dict[str, Source],
    company: str,
    has_first_party: bool,
    used_excerpts: set[str],
) -> tuple[EvidenceItem, list[str]]:
    """Validate 1 proposed item. Returns the item (without an ID) and notes on dropped tags.

    Raises ValueError with a message the model can act on in its corrective retry.
    """
    if not isinstance(raw, dict):
        raise ValueError("Each item must be an object.")
    entry = cast(JsonObject, raw)
    statement, excerpt = entry.get("statement"), entry.get("excerpt")
    basis, source_id, tags_raw = entry.get("basis"), entry.get("source_id"), entry.get("tags")
    if not isinstance(statement, str) or not MIN_STATEMENT <= len(norm(statement)) <= MAX_STATEMENT:
        raise ValueError(f"statement must be {MIN_STATEMENT} to {MAX_STATEMENT} characters.")
    if basis not in BASES:
        raise ValueError("basis must be fact or inference.")
    if not isinstance(source_id, str) or source_id not in sources:
        raise ValueError("source_id must be one of the supplied source ids.")
    if not isinstance(excerpt, str):
        raise ValueError("excerpt is required.")
    quote = norm(excerpt)
    if not MIN_EXCERPT <= len(quote) <= MAX_EXCERPT:
        raise ValueError(f"excerpt must be {MIN_EXCERPT} to {MAX_EXCERPT} characters.")
    if is_boilerplate(quote):
        raise ValueError("excerpt quotes cookie, navigation, or sign-in text.")
    source = sources[source_id]
    if quote not in norm(source["text"]):
        raise ValueError("excerpt is not copied verbatim from its source.")
    if not isinstance(tags_raw, list) or not tags_raw:
        raise ValueError("tags must be a non-empty list.")
    unknown = [tag for tag in tags_raw if tag not in TAGS]
    if unknown:
        raise ValueError(f"unknown tags: {', '.join(map(str, unknown[:5]))}.")
    tags = list(dict.fromkeys(cast(list[str], tags_raw)))
    competitor = _competitor(entry.get("competitor"), company)
    if excerpt_key(quote, competitor) in used_excerpts:
        raise ValueError("excerpt already supports another item; use a distinct excerpt.")
    notes: list[str] = []
    if any(tag.startswith("competitors.") for tag in tags) and competitor is None:
        raise ValueError("competitors.* tags need a competitor with a name.")
    if competitor:
        publisher = host(source["url"]).split(".")[0].replace("-", "")
        rival_key = name_key(competitor["name"]).replace(" ", "")
        if source["kind"] != "competitor" and rival_key and rival_key == publisher:
            raise ValueError(f"{competitor['name']} published this page; the publisher of an "
                             "alternatives list is not evidence that it competes.")
        if re.search(r"\b(?:acquir\w*|is joining|joins|merg\w*|subsidiary|integrat\w*|partner\w*)\b",
                     quote, re.IGNORECASE):
            raise ValueError(f"the excerpt describes an acquisition, integration, or partnership "
                             f"with {competitor['name']}, not competition.")
    if competitor and not competitor["website"] and source["kind"] == "competitor":
        competitor["website"] = f"https://{host(source['url'])}/"
    if has_first_party and source["kind"] != "first_party":
        for tag in FIRST_PARTY_TAGS:
            if tag in tags:
                tags.remove(tag)
                notes.append(f"dropped {tag}: must cite the company's own website")
    if "competitors.alternative" in tags and source["kind"] not in ("competitor", "review") and \
            not _LIST_PAGE.search(f"{source['title']} {source['url']}"):
        # A market report or news piece lists many vendors. Only comparison, alternatives,
        # review, or competitor pages are evidence that buyers choose between 2 products.
        tags.remove("competitors.alternative")
        notes.append("dropped competitors.alternative: not a comparison or alternatives page")
    if source["kind"] == "market_report":
        for tag in [t for t in tags if not t.startswith("market.")]:
            tags.remove(tag)
            notes.append(f"dropped {tag}: a market report supports market items only")
    if "competitors.pricing" in tags and not _PRICE.search(quote):
        tags.remove("competitors.pricing")
        notes.append("dropped competitors.pricing: the excerpt states no price, plan, or tier")
    if source["kind"] == "forum":
        for tag in ("competitors.positioning", "competitors.pricing"):
            if tag in tags:
                tags.remove(tag)
                notes.append(f"dropped {tag}: a forum post is not a reliable source for it")
    if not tags and competitor and all(n.startswith("dropped competitors.") for n in notes):
        raise DroppedItem("; ".join(notes))
    if not tags:
        raise ValueError("no usable tags remain; company.offering and sales.pricing_model "
                         "must cite the company's own website, and competitor positioning and "
                         "pricing cannot cite a forum.")
    skip = [*company.split("|"), *([competitor["name"]] if competitor else [])]
    missing = unsupported_entities(norm(statement), quote, skip)
    if missing:
        raise ValueError("statement names things its excerpt does not contain: "
                         + ", ".join(missing[:5]) + ".")
    if source["kind"] == "forum" and basis == "fact":
        basis = "inference"
        notes.append("forum fact downgraded to inference")
    item: EvidenceItem = {
        "id": "",
        "statement": norm(statement),
        "excerpt": quote,
        "basis": cast(str, basis),
        "tags": tags,
        "source_id": source_id,
        "url": source["url"],
        "retrieved_at": source["retrieved_at"],
        "published_at": source["published_at"],
        "competitor": competitor if any(t.startswith("competitors.") for t in tags) else None,
        "round": source["round"],
    }
    return item, notes
