"""Markdown rendering of an evidence brief for the Streamlit viewer.

Pure functions with no Streamlit import so they can be tested offline.
"""

import re
from typing import cast
from urllib.parse import quote, urlsplit

from .contracts import CATEGORIES, JsonObject
from .logs import logged_debug


@logged_debug
def as_object(value: object, message: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(message)
    entries = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in entries):
        raise ValueError(message)
    return cast(JsonObject, entries)


@logged_debug
def as_object_list(value: object, message: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise ValueError(message)
    return [as_object(item, message) for item in cast(list[object], value)]


@logged_debug
def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[object], value) if isinstance(item, str)]


@logged_debug
def markdown_text(value: str) -> str:
    normalized = " ".join(value.split())
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", normalized)


@logged_debug
def code_text(value: str) -> str:
    """Show a raw string, such as a URL, as inline code so it needs no escaping."""
    return "`" + " ".join(value.split()).replace("`", "'") + "`"


@logged_debug
def markdown_value(value: object) -> str:
    return markdown_text(value) if isinstance(value, str) else ""


@logged_debug
def is_https_link(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


@logged_debug
def markdown_link(label: str, url: str) -> str:
    if not is_https_link(url):
        return markdown_text(label)
    return f"[{markdown_text(label)}]({quote(url, safe=':/?&=#%+@')})"


@logged_debug
def brief_markdown(brief_value: object) -> str:
    brief = as_object(brief_value, "Backend returned an invalid brief.")
    company = as_object(brief.get("company"), "Backend returned an invalid company section.")
    claims = as_object_list(brief.get("claims"), "Backend returned invalid claims.")
    sources = as_object_list(brief.get("sources"), "Backend returned invalid sources.")
    coverage = as_object(brief.get("coverage"), "Backend returned invalid coverage.")
    rejected = as_object_list(brief.get("rejected_sources", []), "Backend returned invalid rejections.")
    kinds = {str(source.get("id")): str(source.get("kind", "")) for source in sources}

    name = markdown_value(company.get("name")) or "Company"
    website = company.get("website")
    heading = (
        markdown_link(str(company.get("name") or "Company"), website)
        if isinstance(website, str) else name
    )
    sections = [
        f"**Company:** {heading}",
        "**Coverage (claims per category):** " + " | ".join(
            f"{category} {coverage.get(category, 0)}" for category in CATEGORIES
        ),
    ]
    gaps = string_list(brief.get("gaps"))
    if gaps:
        sections.append("**Gaps (no evidence found):** " + ", ".join(markdown_text(g) for g in gaps))

    for category in CATEGORIES:
        lines: list[str] = []
        for claim in claims:
            if claim.get("category") != category:
                continue
            source_id = str(claim.get("source_id"))
            published = claim.get("published_at")
            date = f", published {markdown_text(published[:10])}" if isinstance(published, str) and published else ""
            dated = ", **dated: older than 12 months**" if claim.get("dated") is True else ""
            lines.append(
                f"- {markdown_value(claim.get('text'))} "
                f"({markdown_value(claim.get('basis'))}; {markdown_text(str(claim.get('id')))}, "
                f"{markdown_text(source_id)} {markdown_text(kinds.get(source_id, ''))}{date}{dated})"
            )
            lines.append(f"  > {markdown_value(claim.get('quote'))}")
        if lines:
            sections.append("\n".join([f"**{category.capitalize()}**", *lines]))

    uncertainties = string_list(brief.get("uncertainties"))
    if uncertainties:
        sections.append("\n".join(["**Uncertainties:**", *[f"- {markdown_text(u)}" for u in uncertainties]]))
    sections.append("\n".join([
        "**Sources:**",
        *[
            f"- {markdown_text(str(s.get('id')))} ({markdown_text(str(s.get('kind')))}) "
            f"{markdown_link(str(s.get('title') or s.get('url')), str(s.get('url')))}"
            for s in sources
        ],
    ]))
    if rejected:
        sections.append("\n".join([
            "**Rejected sources:**",
            *[f"- {code_text(str(r.get('url')))}: {markdown_value(r.get('reason'))}" for r in rejected],
        ]))
    return "\n\n".join(sections)
