# VentureOS

> **Give it a company name. Get back a cited go-to-market strategy, a 1-pager, and an MVP idea a person can act on.**

VentureOS is a small team of AI agents. It researches a company, works out how the company should go to market, and proposes what to pitch and what to build next. Every claim links back to a real source, and plain code, not the AI, decides what counts as evidence.

It is built for small B2B agencies and technical consultancies getting ready for a client conversation. Research and writing that would normally take a day comes back in a few minutes.

**VentureOS proposes; a person decides.** It does not send emails, build products, or take actions on its own.

For a step-by-step tour of a full run, see the [walkthrough](docs/walkthrough.md).

## The problem, and who it is for

**The problem.** Before a first call with a prospect, a small agency or consultancy needs to understand that company: its market, its competitors, who it sells to, and where it is weak. Then it needs to turn that into a concrete idea to pitch. Done properly, that takes a senior person half a day to a day per prospect, so most teams skip it and turn up with a generic pitch.

**Who it is for.** Founders and partners at B2B agencies and technical consultancies with about 2 to 30 people, such as AI and dev shops, GTM consultancies, and fractional product teams. They pitch several new prospects a month, and the person who does the research is also the person who sells.

**Why they care:**
- **Time.** A day of prep becomes about 3 minutes, plus 15 minutes of review.
- **A sharper pitch.** They arrive with 1 specific use case, a 1-pager they can send, and an MVP idea they could build for the client, instead of "we do AI".
- **Trust.** Every claim links to its source and guesses are labeled as hypotheses, so they do not repeat something made up in front of a client.
- **Control.** It only proposes. Nothing is sent or built without them.

## Example: input and output

**Input:**

```bash
PYTHONPATH=src python3 -m pipeline Baseten --website baseten.co
```

**Output** (about 2.5 minutes, from a real run, shortened):

> **Use case:** Help ML teams at AI-native startups solve slow, fragile prototype-to-production launches that break under real traffic, with a pre-launch production readiness check for model endpoints.
>
> **Key assumption (to test):** these teams see launch delay as a top blocker they would pay to fix. *Not yet proven.*
>
> **Action plan:**
> 1. Validate: interview teams on prototype-to-production blockers.
> 2. Validate: test the ideal customer against the 2-tier sales motion.
> 3. Validate: test the readiness-check concept with prospects.
> 4. Prepare: draft the readiness pitch.
> 5. Deliver: build a minimal check for 1 endpoint, only if validation says go.
>
> **1-pager:** "Get models from prototype to production without the weeks-long fragile launch." It has 5 key points and 4 proof points, each citing its source (e1, e2, e7, e8). The call to action is a 30-minute interview.
>
> **MVP idea:** endpoint intake, a launch-style traffic test, a failure report, and a pass/fail summary. Pricing, training, and support for other providers are out of scope.

Behind that output sit 25 sourced facts, 16 recommendations from the 3 specialists, and a cited company snapshot. Results vary from run to run, so review each one before you share it.

## How it works

<p align="center">
  <img src="docs/architecture/agent-pipeline.svg" alt="VentureOS pipeline: Researcher, then GTM orchestrator with 3 parallel specialists, then PM agent with a human check, ending in an action plan, a 1-pager, and an MVP idea for a person" width="620">
</p>

A simple script (the "pipeline") runs 3 agents, one after another:

1. **Researcher.** Searches the web and reads the company's site, its market, and its competitors. It keeps only facts it can quote word for word from a real page. It stops when it has enough, or when it runs out of budget.
   *You get:* an evidence pack, which is a list of sourced facts.

2. **GTM orchestrator.** Gives the evidence to 3 specialists who work in parallel, like a small consulting team:
   - **Market analyst:** how big the market is, where it is heading, and which segments to focus on.
   - **Competitive strategist:** how the company compares with alternatives, and which gaps are worth going after. Code scores and ranks the gaps.
   - **Challenger salesperson:** who the ideal customer is, what fresh insight to lead with, and how to reach them.

   It then merges their advice and writes a 1-page company snapshot covering mission, problem, customers, product, market, and competition.
   *You get:* a strategy pack.

3. **PM agent.** First it checks that the strategy covers the basics, such as mission, customers, and competitors. If something is missing, it **stops and asks you** whether to research more or carry on with the gaps marked unknown. Then it picks 1 use case, written as *"Help {customer} solve {problem} with {MVP}"*, and proposes:
   - **An action plan:** 3 to 7 next steps. At least 1 step tests the riskiest assumption.
   - **A 1-pager:** a short proposal you can read, edit, and send.
   - **An MVP idea:** what to build and for whom, the must-have features, and what is out of scope. It describes the MVP but does not build it.

   *You get:* a plan for a person to review and act on.

### Why you can trust the output

