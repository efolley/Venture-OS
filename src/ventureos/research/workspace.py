"""Evidence workspace for one research run.

The agent (a DeepAgents ReAct loop) never writes the brief directly. It calls the
tools below, which collect sources and accept only claims that pass the same
deterministic checks as before (verbatim quote, no boilerplate, known source).
The workspace also reports which fields are still empty, so the loop can continue
until every field is filled or the search budget is spent.
"""

import json
import re
from datetime import datetime, timezone
from typing import cast

from .contracts import CATEGORIES, Brief, JsonObject, RejectedSource, SearchProvider, Source
from .engine import (
    MAX_CLAIMS,
    _apply_claim_policy,
    _check_claim,
    _checked_brief,
    _host,
    _host_matches,
    _norm,
    _off_target_reason,
    _public_https_url,
    _user_website,
    classify_source,
    clean_text,
)
from .logs import logged, logged_debug, logger


MIN_EXTERNAL_SITES = 3
MAX_EXTERNAL_SITES = 5
MAX_FIRST_PARTY_PAGES = 3
MAX_PAGES_PER_EXTERNAL_SITE = 2
MAX_SEARCHES = 5
SOURCE_CHARS = 20000
READ_CHARS = 4000
PREVIEW_CHARS = 300
MAX_UNCERTAINTIES = 10

