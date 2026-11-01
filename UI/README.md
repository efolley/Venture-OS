# Venture OS UI

Local Streamlit interface for Web Intelligence. It is an operator tool, not an authenticated public application.

## Start

Run from the repository root using your virtual environment:

```bash
python3 -m pip install -e '.[runtime,ui]'
PYTHONPATH=src:. python3 -m streamlit run UI/app.py --server.address 127.0.0.1
```

Open http://localhost:8501. Enable Demo mode and click Research company for a synthetic report without keys, database, or network. Demo deliberately ignores the inputs and labels the result synthetic.

## Live test requirements

Fill these values in the root `.env` file before starting Streamlit (existing shell variables take precedence):

- TAVILY_API_KEY: search API credential.
- ANTHROPIC_API_KEY: Claude API credential.
- ANTHROPIC_MODEL: model ID your account can access.
- VENTUREOS_DATABASE_URL: reachable PostgreSQL database dedicated to VentureOS.

Do not paste credentials into chat or commit them. The UI and live research CLI automatically load the root `.env` file without interpolation. Restart Streamlit after changing values already loaded into its process. Enter a real company name and its final HTTPS website, disable Demo mode, and click Research company. A bare domain is prefixed with https://. The server makes paid search/model requests and stores accepted results in PostgreSQL. No credentials are exposed in the UI.

Expect a short source-linked company overview, problems, trends, buying signals, uncertainties, and a downloadable JSON report. A provider may omit the overview; the UI then shows an explicit fallback instead of inventing a description. Sources are sampled up to 6 fetch attempts by default, not an exhaustive crawl. PDFs and JavaScript-rendered pages are unsupported; use the final HTTPS URL. Model inference and citations still require human review.

Results are held only in the current Streamlit session and persisted by the live runtime. A new submission clears the previous display. Each live click starts a fresh run. Editing a field or downloading a report does not initiate another research call.

## Verification

```bash
python3 -m pip install -e '.[runtime,test,ui]'
PYTHONPATH=src:. python3 -m unittest discover -s tests -p test_ui.py -v
```

UI tests use Streamlit AppTest and deterministic research responses. Live Basecamp research with Tavily, local Ollama, and PostgreSQL has been verified. Streamlit form behavior follows the [official form guide](https://docs.streamlit.io/develop/concepts/architecture/forms).

## Local PostgreSQL

The development database is `ventureos` on `127.0.0.1:5433`, with files under ignored `runs/postgres`. It uses local trust authentication and is intended only for development on this machine. Its URL is already in ignored `.env`.

Start after a reboot, from the repository root:

```bash
pg_ctl -D runs/postgres -l runs/postgres.log -o '-h 127.0.0.1 -p 5433 -k /tmp' start
```

Stop it with `pg_ctl -D runs/postgres stop`. Keep the data directory; it contains your local research results. `.env.example` contains empty API placeholders only.

## Ollama testing

The local `.env` selects `MODEL_PROVIDER=ollama` and `OLLAMA_MODEL=qwen3:8b`. Run `ollama pull qwen3:8b` once and keep Ollama running on 127.0.0.1:11434. Anthropic settings are not required in this mode. Tavily and PostgreSQL are still needed for live web research.

```text
MODEL_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
TAVILY_API_KEY=your-key
VENTUREOS_DATABASE_URL=postgresql://localhost:5433/ventureos
```

Restart Streamlit after configuration changes. To use Claude again, set MODEL_PROVIDER=anthropic and supply ANTHROPIC_API_KEY and ANTHROPIC_MODEL. Ollama uses JSON output with thinking disabled, local-only networking, and a 120-second model timeout; slow hardware or a cold model can time out. Provider input-token costs are irrelevant to local Ollama, but the existing conservative output-unit budget still applies.

## Research progress

While a run is active, the status panel reports configuration checks, searching, scraping, processing, validation, and saving. It finishes as Company report ready or Research stopped. These labels reflect actual execution stages, not percentage estimates. Very short phases may finish between UI polls. Fixture mode does not report database saving.

## Terminal and file logs

Application functions log started, completed, and failed events to stderr and `logs/YYYY-MM-DD.log`. Entries include timestamps, function names, durations, process/thread IDs, and exception types. Arguments, return values, raw exception messages, prompts, company evidence, credentials, and database URLs are excluded.

All processes append to the same daily file using a cross-process file lock. Dates and timestamps use America/New_York time; long-running processes switch files at midnight. Daily files are not split by size or automatically deleted. Earlier per-process files are retained. logs/ is ignored by Git. A file-write setup failure falls back to terminal logging. The logging infrastructure itself is not recursively instrumented, and Protocol declarations have no executable body to log.

The research subprocess writes file logs immediately; its captured log lines are relayed to the Streamlit terminal when it finishes. UI phase updates continue live while it runs. No server needs to be launched to inspect existing files:

```bash
tail -f logs/$(TZ=America/New_York date +%F).log
```

Logging tests verify console/file output, payload exclusion, midnight rollover, concurrent process writes, duplicate-handler prevention, and context-manager behavior. The full regression suite passed 71 tests using the existing disposable PostgreSQL instance. No UI or database service was launched for that verification.

## Specific failures

Failed research now reports the last phase, innermost application function, exception type, and a safe explanation in the UI. For example: Research failed during processing. Function: ventureos.web_live.OllamaModel.__call__ | ValueError | Ollama stopped before completing valid JSON. Raw exception messages, credentials, and provider payloads are excluded. Runtime errors are returned in a structured CLI error field; historical failures do not retain this diagnostic in PostgreSQL.

## Data Management

Use the left sidebar to switch between Research and Data Management using page buttons. History reads the latest 100 valid successful Web Intelligence artifacts from the local-ui and local CLI scopes in PostgreSQL, newest first. Select a company/date/run entry to view its summary, findings, sources, limitations, and download. Refresh results reloads the list. Demo reports and failed tasks are excluded. This remains a local operator interface, not an authenticated multi-user history service.

Research reports now include quoted excerpts, discovered source categories, publication-date warnings, and unresolved conflicts. View these in Evidence quality and conflicts and Sources and limitations.
