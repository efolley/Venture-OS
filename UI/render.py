"""Turn an evidence pack (schema v4) and a GTM strategy pack (schema v4) into Markdown.

Presentation only; no processing. Page and model text is untrusted, so every string is
escaped before rendering.
"""

import re

FIELD_LABELS = {
    "company": "Company", "market": "Market", "competitors": "Competitors", "sales": "Sales",
}
ITEM_LABELS = {
    "offering": "What they sell", "mission": "Mission", "vision": "Vision",
    "problem": "Problem they solve", "category": "Category", "size_growth": "Size or growth",
    "trends": "Trends", "target_customer": "Target customer", "buyer_role": "Buyer role",
    "pricing_model": "Pricing model", "channel": "Sales channel", "buying_signals": "Buying signals",
}
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<$])")


def esc(value: object) -> str:
    return _MD_SPECIAL.sub(r"\\\1", " ".join(str(value or "").split()))


def safe_link(label: str, url: str) -> str:
    if not url.startswith("https://") or any(c in url for c in " ()<>\"'"):
        return esc(label)
    return f"[{esc(label)}]({url})"


def _cite(ids: list[str], evidence: dict[str, dict]) -> list[str]:
    lines = []
    for evidence_id in ids:
        item = evidence.get(evidence_id)
        if item is None:
            continue
        basis = "" if item["basis"] == "fact" else " _(inference)_"
        lines.append(f"- {esc(item['statement'])}{basis} {safe_link(evidence_id, item['url'])}")
    return lines or ["- _missing_"]


def coverage_table(coverage: dict[str, dict]) -> str:
    rows = ["| Field | Status | Missing |", "| --- | --- | --- |"]
    for field, label in FIELD_LABELS.items():
        entry = coverage.get(field, {"status": "partial", "missing": []})
        icon = "✅ complete" if entry["status"] == "complete" else "🟡 partial"
        rows.append(f"| {label} | {icon} | {esc(', '.join(entry['missing'])) or 'none'} |")
    return "\n".join(rows)


def pack_markdown(pack: dict) -> str:
    evidence = {item["id"]: item for item in pack.get("evidence", [])}
    company = pack["company"]
    out = [
        f"### {esc(company['name'])}",
        f"{safe_link(company['website'], company['website'])} · status **{pack['status']}** · "
        f"{len(evidence)} evidence items · {len(pack.get('sources', []))} sources",
        "",
        coverage_table(pack["coverage"]),
        "",
        "#### Company",
    ]
    for key in ("offering", "mission", "vision", "problem"):
        out += ["", f"**{ITEM_LABELS[key]}**", ""]
        out += _cite(company.get(key, []), evidence)
    for field in ("market", "sales"):
        out += ["", f"#### {FIELD_LABELS[field]}"]
        for key, ids in pack[field].items():
            out += ["", f"**{ITEM_LABELS.get(key, esc(key))}**", ""]
            out += _cite(ids, evidence)
    out += ["", "#### Competitors"]
    if not pack["competitors"]:
        out.append("- _none found_")
    for rival in pack["competitors"]:
        website = safe_link(rival["website"], rival["website"]) if rival["website"] else "website unknown"
        pricing = {"found": "", "not_published": " · pricing not published",
                   "not_checked": " · pricing not checked"}[rival["pricing_status"]]
        out += ["", f"**{esc(rival['name'])}** ({website}){pricing}", ""]
        out += _cite(list(dict.fromkeys(rival["positioning"] + rival["pricing"])), evidence)
    if pack.get("uncertainties"):
        out += ["", "#### Notes", *[f"- {esc(note)}" for note in pack["uncertainties"]]]
    return "\n".join(out)


def evidence_rows(pack: dict) -> list[dict]:
    return [{
        "id": item["id"], "statement": item["statement"], "excerpt": item["excerpt"],
        "basis": item["basis"], "tags": ", ".join(item["tags"]), "url": item["url"],
        "retrieved": item["retrieved_at"][:10], "round": item["round"],
    } for item in pack.get("evidence", [])]


