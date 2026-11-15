"""Turn an evidence pack (schema v4) into Markdown. Presentation only; no processing.

Page text is untrusted, so every string from the pack is escaped before rendering.
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
