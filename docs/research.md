# Research agent (Web Intelligence)

Agent 1 of the pipeline. It collects sourced evidence about a company and returns an evidence brief of cited claims. It does not write an ICP, positioning, or strategy; later agents cite its claim IDs.

Status: a standalone implementation in `src/ventureos/research/` with a Streamlit page and an optional local FastAPI backend. It is not connected to the harness or PostgreSQL yet.

## How it works

The research loop is a [DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview) ReAct agent (LangChain). The model reasons and calls tools; deterministic code validates everything it records.

1. Understand the request: research, follow-up, or clarify. A bare company URL skips the model call.
2. Fetch the main website first (a Tavily search restricted to the company domain, up to 3 pages).
3. The agent loops with tools: `field_status`, `search_web(query, site)`, `read_source`, `add_claim`, `reject_source`, `note_uncertainty`, `set_company`.
4. It collects 3 to 5 other websites (at most 2 pages each) so market, competitors, trends, signals and risks come from third parties.
5. The runner keeps re-prompting (up to 2 passes) until every field is filled or the budget is spent. Fields: the 9 categories each need 1 claim, plus the main site and 3 or more other websites. Budget: 5 searches.
6. Every page is cleaned (cookie, navigation, sign-in sentences removed), labeled by domain, and rejected if it looks like another organization.
7. `add_claim` checks each claim on the spot and returns the error to the agent so it can fix it. `finish` validates the whole brief.

## Brief schema

```json
{
  "schema_version": 2,
  "company": {"name": "Acme Cloud", "website": "https://acme.example.com"},
  "sources": [{"id": "s1", "url": "...", "title": "...", "kind": "first_party", "retrieved_at": "...", "published_at": null}],
  "claims": [{"id": "c1", "text": "...", "basis": "fact", "category": "customers", "source_id": "s1", "quote": "...", "published_at": "2020-04-01T00:00:00Z", "dated": true}],
  "coverage": {"company": 0, "product": 1, "pricing": 0, "customers": 1, "market": 0, "competitors": 0, "trends": 0, "signals": 1, "risks": 0},
  "gaps": ["company", "pricing", "market", "competitors", "trends", "risks"],
  "uncertainties": ["..."],
  "rejected_sources": [{"url": "...", "reason": "does not mention the company website"}]
}
```

Categories: company, product, pricing, customers, market, competitors, trends, signals, risks. Claim IDs are assigned by code, and `gaps` is computed from coverage, not by the model.

## Claim rules enforced in code

- `source_id` must be a collected source that was not rejected.
- `quote` must be 25 to 400 characters, appear verbatim in that source after whitespace normalization, and contain no cookie, navigation, or sign-in text.
- `basis` is `fact` or `inference`; `category` is one of the 9 above.
- Each claim needs its own quote. A quote that already supports another claim is rejected.
- Product, pricing and customers claims must cite a main-website page when one was collected.
- Every capitalized name and every number in the claim text must appear in its quote (a lexical check, not entailment).
- A `fact` that cites a forum post is downgraded to `inference`.
- Each claim carries its source's `published_at`. `dated` is true when that date is more than 12 months old; a missing date gives `dated: false`.
- Source filter: aggregator pages must mention the company website. News, review, forum and reference pages need a name match. Other pages need the website or at least 3 name mentions.
- A brief has 3 to 30 distinct claims from at least 2 sources, and the company website must match the request. Fewer than 3 other websites is reported in `uncertainties`, not treated as a failure.
- Gemini output that hits the token limit is rejected, never parsed.

## Run locally

Python 3.11+ is required for Research (DeepAgents). Put `TAVILY_API_KEY` and `GEMINI_API_KEY` in the root `.env` (git-ignored), then:

```bash
.venv/bin/python -m pip install -e '.[agent,chat,ui,test]'
.venv/bin/streamlit run UI/app.py
```

The page has one chat box: enter a company name or website, then ask follow-up questions. It calls the engine directly, keeps state in the browser session only, and has no authentication, so run it on your own machine.

The optional local API starts with `PYTHONPATH=src .venv/bin/python -m ventureos.research.api`. It is loopback only and keeps sessions in memory.

## Local API (optional)

- `POST /api/sessions` creates an in-memory conversation.
- `POST /api/sessions/{session_id}/messages` accepts `{"message":"Acme Cloud"}` and returns a job ID.
- `GET /api/jobs/{job_id}?after=0` returns progress events (`module`, `input`, `output`, `status`) and the result.
- `GET /api/sessions/{session_id}` returns history and the current brief.

Other agents can call `ResearchEngine.research(company, website, progress)` directly. It returns the brief and the evidence sources, without session or intent handling.

## Verify

```bash
PYTHONPATH=src python3 -m unittest tests/test_research.py tests/test_research_agent.py tests/test_research_policy.py -v
```

`tests/test_research_agent.py` runs the real DeepAgents loop with a scripted chat model and skips when DeepAgents is not installed. The suite uses provider doubles and `tests/fixtures/research_golden_basecamp.json`; it makes no live calls. API tests skip when the `chat` and `test` extras are missing. The golden fixture checks extraction contracts and grounding boundaries (cookie banner, wrong-entity page, coverage), not model accuracy.

## Known limits

- Quote matching proves provenance, not that a claim follows from its quote. The name and number check catches added entities, not changed meaning. A model entailment check is not implemented (planned).
- Source kinds come from a short domain list and are not credibility ratings.
- A name match cannot separate two companies with the same name unless the website is known. Pass the website for ambiguous names.
- The agent chooses its own queries within a 5-search budget. Per-category query templates (news, jobs, pricing, reviews) are not enforced.
- Each source keeps at most 20,000 characters of cleaned text.
- The live DeepAgents loop with Gemini is not covered by the tests; Gemini must support tool calling.
- `published_at` is set only when Tavily returns a date.
- Nothing is persisted. PostgreSQL storage of sources and claims is planned.
- Live Tavily and Gemini calls are not covered by the tests.

## Logs

Every function in the Research code logs when it starts, completes (with duration) or fails.

- Terminal and `logs/research.log` (rotating, git-ignored).
- Default level `INFO` shows pipeline steps. `VENTUREOS_LOG_LEVEL=DEBUG` shows every function.
- `VENTUREOS_LOG_DIR` changes the log folder.
- Logs hold names, durations, counts and error types only. No API keys, prompts, page text or model output.