- **Sourced.** Every fact cites the page it came from, and links that the search never returned are rejected.
- **Honest labels.** Advice is labeled `evidence_based` only when a source directly supports it. Everything else is labeled a `hypothesis`.
- **Code decides.** The AI proposes, then code checks limits, citations, scores, and rankings before anything is accepted.
- **No crashes on failure.** If a step runs out of budget or a specialist fails, you still get a usable result marked `partial`.

## Status

| # | Agent | Status | Version |
| -- | --- | --- | --- |
| 1 | Researcher | Working | V.0.3 |
| 2 | GTM orchestrator (3 specialists and snapshot) | Working | V.0.4 |
| 3 | PM agent (human check, plan, 1-pager, MVP idea) | Working | V.0.2 |
| | Pipeline (runs all 3 in 1 command) | Working | V.0.2 |

All 3 agents run end to end, from the command line and from the web UI. Known limits:
- Output quality varies from run to run, and the strategy can still be thin. See the TODO list below.
- If you choose "research more", VentureOS lists the gaps, but you have to start the new Research run yourself.
- Without a database, Research runs are kept in memory and are lost when the API restarts. GTM and PM results are saved to `runs/`.

## Quick start

You need Python 3.11 or later, an [Anthropic API key](https://console.anthropic.com/), and a [Tavily API key](https://tavily.com/) for web search. Live runs make billed API calls.

```bash
python3 -m pip install -e '.[research,api,ui,test]'
```

```bash
cp .env.example .env
```

Put your `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` in `.env`. Then run the whole flow for 1 company:

```bash
PYTHONPATH=src python3 -m pipeline Linear --website linear.app
```

It takes a few minutes and writes 3 files to `runs/`:

| File | What is in it |
| --- | --- |
| `linear-research.json` | The evidence pack, with every sourced fact |
| `linear-gtm.json` | The strategy pack, with the snapshot and recommendations |
| `linear-pm.json` | The use case, action plan, 1-pager, and MVP idea |

If the PM agent stops to ask you (exit code 5), run the same command again with `--decision proceed` or `--decision research`.

### Web UI

Start the backend:

```bash
PYTHONPATH=src python3 -m pipeline.api
```

Then start the UI in a second terminal:

```bash
streamlit run UI/app.py
```

Type a company name or website in the chat. The chat shows the research first, then the strategy, then the plan, with a **1-pager** tab and an **MVP idea** tab. When the PM agent needs a decision, it shows 2 buttons: **Research more** and **Proceed with gaps**. The **Data management** tab lists every past run.

The backend listens only on `127.0.0.1` and has no login, so run it only on your own machine.

### How to test it

1. **Offline tests** (free, about 1 second). They check the rules, limits, and the human check without calling any API:
   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests
   ```
2. **Live run** (billed, about 2.5 minutes). Run 1 company and read the log. Each `[pipeline]` line shows how long the step took:
   ```bash
   PYTHONPATH=src python3 -m pipeline Vercel --website vercel.com --output-dir runs/test
   ```
3. **Human check.** Give the PM agent an incomplete strategy pack. It should stop and ask, with exit code 3 (the full pipeline uses exit code 5 for the same stop):
   ```bash
   PYTHONPATH=src python3 -m pm data/notion-gtm-incomplete.json
   ```
   Run it again with `--decision proceed`. You should get a plan marked `partial`.

A good result:
- The use case is not just the company's own product.
- The plan starts with at least 1 validate step.
- Every claim has a source ID.
- Guesses are labeled as hypotheses.

The [walkthrough](docs/walkthrough.md) explains each step in detail.

## Details for developers

<details>
<summary>Agent 1: Researcher</summary>

- **Input:** a company name or website and optional instructions, such as `EU only`. A re-run also takes the previous run ID and its gaps.
- **Loop:** a [DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview) ReAct agent on Claude Haiku 5.5 with 5 tools: `coverage_status`, `search_web`, `read_source`, `add_evidence`, and `note_gap`. Code validates every tool call.
- **Name only:** 1 search and 1 model call fix the spelling and propose up to 5 official websites. The run stops with `clarify` until you pick one.
- **Evidence rules:**
  - Excerpts are 25 to 400 characters and appear word for word in their source.
  - Names and numbers in a statement must appear in its excerpt.
  - Facts from forums become inferences.
  - Competitor facts come only from comparison pages, review pages, or the competitor's own site.
- **Checklist (in code):**
  - Company: offering, mission, and problem, with vision optional.
  - Market: category, size or growth, and at least 2 trends.
  - Competitors: 3 to 5, with positioning and pricing.
  - Sales: target customer, buyer, pricing model, and channel.
- **Limits:** 12 searches, 36 sources, and 36 model calls. Hitting a limit returns a `partial` pack with its gaps.
- **Output:** an evidence pack, schema v4 (`src/research/pack.schema.json`).

</details>

<details>
<summary>Agent 2: GTM orchestrator</summary>

- **Input:** an evidence pack (schema v4) and optional instructions. It never searches the web.
- **Sub-agents:** they run in parallel. Each sees only the evidence tagged for its job and must cite evidence IDs. Invalid output gets 1 corrective retry. A sub-agent that still fails is marked `failed`, and the run continues.
- **Ranking:** each competitive hypothesis gets 4 sub-scores from 1 to 5: `pain`, `gap_size`, `competitor_weakness`, and `fit`. Code adds them into a score from 4 to 20 and ranks the hypotheses.
- **Merge:** 1 model call groups overlapping recommendations into themes, and code validates the grouping.
- **Snapshot:** code decides what each line may cite. A line with nothing to cite is `unknown` and is never sent to the model. Code validates the lines one at a time and trims an over-long line to whole sentences.
- **Output:** a strategy pack, schema v4.

</details>

<details>
<summary>Agent 3: PM agent</summary>

- **Input:** a strategy pack (schema v4) and an optional decision, `proceed` or `research`.
- **Baseline (in code):**
  - Research is complete.
  - 8 snapshot lines are found (vision is optional).
  - All 3 sub-agents completed.
  - There are at least 2 ranked hypotheses, 2 sales recommendations, and 1 market recommendation.
- **Human check (HITL):** if the baseline fails and no decision was given, PM stops with `hitl_required`. It lists the missing items and the Research gaps that would fix them.
  - `research` returns those gaps.
  - `proceed` plans with the gaps marked unknown and marks the result `partial`.
- **Planner:** a DeepAgents agent with code-checked tools: `set_use_case`, `add_action`, `set_one_pager`, `set_mvp_idea`, and `plan_status`. A single JSON call completes anything the agent leaves unfinished. Every item must cite IDs from the strategy pack.
- **Output:** a PM result, schema v2, with `baseline`, `hitl`, `use_case`, `action_plan`, `one_pager`, and `mvp_idea`.

</details>

<details>
<summary>Commands and API</summary>

Each agent also runs on its own:

```bash
PYTHONPATH=src python3 -m research "Basecamp" --website basecamp.com
```

```bash
PYTHONPATH=src python3 -m gtm data/notion.json --output runs/notion-gtm.json
```

```bash
PYTHONPATH=src python3 -m pm data/notion-gtm.json --output runs/notion-pm.json
```

Pipeline options:
- `--decision proceed|research`
- `--no-pm` stops after GTM.
- `--instructions "..."`
- `--output-dir`

Set `RESEARCH_DATABASE_URL` to store Research runs in PostgreSQL.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/sessions`, `POST /api/sessions/{id}/messages`, `GET /api/jobs/{id}` | Research chat |
| `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/rounds` | Stored Research runs |
| `POST /api/gtm/runs`, `GET /api/gtm/jobs/{id}`, `GET /api/gtm/runs/{research_run_id}` | GTM on a stored evidence pack |
| `POST /api/pm/runs`, `GET /api/pm/jobs/{id}`, `GET /api/pm/runs/{research_run_id}` | PM on a saved strategy pack (`decision` is optional) |

</details>

<details>
<summary>Tests</summary>

The tests use fake providers and never call live services:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

To run the PostgreSQL tests, set `RESEARCH_TEST_DATABASE_URL` to a disposable PostgreSQL database. CI always runs them. A live Research check makes billed calls and is not part of the tests:

```bash
PYTHONPATH=src python3 scripts/live_smoke.py linear.app baseten.co
```

</details>

<details>
<summary>Project structure</summary>

```text
src/research/   Agent 1: Researcher
src/gtm/        Agent 2: GTM orchestrator and its 3 sub-agents
src/pm/         Agent 3: PM agent
src/pipeline/   Runs the 3 agents in order; also the API for the UI
UI/             Streamlit web UI (display only)
data/           Sample packs used by the tests
tests/          Offline tests
docs/           Pipeline picture
```

</details>

## Roadmap

- [x] Researcher, GTM orchestrator, and PM agent working end to end
- [x] Human check before planning (research more or proceed)
- [x] PM output as an action plan, a 1-pager, and an MVP idea for a person
- [ ] "Research more" restarts Research on the gaps automatically
- [ ] Simple setup: file storage by default and a one-command start
- [ ] Example outputs for well-known companies in `examples/`
- [ ] Download the 1-pager and MVP idea as Markdown

### TODO: output quality

1. [ ] GTM: give the sub-agents the mission, problem, and offering evidence, so they stop reporting the mission as missing.
2. [ ] Snapshot: keep lines descriptive, and describe the ideal customer by role or segment, not by pricing tier.
3. [ ] Research: check the market category against what the company sells before sizing the market.
4. [ ] Research: require competitor evidence from at least 2 independent sources.
5. [ ] GTM: require at least 1 recommendation that is not about pricing.