_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class ResearchWorkspace:
    """Mutable state and tool logic for one run. One instance per research call."""

    @logged_debug
    def __init__(
        self,
        company: str,
        website: str,
        search: SearchProvider,
        *,
        question: str = "",
        max_searches: int = MAX_SEARCHES,
    ) -> None:
        self.company = company.strip()[:200]
        self.website = website
        self.user_website = bool(website)
        self.question = question
        self.search_provider = search
        self.max_searches = max_searches
        self.searches_used = 0
        self.evidence: list[Source] = []
        self.pre_rejected: list[RejectedSource] = []
        self.claims: list[JsonObject] = []
        self.flagged: dict[str, str] = {}
        self.uncertainties: list[str] = []
        self._seen_urls: set[str] = set()

    @property
    def host(self) -> str:
        return _host(self.website) if self.website else ""

    @logged_debug
    def _usable(self) -> list[Source]:
        return [s for s in self.evidence if s["id"] not in self.flagged]

    @logged_debug
    def _external_hosts(self) -> list[str]:
        hosts = {_host(s["url"]) for s in self._usable() if s["kind"] != "first_party"}
        return sorted(hosts)

    @logged_debug
    def _first_party_pages(self) -> int:
        return sum(1 for s in self._usable() if s["kind"] == "first_party")

    @logged
    def field_status(self) -> JsonObject:
        """Report which fields are filled and what is still missing."""
        return self._field_status()

    @logged_debug
    def _field_status(self) -> JsonObject:
        counts = {category: 0 for category in CATEGORIES}
        for claim in self.claims:
            counts[cast(str, claim["category"])] += 1
        missing = [category for category, count in counts.items() if count == 0]
        external = self._external_hosts()
        first_party = self._first_party_pages()
        searches_left = self.max_searches - self.searches_used
        complete = (
            not missing and first_party >= 1 and len(external) >= MIN_EXTERNAL_SITES
        )
        return {
            "complete": complete,
            "category_claims": counts,
            "missing_categories": missing,
            "company_website": self.website or None,
            "main_site_pages": first_party,
            "external_sites": external,
            "external_sites_needed": max(0, MIN_EXTERNAL_SITES - len(external)),
            "external_site_slots_left": MAX_EXTERNAL_SITES - len(external),
            "searches_left": searches_left,
            "claims": len(self.claims),
        }

    @logged_debug
    def exhausted(self) -> bool:
        return self.searches_used >= self.max_searches

    @logged
    def set_company(self, name: str, website: str = "") -> str:
        """Set the company name and official HTTPS website when the user did not give them."""
        if name.strip() and not self.company:
            self.company = name.strip()[:200]
        if website.strip():
            if self.user_website:
                return _dump({"error": "The website was given by the user and cannot change."})
            try:
                self.website = _user_website(website)
            except ValueError as error:
                return _dump({"error": str(error)})
            for source in self.evidence:
                source["kind"] = classify_source(source["url"], self.host)
        return _dump({"company": self.company, "website": self.website})

    @logged
    def search_web(self, query: str, site: str = "") -> str:
        """Search the web and store usable pages as sources.

        Pass `site` (a bare domain such as example.com) to search only that website.
        Returns source ids with short previews; use read_source for the full text.
        """
        if self.exhausted():
            return _dump({"error": (
                "Search budget is spent. Do not call search_web again. Use read_source on "
                "the collected sources and record claims with add_claim, then stop."
            ), "status": self._short_status()})
        if not query.strip():
            return _dump({"error": "Give a non-empty query."})
        domain = ""
        if site.strip():
            domain = _host(site.strip() if "://" in site else f"https://{site.strip()}")
            if not _DOMAIN.match(domain):
                return _dump({"error": "site must be a bare domain such as example.com."})
        self.searches_used += 1
        if domain:
            results = self.search_provider.search(query.strip()[:300], limit=5, include_domains=[domain])
        else:
            results = self.search_provider.search(query.strip()[:300], limit=5)
        added: list[JsonObject] = []
        skipped: list[JsonObject] = []
        for item in results:
            try:
                url = _public_https_url(item["url"])
            except ValueError:
                continue
            if url in self._seen_urls:
                continue
            self._seen_urls.add(url)
            text = clean_text(item["text"])[:SOURCE_CHARS]
            if not text.strip():
                self._reject(url, "no usable text after removing boilerplate", skipped)
                continue
            kind = classify_source(url, self.host)
            title = item["title"][:300]
            reason = _off_target_reason(kind, title, text, self.company, self.host)
            if not reason:
                reason = self._cap_reason(url, kind)
            if reason:
                self._reject(url, reason, skipped)
                continue
            source: Source = {
                "id": f"s{len(self.evidence) + 1}",
                "url": url,
                "title": title,
                "kind": kind,
                "text": text,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "published_at": item.get("published_at") or None,
            }
            self.evidence.append(source)
            added.append({
                "id": source["id"], "url": url, "kind": kind, "chars": len(text),
                "preview": text[:PREVIEW_CHARS],
            })
        logger.info(
            "workspace search added=%d skipped=%d searches_used=%d",
            len(added), len(skipped), self.searches_used,
        )
        return _dump({"added": added, "skipped": skipped, "status": self._short_status()})

    @logged_debug
    def _reject(self, url: str, reason: str, skipped: list[JsonObject]) -> None:
        self.pre_rejected.append({"url": url, "reason": reason})
        skipped.append({"url": url, "reason": reason})

    @logged_debug
    def _cap_reason(self, url: str, kind: str) -> str | None:
        host = _host(url)
        same_host = sum(1 for s in self._usable() if _host(s["url"]) == host)
        if kind == "first_party":
            if self._first_party_pages() >= MAX_FIRST_PARTY_PAGES:
                return "main website page limit reached"
            return None
        hosts = self._external_hosts()
        if host not in hosts and len(hosts) >= MAX_EXTERNAL_SITES:
            return "external site limit reached"
        if same_host >= MAX_PAGES_PER_EXTERNAL_SITE:
            return "page limit for this site reached"
        return None

    @logged_debug
    def _short_status(self) -> JsonObject:
        status = self._field_status()
        return {key: status[key] for key in (
            "missing_categories", "main_site_pages", "external_sites_needed", "searches_left",
        )}

    @logged
    def read_source(self, source_id: str, start: int = 0) -> str:
        """Read up to 4000 characters of a source's cleaned text from character `start`."""
        source = next((s for s in self._usable() if s["id"] == source_id), None)
        if source is None:
            return _dump({"error": "Unknown or rejected source id."})
        start = max(0, int(start))
        text = source["text"]
        return _dump({
            "id": source_id,
            "start": start,
            "total_chars": len(text),
            "text": text[start:start + READ_CHARS],
            "more": start + READ_CHARS < len(text),
        })

    @logged
    def add_claim(self, text: str, basis: str, category: str, source_id: str, quote: str) -> str:
        """Record one atomic claim. The quote must be copied verbatim from the source text.

        basis is "fact" or "inference". category is one of: company, product, pricing,
        customers, market, competitors, trends, signals, risks.
        """
        if len(self.claims) >= MAX_CLAIMS:
            return _dump({"error": f"Claim limit of {MAX_CLAIMS} reached."})
        texts = {s["id"]: _norm(s["text"]) for s in self._usable()}
        try:
            claim = _check_claim(
                len(self.claims) + 1,
                {"text": text, "basis": basis, "category": category,
                 "source_id": source_id, "quote": quote},
                texts,
                set(self.flagged),
            )
        except ValueError as error:
            return _dump({"rejected": str(error)})
        if any(cast(str, c["text"]).casefold() == claim["text"].casefold() for c in self.claims):
            return _dump({"rejected": "Duplicate claim."})
        kind = next(s["kind"] for s in self._usable() if s["id"] == claim["source_id"])
        reason = _apply_claim_policy(
            claim, kind, self._first_party_pages() > 0,
            {cast(str, c["quote"]).casefold() for c in self.claims}, self.company,
        )
        if reason:
            return _dump({"rejected": reason})
        self.claims.append(cast(JsonObject, claim))
        status = self._short_status()
        return _dump({"accepted": True, "claims": len(self.claims), "status": status})

    @logged
    def reject_source(self, source_id: str, reason: str) -> str:
        """Drop a source that is about a different organization, with the claims that cite it."""
        if not any(s["id"] == source_id for s in self.evidence):
            return _dump({"error": "Unknown source id."})
        self.flagged[source_id] = reason.strip()[:200] or "flagged as a different organization"
        self.claims = [c for c in self.claims if c["source_id"] != source_id]
        return _dump({"rejected": source_id, "claims": len(self.claims)})

    @logged
    def note_uncertainty(self, text: str) -> str:
        """Record something the evidence does not settle (a gap, a conflict, thin sourcing)."""
        note = _norm(text)[:300]
        if note and note not in self.uncertainties and len(self.uncertainties) < MAX_UNCERTAINTIES:
            self.uncertainties.append(note)
        return _dump({"uncertainties": len(self.uncertainties)})

    @logged
    def finish(self) -> tuple[Brief, list[Source]]:
        """Validate everything collected and return the brief plus the sources it may cite."""
        notes = list(self.uncertainties)
        external = self._external_hosts()
        if self.website and self._first_party_pages() == 0:
            notes.insert(0, "No page from the company's own website was collected.")
        if len(external) < MIN_EXTERNAL_SITES:
            notes.insert(0, (
                f"Only {len(external)} independent website(s) were found; "
                f"the target is {MIN_EXTERNAL_SITES} to {MAX_EXTERNAL_SITES}."
            ))
        raw: JsonObject = {
            "company": {"name": self.company, "website": self.website},
            "claims": [
                {key: claim[key] for key in ("text", "basis", "category", "source_id", "quote")}
                for claim in self.claims
            ],
            "rejected_source_ids": sorted(self.flagged),
            "uncertainties": notes[:MAX_UNCERTAINTIES],
        }
        brief = _checked_brief(
            raw, self.evidence, self.pre_rejected, self.website if self.user_website else "",
            require_website_source=False,
        )
        usable_ids = {ref["id"] for ref in brief["sources"]}
        company_host = _host(brief["company"]["website"])
        accepted = [s for s in self.evidence if s["id"] in usable_ids]
        for source in accepted:
            source["kind"] = classify_source(source["url"], company_host)
        for ref in brief["sources"]:
            ref["kind"] = classify_source(ref["url"], company_host)
        return brief, accepted

    @logged
    def seed_main_site(self) -> None:
        """Fetch pages from the company's own website before the agent starts."""
        if self.host:
            self.search_web(f"{self.company} {self.host} product pricing customers", site=self.host)
