# Web Intelligence

The simple plugin researches a company using injected read-only search/fetch tools and a model provider. It returns problems, trends, buying signals, uncertainties, source text excerpts, and retrieval timestamps. It does not include live provider credentials, network adapters, scheduling, RAG, or a research CLI.

## Register with the existing runtime

```python
from ventureos.execution import Task
from ventureos.gateways import ModelGateway, ToolGateway, Principal
from ventureos.runtime import RuntimeHarness
from ventureos.store import PostgresStore
from ventureos.web_intelligence import WebIntelligenceAgent, valid_research, ResearchMemory

# Supply these callables from your trusted integration code:
# search_handler(args) -> {"urls": ["https://example.com/about"]}
# fetch_handler(args) -> {"url": args["url"], "text": "Source text"}
# provider(model, prompt, *, max_units, timeout) -> ModelReply

def configure(dsn, search_handler, fetch_handler, provider):
    store = PostgresStore(dsn)
    store.initialize()
    tools = ToolGateway()
    tools.register("web_search", search_handler, side_effect=False)
    tools.register("web_fetch", fetch_handler, side_effect=False)
    runtime = RuntimeHarness(store, tools=tools, models=ModelGateway(provider))
    runtime.register("web_intelligence", WebIntelligenceAgent("research-model"), valid_research)
    return runtime, ResearchMemory(store)
```

Submit a Task with agent_id `web_intelligence` and payload `{"company": "Example", "website": "https://example.com"}`. Optional payload fields are `questions` (a nonempty list) and `max_pages` (1 to 5, default 3). Authenticate in the host application and supply a Principal scoped to the tenant with `task:submit`, `task:execute`, `agent:web_intelligence`, `model:research-model`, `tool:web_search`, and `tool:web_fetch`; add `research:read` for memory reads. Use `runtime.submit(principal, task)` and `runtime.work_once(principal)`.

The model must return JSON with problems, trends, and buying_signals lists; each finding has text, source_ids, and basis (`fact` or `inference`). It must also return an uncertainties list. Unknown source IDs and malformed output are rejected. Empty findings are allowed when evidence is inconclusive. Citation validation does not prove factual accuracy.

## Memory and refresh

Successful runtime completion saves the accepted artifact in PostgreSQL. `memory.latest(principal, tenant, website, max_age_seconds=86400)` reads the latest accepted result for the exact website URL, or returns None if missing or stale. All included sources must meet the freshness window. Submit a new task ID to refresh; this does not automatically reuse old evidence. Failed tasks do not publish accepted memory. The source excerpts are capped at 12000 characters per fetched page; full snapshots and BlobStore remain planned.

## Boundaries

Web adapters must enforce timeouts, response size limits, rate limits, DNS/IP restrictions at connection time, and redirect validation. Lexical URL validation in this module alone is not SSRF protection. Search processes at most 20 candidates and fetch attempts are bounded by max_pages. OSError fetch failures become uncertainty entries when other evidence succeeds; no evidence fails before model analysis. Other adapter errors fail closed under runtime policy. Heuristic content checks block selected injection patterns and redact selected PII; they are not complete defenses. Retrieval time is not publication time or proof of real-time accuracy.

## Verification

All module tests live in `tests/test_web_intelligence.py`. Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p test_web_intelligence.py -v
```

Install runtime/test extras and set VENTUREOS_TEST_DSN to a disposable PostgreSQL database for the integration case. Without it, that case skips. Reports in tests/reports/web_intelligence_* capture pre-implementation failure, incremental checks, and the final full-suite run (46 tests passed, including 12 module cases). These tests use deterministic provider doubles; live research quality remains unverified.
