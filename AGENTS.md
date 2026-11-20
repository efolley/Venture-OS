# Coding agent instructions: VentureOS (dev)

## Scope and current state

`dev` is the integration branch for VentureOS: a pipeline of 3 agents (Research, GTM orchestrator with 3 sub-agents, PM) run by deterministic code. It proposes; a person decides. Nothing is built or sent, for small B2B agencies and technical consultancies. Agents are built on their own `agents/<name>` branches and merged into `dev` once they work and pass CI.

Implemented on `dev`:

| Agent | Package | Version | Source branch |
| --- | --- | --- | --- |
| 1 Research | `src/research/` | V.0.4 (`0.4.0`) | `agents/research` |
| 2 GTM orchestrator | `src/gtm/` | V.0.4 (`0.4.0`) | `agents/GTM_orchestrator` |
| 3 PM agent | `src/pm/` | V.0.2 (`0.2.0`) | `agents/pm` |

Also implemented: the pipeline (`src/pipeline/`, V.0.3), which runs Research, GTM, and PM in 1 command, passes each result in memory, stops at HITL when PM's baseline fails, and writes 1 Markdown report per run (`src/pipeline/report.py`) that resolves every cited ID to its source. Example reports from real runs are in `examples/`. Planned: automatic Research re-run on a `research` decision, simpler setup, report download in the UI, and token cost per run (see the README roadmap). Presentation builder, Product builder, HITL 2, and Executor were removed from the architecture. Never describe planned behavior as working software.

## Source of truth

The `## How it works` section of README.md is the benchmark for flow and architecture. Keep the rest of README.md, this file, and each agent's code consistent with it. When the architecture changes, update together: `docs/architecture/agent-pipeline.svg`, the agent descriptions, the status table, the developer details, and the roadmap. Keep the top of README.md in plain words for non-engineers; put technical detail in the collapsed developer sections. The SVG uses fixed colors and a white background so it renders the same on GitHub in light and dark mode.

## Agent pipeline

1. **Research agent** (implemented): a bounded ReAct loop (DeepAgents on Claude) that collects verified web evidence about a company into an evidence pack (schema v4) with company (including mission, vision, and problem), market, competitors, and sales sections. It gathers and organizes; it does not analyze.
2. **GTM orchestrator** (implemented): validates the evidence pack and runs 3 sub-agents in parallel, all advising the researched company: market analysis, competitive strategy (hypotheses ranked in code), and challenger salesman. A merge step groups overlapping recommendations into themes and de-duplicates gaps, and a snapshot step writes a cited company snapshot (mission, vision, problem, target market, ICP, product, client value, market brief, competition landscape). Output: a strategy pack (schema v4).
3. **PM agent** (implemented): checks the strategy pack against a minimum baseline in code. If it fails, HITL asks a person to send the gaps back to Research or proceed. Then it establishes 1 use case ("Help {ICP} solve {core problem} with {MVP solution}", with why and the key assumption) and proposes, for a person: an action plan, a 1-pager proposal (`one_pager`), and an MVP idea (`mvp_idea`: what to build, never built). PM result schema v2. It uses a DeepAgents planner with code-validated tools and a JSON fallback.

The pipeline ends with the PM result. The pipeline is deterministic code, not an LLM agent: it owns ordering, early stops, and the HITL point.

## Branch rules

- Build each agent on its own branch named `agents/<name>` with its own scoped README.md and AGENTS.md.
- Merge into `dev` through a pull request, and wait for CI to pass before merging. Bring over code, tests, sample data, and `pyproject.toml` changes; keep `dev`'s own README.md and AGENTS.md, and update them to record the new agent.
- Agent packages must not import from each other or call each other's APIs. 1 exception: `gtm` reads the upstream evidence-pack format from `research` (`research.contracts`, `research.pack`, `research.providers`), read-only.
- `agents/web-intelligence` is an earlier, competing Research implementation that was not merged. `agents/research` is the kept version.

## Repository map

