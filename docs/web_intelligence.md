# Web Intelligence

Run a synthetic example immediately, or use Tavily search, direct HTTPS fetch, Claude analysis, and PostgreSQL memory for real company research.

## Try without credentials

```bash
PYTHONPATH=src python3 -m ventureos.research --fixture
```

Expect JSON with status `succeeded`, source text, problems, buying signals, and uncertainties. Fixture mode is synthetic, uses no network or database, and is explicitly labeled `fixture`. It does not prove real-world research quality.

## Run live research

Install optional runtime dependencies into your virtual environment:

```bash
python3 -m pip install -e '.[runtime]'
```

Fill `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, and `VENTUREOS_DATABASE_URL` in the root `.env` file using your own credentials. Set `ANTHROPIC_MODEL` there to a Claude model ID available to your account. Existing shell variables take precedence; the CLI also accepts --model. Live requests use paid provider APIs; never commit keys.

```bash
PYTHONPATH=src python3 -m ventureos.research \
  --company "Example" \
  --website "https://example.com" \
  --model "$ANTHROPIC_MODEL" \
  --tenant local \
  --run-id example-1
```

Use a final HTTPS URL: up to 3 public HTTPS redirects are followed; nonstandard ports are rejected. Output contains `mode: live`, status, run ID, persistence flag, and an accepted artifact on success. A failure exits nonzero. Provide a new run ID to refresh; repeating a successful ID reuses its result. Keep company and task inputs unchanged when reusing IDs. `--output report.json` writes to a new file without overwriting existing files. The CLI processes the exact selected task, not unrelated queued work. Tenant selection is local operator scope, not authentication.

The CLI/UI default is at most 6 source fetch attempts across 4 categorized searches; `--max-pages` accepts 1 to 10. The library request default remains 3. Each analysis attempt reserves 2000 model output units (at most 2 attempts) and 1 unit per tool call using existing runtime budgets. These units are not total token billing or dollar limits: provider input tokens and search credits are billed separately. Provider model access, workspace configuration, quotas, and website accessibility can affect success.

The implementation follows [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) and [Claude Messages](https://platform.claude.com/docs/en/api/messages/create); it uses the supported legacy x-api-key header and API version 2023-06-01 for Claude.

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

Submit a Task with agent_id `web_intelligence` and payload `{"company": "Example", "website": "https://example.com"}`. Optional payload fields are `questions` (a nonempty list) and `max_pages` (1 to 10, library default 3), and `max_source_age_days` (1 to 3650, default 365). Authenticate in the host application and supply a Principal scoped to the tenant with `task:submit`, `task:execute`, `agent:web_intelligence`, `model:research-model`, `tool:web_search`, and `tool:web_fetch`; add `research:read` for memory reads. Use `runtime.submit(principal, task)` and `runtime.work_once(principal)`.

The model must return JSON with problems, trends, and buying_signals lists; each finding has text, source_ids, and basis (`fact` or `inference`). It must also return an uncertainties list. Unknown source IDs and malformed output are rejected. Empty findings are allowed when evidence is inconclusive. Citation validation does not prove factual accuracy.

## Memory and refresh

Successful runtime completion saves the accepted artifact in PostgreSQL. `memory.latest(principal, tenant, website, max_age_seconds=86400)` reads the latest accepted result for the exact website URL, or returns None if missing or stale. All included sources must meet the freshness window. Submit a new task ID to refresh; this does not automatically reuse old evidence. Failed tasks do not publish accepted memory. Model source excerpts are capped at 5000 characters per page. The local BlobStore saves the full sanitized parsed text returned by the fetcher, capped at 200000 characters per page, under ignored runs/blobs; raw HTML and unbounded files are not retained.

## Boundaries

The included transport pins connections to validated public DNS addresses with TLS hostname verification, follows up to 3 public-page HTTPS redirects with destination validation and refuses compressed responses, accepts HTTPS port 443 only, caps responses at 1 MB, and spaces requests by 1 second per client. Socket operations use timeouts; these are not hard end-to-end deadlines and DNS resolver time is OS-controlled. HTML scripts/styles are excluded; PDF and JavaScript-rendered pages are unsupported. Failed pages or excessive redirects may leave evidence gaps. Lexical URL validation alone is not SSRF protection. Search processes at most 20 candidates and fetch attempts are bounded by max_pages. OSError fetch failures become uncertainty entries when other evidence succeeds; no evidence fails before model analysis. Other adapter errors fail closed under runtime policy. Heuristic content checks block selected injection patterns and redact selected PII; they are not complete defenses. Retrieval time is not publication time or proof of real-time accuracy.

## Verification

All module and adapter tests live in `tests/test_web_intelligence.py`. Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p test_web_intelligence.py -v
```

