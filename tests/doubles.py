"""Provider doubles. Tests never call live search or model providers."""

import json
from typing import Callable

from research.contracts import JsonObject, SearchResult


class FakeSearch:
    """Returns pages for the first route whose key is a substring of the query."""

    def __init__(self, routes: dict[str, list[SearchResult]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, list[str] | None]] = []

    def search(self, query: str, limit: int = 5, *, include_domains: list[str] | None = None
               ) -> list[SearchResult]:
        self.calls.append((query, include_domains))
        for key, pages in self.routes.items():
            if key in query:
                return [dict(p) for p in pages][:limit]  # type: ignore[misc]
        return []


class WorldModel:
    """Extraction double: returns prepared items for each supplied source URL.

    `items` maps a URL to item templates without source_id. `resolve` answers the
    website-confirmation call. The ReAct reason call follows the suggested template unless
    `reason` is given. `override` can replace any answer (for retry tests).
    """

    def __init__(self, items: dict[str, list[JsonObject]] | None = None,
                 resolve: JsonObject | None = None,
                 override: Callable[[str, JsonObject, int], JsonObject | None] | None = None,
                 reason: Callable[[JsonObject], JsonObject] | None = None) -> None:
        self.items = items or {}
        self.resolve = resolve or {"status": "not_found", "candidates": []}
        self.override = override
        self.reason = reason
        self.calls: list[tuple[str, JsonObject]] = []

    def json(self, system: str, prompt: str) -> JsonObject:
        payload = json.loads(prompt)
        self.calls.append((system, payload))
        if self.override:
            answer = self.override(system, payload, len(self.calls))
            if answer is not None:
                return answer
        if "official website" in system:
            return self.resolve
        if "plan the next web search" in system:
            if self.reason is not None:
                return self.reason(payload)
            suggested = payload.get("suggested") or {}
            return {"thought": f"Fill {suggested.get('gap')} next.", **suggested}
        items: list[JsonObject] = []
        for source in payload["sources"]:
            for template in self.items.get(source["url"], []):
                items.append({"basis": "fact", "competitor": None, **template,
                              "source_id": source["id"]})
        return {"items": items, "rejected_sources": []}


def page(url: str, title: str, text: str, published_at: str | None = None) -> SearchResult:
    result: SearchResult = {"url": url, "title": title, "text": text}
    if published_at:
        result["published_at"] = published_at
    return result


HOME = "https://acmecloud.com/"
PRICING = "https://acmecloud.com/pricing"
NEWS = "https://techcrunch.com/acme-cloud-market"
G2 = "https://g2.com/acme-cloud-alternatives"

HOME_TEXT = (
    "Accept all cookies to continue. Acme Cloud sells a document collaboration workspace for "
    "agencies. Acme Cloud is built for agency operations managers who run client projects. "
    "Start a free trial or book a demo with our sales team."
)
PRICING_TEXT = (
    "Acme Cloud pricing is per seat, starting at $12 per user per month. "
    "Acme Cloud partners with resellers in Europe."
)
NEWS_TEXT = (
    "Acme Cloud competes in the collaborative work management category. "
    "Analysts expect the collaborative work management market to grow 13 percent a year. "
    "Agencies are consolidating tools into a single workspace, Acme Cloud said. "
    "Buyers increasingly ask for built-in AI summaries in project tools."
)
G2_TEXT = (
    "Top Acme Cloud alternatives. Beta Docs is a wiki for engineering teams and costs $8 per "
    "user per month. Gamma Boards positions itself as visual planning for marketing teams "
    "with plans from $10 per user. Delta Desk is a client portal for agencies with plans from "
    "$15 per seat."
)

FULL_ROUTES: dict[str, list[SearchResult]] = {
    "product what it does": [page(HOME, "Acme Cloud", HOME_TEXT),
                             page(PRICING, "Acme Cloud pricing", PRICING_TEXT)],
    "market category size growth": [page(NEWS, "Acme Cloud and the market", NEWS_TEXT,
                                         "2026-09-01")],
    "competitors alternatives": [page(G2, "Acme Cloud alternatives", G2_TEXT)],
}

FULL_ITEMS: dict[str, list[JsonObject]] = {
    HOME: [
        {"statement": "Acme Cloud sells a document collaboration workspace for agencies.",
         "excerpt": "Acme Cloud sells a document collaboration workspace for agencies.",
         "tags": ["company.offering", "sales.target_customer"]},
        {"statement": "The product is built for agency operations managers.",
         "excerpt": "Acme Cloud is built for agency operations managers who run client projects.",
         "tags": ["sales.buyer_role"]},
        {"statement": "It offers a free trial and demos with a sales team.",
         "excerpt": "Start a free trial or book a demo with our sales team.",
         "tags": ["sales.channel"]},
    ],
    PRICING: [
        {"statement": "Pricing is per seat from $12 per user per month.",
         "excerpt": "Acme Cloud pricing is per seat, starting at $12 per user per month.",
         "tags": ["sales.pricing_model"]},
    ],
    NEWS: [
        {"statement": "It competes in collaborative work management.",
         "excerpt": "Acme Cloud competes in the collaborative work management category.",
         "tags": ["market.category"]},
        {"statement": "Analysts expect the market to grow 13 percent a year.",
         "excerpt": "Analysts expect the collaborative work management market to grow 13 percent a year.",
         "tags": ["market.size_growth"]},
        {"statement": "Agencies are consolidating tools into a single workspace.",
         "excerpt": "Agencies are consolidating tools into a single workspace, Acme Cloud said.",
         "basis": "inference", "tags": ["market.trends"]},
        {"statement": "Buyers increasingly ask for built-in AI summaries.",
         "excerpt": "Buyers increasingly ask for built-in AI summaries in project tools.",
         "tags": ["market.trends"]},
    ],
    G2: [
        {"statement": "Beta Docs is a wiki for engineering teams at $8 per user per month.",
         "excerpt": "Beta Docs is a wiki for engineering teams and costs $8 per user per month.",
         "tags": ["competitors.alternative", "competitors.positioning", "competitors.pricing"],
         "competitor": {"name": "Beta Docs", "website": "https://betadocs.com"}},
        {"statement": "Gamma Boards positions itself as visual planning from $10 per user.",
         "excerpt": "Gamma Boards positions itself as visual planning for marketing teams with plans from $10 per user.",
         "tags": ["competitors.alternative", "competitors.positioning", "competitors.pricing"],
         "competitor": {"name": "Gamma Boards", "website": "https://gammaboards.com"}},
        {"statement": "Delta Desk is a client portal for agencies from $15 per seat.",
         "excerpt": "Delta Desk is a client portal for agencies with plans from $15 per seat.",
         "tags": ["competitors.alternative", "competitors.positioning", "competitors.pricing"],
         "competitor": {"name": "Delta Desk", "website": "https://deltadesk.com"}},
    ],
}