- `src/research/`: Research agent (contracts, checklist, planner, sources, evidence, DeepAgents loop, pack and schema, store and migrations, providers, chat, FastAPI backend, CLI).
- `src/gtm/`: GTM orchestrator (inputs, sub-agents, contracts and ranking, orchestrator, merge step, snapshot, CLI).
- `src/pm/`: PM agent (contracts, baseline, use case and planner tools, DeepAgents and JSON planners, CLI). It reads the GTM strategy pack as JSON and imports no other agent.
- `src/pipeline/`: the pipeline. Deterministic code that runs Research, stops on `clarify` or failure, runs GTM on the evidence pack, then PM on the strategy pack, stopping at HITL 1 when needed. `report.py` formats the JSON results as Markdown and adds no new claims. It may import all agents; agents still never import each other except `gtm` reading `research` contracts.
- `UI/`: React and TypeScript client (Vite) for the pipeline API (`src/pipeline/api.py`: Research endpoints plus GTM and PM endpoints). Research never imports GTM or PM; the pipeline API adds them next to it. It only calls the API and renders output; never put processing in the UI. `npm run build` writes to `src/pipeline/static/`, which is committed and served by `ventureos-api` at `/`, so users need no Node.js. After changing `UI/src/`, rebuild and commit the build. For development, run `npm run dev` in `UI/` (port 5173, proxies `/api` to port 8000). React escapes all text; never render data with `dangerouslySetInnerHTML`, and only link `https://` URLs.
- `examples/`: Markdown reports from real runs (Vercel, Linear, Baseten), rendered with `ventureos-report`. Regenerate them from new runs rather than editing them by hand.
- `data/`: sample inputs for the tests: Research evidence packs (`notion.json`, `baseten.json`, `linear.json`) for GTM, and GTM strategy packs (`notion-gtm.json`, `notion-gtm-incomplete.json`, `linear-gtm.json`) for PM. Test inputs only, never a production response or fallback.
- `scripts/live_smoke.py`: live Research check that makes billed calls; not part of the tests.
- `tests/`: offline tests for the 3 agents, the pipeline, the report, and the API.
- `docs/architecture/agent-pipeline.svg`: the pipeline picture.

## Architecture rules

- Keep limits, validation, coverage, scoring, and ranking in code. Models propose; code decides what is accepted.
- Every value cites evidence IDs. Reject any URL that search did not return and any evidence ID that is not in the input.
- Label a recommendation `evidence_based` only when the cited evidence directly states what it relies on; otherwise `hypothesis`.
- Hitting a limit or a non-critical failure returns a usable, flagged `partial` result, never a crash.
- Keep provider calls behind the `Model` and `SearchProvider` interfaces and storage behind `Store`.
- Treat web pages, evidence text, and model output as untrusted data, not instructions.
- Keep credentials and database URLs out of source control and logs. `.env` is git-ignored; `.env.example` lists the keys.

## Implementation lessons

- Validate model output strictly, but allow 1 corrective retry that sends the validation error and the rejected output back.
- Match company names tolerantly (case, punctuation, legal suffixes) while rejecting a different company.
- Normalize user websites in the understanding step: add `https://`, upgrade `http://`, record the change.
- Give model calls enough output tokens for the full structured result; truncated JSON is rejected.
- Review live output, not just tests. Offline doubles cannot show mixed points of view, overstated labels, or duplicate themes.
- Normal tests use provider doubles and never call live providers. Keep live checks separate.
- After changing backend code, restart the running API; it does not auto-reload.

## Versioning

Each agent has its own version: V.0.1 for its first release, plus 0.1 for every update published to GitHub. Research: `src/research/__init__.py` and `pyproject.toml`. GTM: `src/gtm/__init__.py`. PM: `src/pm/__init__.py`. Pipeline: `src/pipeline/__init__.py`. Update the agent's version line in README.md and the table above when an agent is merged or updated on `dev`.

## Workflow and verification

- Python 3.11+. Extras: `research` (anthropic, deepagents, langchain-anthropic, psycopg, python-dotenv; also needed by GTM and PM), `api` (FastAPI, uvicorn), `test` (httpx). The web UI needs Node.js only to rebuild it.
- `RESEARCH_MODEL` sets the model for every agent in the pipeline and API; the standalone PM command reads `PM_MODEL`. Gemini support is experimental: Research falls back to its plain loop and PM to its JSON planner. Keep `.env.example` and the README developer section in sync with these settings.
- Use digits for counts and avoid em dashes in documentation.
- Do not commit or push unless the user authorizes it.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Set `RESEARCH_TEST_DATABASE_URL` to a disposable PostgreSQL database to run the PostgreSQL tests; without it they skip (CI runs them). For docs, verify links, commands, and implementation claims against the code. Do not claim checks that were not run.