# ----- GTM strategy pack ---------------------------------------------------------------

SNAPSHOT_LABELS = {
    "mission": "Mission", "vision": "Vision", "problem": "Problem they solve",
    "target_market": "Target market", "icp": "Ideal customer profile", "product": "Product",
    "client_value": "How it helps clients", "market_brief": "Market brief",
    "competitive_landscape": "Competition landscape",
}
STATUS_ICONS = {"complete": "✅ complete", "partial": "🟡 partial", "fallback": "🔴 fallback"}


def _sources(item: dict) -> str:
    ids = [*item.get("evidence_ids", []), *item.get("recommendation_ids", [])]
    return f" `{esc(', '.join(ids))}`" if ids else ""


def _basis(item: dict) -> str:
    return " _(hypothesis)_" if item.get("basis") == "hypothesis" else ""


def snapshot_markdown(strategy: dict) -> str:
    snapshot = strategy["snapshot"]
    company = snapshot["company"]
    lines = snapshot["lines"]
    out = [
        f"### Company snapshot: {esc(company['name'])}",
        f"{safe_link(company['website'], company['website'])} · snapshot "
        f"**{STATUS_ICONS.get(snapshot['status'], esc(snapshot['status']))}** · strategy "
        f"**{esc(strategy['status'])}**",
    ]
    groups = (("Mission and vision", ("mission", "vision")), ("Problem", ("problem",)),
              ("Target market and ICP", ("target_market", "icp")),
              ("Product", ("product", "client_value")), ("Market analysis", ("market_brief",)),
              ("Competition", ("competitive_landscape",)))
    for title, keys in groups:
        out += ["", f"**{title}**", ""]
        for key in keys:
            line = lines.get(key, {})
            text = (f"{esc(line['text'])}{_basis(line)}{_sources(line)}"
                    if line.get("status") == "found" else "_unknown_")
            out.append(f"- {SNAPSHOT_LABELS[key]}: {text}")
    if snapshot.get("line_errors"):
        out += ["", "_Lines that failed validation: "
                + esc(", ".join(snapshot["line_errors"])) + "_"]
    return "\n".join(out)


def _recommendations(strategy: dict, agent: str) -> list[dict]:
    return [item for item in strategy.get("recommendations", []) if item.get("agent") == agent]


def competitive_markdown(strategy: dict) -> str:
    rows = ["| Rank | Score | Hypothesis | Validate by asking |", "| --- | --- | --- | --- |"]
    items = sorted(_recommendations(strategy, "competitive_strategy"), key=lambda i: i.get("rank", 99))
    for item in items:
        rows.append(f"| {item.get('rank', '')} | {item.get('score', '')}/20 | "
                    f"**{esc(item['title'])}**: {esc(item['recommendation'])}{_sources(item)} | "
                    f"{esc(item.get('validation_question', ''))} |")
    return "\n".join(rows) if items else "_No competitive hypotheses._"


def recommendations_markdown(strategy: dict, agent: str) -> str:
    items = _recommendations(strategy, agent)
    if not items:
        status = strategy.get("sub_agents", {}).get(agent, {})
        return f"_No recommendations ({esc(status.get('error') or status.get('status', 'missing'))})._"
    return "\n".join(f"- **{esc(item['title'])}**{_basis(item)}: {esc(item['recommendation'])}"
                     f"{_sources(item)}" for item in items)


def themes_markdown(strategy: dict) -> str:
    themes = strategy.get("themes", [])
    if not themes:
        return "_No themes._"
    return "\n".join(f"- **{esc(theme['title'])}** ({esc(', '.join(theme.get('agents', [])))})"
                     for theme in themes)


def gaps_markdown(strategy: dict) -> str:
    gaps = strategy.get("gaps", [])
    return "\n".join(f"- {esc(gap)}" for gap in gaps) if gaps else "_No gaps listed._"