Install runtime/test extras and set VENTUREOS_TEST_DSN to a disposable PostgreSQL database for the integration case. Without it, that case skips. Reports in tests/reports/web_intelligence_live_* capture pre-implementation failures and post-implementation results. The latest full suite passed 54 tests, including 20 module/adapter cases and PostgreSQL integration. A public example.com HTTPS fetch was smoke-tested successfully. Provider calls use deterministic doubles in the suite; live Tavily search, public-page scraping, local Qwen generation, database records, and snapshot retrieval have now been verified with Basecamp. Paid Claude analysis remains optional and unverified here.

## Company summary UI

The research prompt now requests an optional company_summary object with text, source_ids, and basis. When provided, it is validated with the same provenance rules as findings. See [the Streamlit UI](../UI/README.md) for company/website inputs and summary display.

## Local model option

Set MODEL_PROVIDER=ollama and OLLAMA_MODEL=qwen3:8b in root .env, install the model with `ollama pull qwen3:8b`, and keep Ollama running. Live research then needs Tavily and PostgreSQL but no Anthropic key.

```bash
PYTHONPATH=src python3 -m ventureos.research --provider ollama --model qwen3:8b --company "Example" --website https://example.com
```

The adapter uses the local [Ollama chat API](https://docs.ollama.com/api/chat) with JSON output and thinking disabled. Hosted and remote Ollama endpoints are not supported.

## Structured local-model output

Ollama research calls now use a JSON schema requiring the overview, findings arrays, uncertainties, fact/inference labels, and nonempty citations constrained to fetched source IDs. Generic JSON mode could return a source object instead of a report; validation continues to reject malformed or unsupported output. Summaries keep at most 2 complete generated sentences when sentence boundaries are available, discarding trailing partial text without adding claims. Schema compliance does not independently prove factual accuracy.

## Completed research workflow

The agent attempts 4 categorized searches: official company material, recent news, careers/job postings, and independent supporting material. Sources are classified by discovery query, not certified for credibility. Fetch attempts are round-robin across categories and bounded; missing categories and search/fetch failures are explicit uncertainties.

Sources include retrieval time, publication time when a recognized HTML meta tag supplies it, category, and a tenant-scoped snapshot reference. assess_quality marks publications older than the request's max_source_age_days as stale and flags unknown publication dates. Retrieval time alone does not prove a source is current. Buying signals supported only by stale sources are rejected. Conflicts require at least 2 distinct valid sources and matching excerpts; they remain unresolved for review.

Ollama selects quotes from actual source excerpts through its output schema. Accepted quotes must match cited source text after whitespace normalization. Legacy injected providers without quotes receive explicitly labeled context_only excerpts; these are not verified supporting quotations. Even quote_matched_not_entailment_verified evidence does not establish that a generated claim follows logically from its source. Fact/inference labels are model judgments subject to review.

Successful completion transactionally writes ventureos_tasks, ventureos_research_sources, and ventureos_research_findings. LocalBlobStore stores parsed-text snapshots by tenant and content hash; research:read authorization is required for retrieval. Blob files may remain after failed tasks because disk and PostgreSQL do not share a transaction. No RAG is used. Re-running schema initialization creates the new tables without backfilling historical reports.

## Completion verification

- tests/test_web_intelligence.py holds module and integration cases, including stale sources, conflicting citations, missing sources, PII, injection, quotes, tenant isolation, snapshots, and database records.
- tests/fixtures/web_intelligence_evals.json contains 8 golden acceptance/evidence cases; these test extraction contracts and grounding boundaries, not a statistical model-accuracy benchmark.
- Run `PYTHONPATH=src python3 -m ventureos.evals --research tests/fixtures/web_intelligence_evals.json` for offline evals. CI runs them as a release check.
- tests/reports/web_completion_pre.txt and web_completion_full_post.txt preserve before/after outcomes; the final suite passes 96 tests.
- tests/reports/web_completion_live_verification.json records a successful real Basecamp run with 5 sources covering all 4 categories, normalized PostgreSQL records, validated quotes, and readable snapshots. The report is in ignored runs/basecamp-complete-v2-final.json.

The agent is a bounded research tool, not an exhaustive crawler or autonomous fact checker. Full semantic truth verification, source credibility certification, image/PDF extraction, browser-rendered pages, and production hardening are outside this completed backlog.
