# VentureOS walkthrough

This page follows 1 company through a full VentureOS run, from the name you type to the plan you get back. It explains what happens at each step, what you can see in the log, and how to check the result.

The examples come from real runs on Baseten, Linear, and Vercel. Model output differs a little on every run.

## The big picture

```text
Company name or website
        |
        v
1. Researcher ............ evidence pack (sourced facts)
        |
        v
2. GTM orchestrator ...... strategy pack (3 specialists + company snapshot)
        |
        v
3. PM agent .............. checks the basics
        |                    missing something? -> a person chooses: research more, or proceed
        v
Plan for a person ........ use case, action plan, 1-pager, MVP idea
```

The pipeline (`src/pipeline/`) is plain code, not an AI agent. It runs the 3 agents in order, passes each result to the next in memory, and stops early when a step cannot continue. Nothing is sent, built, or published. A person reads the result and decides what to do.

A full run takes about 3 minutes:

| Step | Typical time |
| --- | --- |
| Researcher | 70 to 110 seconds |
| GTM orchestrator | about 40 seconds |
| PM agent | about 40 seconds |

## Before you start

You need Python 3.11 or later, an Anthropic API key, and a Tavily API key. You do not need Node.js. Live runs make billed API calls. Run these once from the project folder:

```bash
python3 -m venv .venv && source .venv/bin/activate
```

```bash
python3 -m pip install -e '.[research,api,test]'
```

```bash
cp .env.example .env
```

Put `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` in `.env`.

## Step 0: start a run

There are 3 ways to run the same pipeline. Pick 1.

**Web UI.** Start the server from the project folder, then open http://127.0.0.1:8000:

```bash
ventureos-api
```

Type `baseten.co` in the chat, or click a suggestion, and press Enter. The chat shows each step as it happens. Stop the server with `Ctrl+C` when you are done.

**Full stack with Docker.** `docker compose up --build` starts PostgreSQL, Redis, Kafka, the API, 2 workers, and the API gateway; open http://127.0.0.1:8080. The chat works the same, but your chats survive restarts and the work runs in the workers.

**Command line.** Run 1 command and read the log:

```bash
ventureos-pipeline Baseten --website baseten.co
```

**Tip:** give a website, not just a name. With a name only, the Researcher checks the spelling, proposes up to 5 official websites, and stops so you can pick 1 (status `clarify`). In the web UI, click your choice. On the command line, run again with `--website`. That stops a run from researching the wrong company.

## Step 1: Researcher

**Goal:** collect facts about the company that a person could check.

**What it does:**
1. Fixes the website (for example, it adds `https://`).
2. Runs a loop: decide what is missing, search, read a page, and record facts. An AI agent chooses what to search next. Code checks every step.
3. Starts with the company's own site (offering, mission, problem, pricing), then the market (category, size, trends), then competitors (3 to 5, with positioning and pricing), then sales (target customer, buyer, channel).
4. Stops when the checklist is complete or it hits a limit: 12 search rounds, 36 sources, and 36 model calls.

**The rules that keep it honest:**
- A fact counts only if its quote appears word for word on the page.
- Names and numbers in a fact must appear in its quote.
- Facts from forums count as inferences, not facts.
- Pages about a different company are rejected.

**In the log:**

```text
[plan] running {"round": 1, "gap": "company", "query": "Linear about mission vision", "site": "linear.app"}
[collect] success {"round": 1, "kept": 3, "skipped": 1}
[coverage] success {"round": 3, "items": 4, "coverage": {"company": {"status": "partial", "missing": ["company.mission"]}, ...}}
[pipeline] done {"step": "research", "status": "complete", "duration_s": 72.7}
```

**Output:** `runs/<company>-research.json`, the evidence pack. Each fact has an ID (`e1`, `e2`, and so on), a statement, a quote, and its source URL. In the test runs, packs had 23 to 25 facts.

**In the web UI:** a "Researching the web" line with a timer, and each round as it happens, such as "Round 2: searching for market" and "Round 2: kept 3 pages, skipped 1". When it finishes, the evidence pack card shows the coverage of company, market, competitors, and sales, the key facts with their IDs, and the full evidence table.

**If it is incomplete:** the pack is marked `partial`, lists its gaps, and the run continues. It never crashes. In the web UI, a **Research the missing items** button starts a second Research run on just those gaps.

## Step 2: GTM orchestrator

**Goal:** turn facts into go-to-market advice for the company.

**What it does:**
1. Sends the evidence to 3 specialists at the same time:
   - **Market analyst:** market size, trends, and which segments to focus on.
   - **Competitive strategist:** gaps versus competitors. Each idea gets 4 scores (pain, gap size, competitor weakness, and fit), and code adds them up and ranks the ideas.
   - **Challenger salesperson:** the ideal customer, a fresh insight to lead with, and how to reach them.
2. Each specialist sees only the facts it needs and must cite fact IDs. A recommendation is labeled `evidence_based` only when a fact directly supports it; otherwise it is labeled `hypothesis`.
3. A merge step groups overlapping advice into themes.
4. A snapshot step writes 9 short lines: mission, vision, problem, target market, ideal customer, product, client value, market brief, and competition. A line with no supporting fact is marked `unknown` instead of being guessed.

**In the log:**

```text
[pipeline] running {"step": "gtm", "research_status": "complete"}
[pipeline] complete {"step": "gtm", "status": "complete", "duration_s": 37.8}
```

**In the web UI:** "Building the GTM strategy" with a timer, then the strategy card. It shows the 9-line snapshot and 4 tabs: **Competitive analysis** (ideas ranked by score, each with a question to validate it), **Sales strategy**, **Market analysis**, and **Themes and gaps**.

**Output:** `runs/<company>-gtm.json`, the strategy pack. In the test runs, packs had 16 to 18 recommendations (IDs `r1`, `r2`, and so on) and 8 of 9 snapshot lines filled. Vision was often missing because many companies do not publish one.

## Step 3: PM agent

**Goal:** turn the strategy into 1 clear proposal that a person can act on.

### 3a. Check the basics

Code, not the AI, checks the strategy pack:
- Research is complete.
- 8 snapshot lines are filled (vision is optional).
- All 3 specialists finished.
- There are at least 2 ranked ideas, 2 sales recommendations, and 1 market recommendation.

### 3b. Human check (only if something is missing)

If a check fails, PM stops and asks a person:

```text
PM status: hitl_required
Baseline: fail (missing: research_complete, snapshot.mission, snapshot.competitive_landscape)
HITL 1: rerun with --decision research (send gaps to Research) or --decision proceed (plan with gaps marked unknown).
```

- **Research more** (`--decision research`): PM returns the exact gaps for the Researcher, such as `company.mission`. For now, you start that Research run yourself.
- **Proceed** (`--decision proceed`): PM plans anyway, treats the gaps as unknown, and marks the result `partial`.

In the web UI, the PM card shows the question with 2 buttons: **Research more** and **Proceed with gaps**. Click 1 and PM runs again with your answer. After **Research more**, start the new Research run in the chat yourself.

### 3c. Plan

An AI planner works through tools, and code checks every call before accepting it:

1. **Use case:** 1 sentence built by code: *"Help {customer} solve {problem} with {MVP}."* It comes with why (1 to 3 sentences with sources), the key assumption that is not yet proven, and up to 2 alternatives it considered.
2. **Action plan:** 3 to 7 steps. Each has a purpose (validate, prepare, or deliver), an owner, a priority, a horizon (now, next, or later), and a success metric. At least 1 step must test the key assumption.
3. **1-pager:** a headline, problem, value proposition, target customer, 3 to 5 key points, proof points with sources, and a call to action.
4. **MVP idea:** the product goal, target user, core job, 3 to 5 must-have features, what is out of scope, success criteria, and a short scenario of a user trying it. Nothing is built.

If the planner breaks a rule (too long, wrong ID, wrong count), code rejects the call and says why, and the planner fixes it. If the planner stops early, a single fallback call completes whatever is missing.

**In the log:**

```text
[baseline] success {"status": "pass", "missing": []}
[plan] success {"tool": "set_use_case"}
[plan] success {"tool": "add_action"}
[plan] success {"tool": "set_one_pager"}
[plan] success {"tool": "set_mvp_idea"}
[plan] done {"status": "complete", "actions": 6, "rejected": 0, "duration_s": 40.5}
```

**In the web UI:** the PM card shows the use case, the action plan as a timeline (validate, prepare, deliver), and **1-pager** and **MVP idea** tabs. Hover any source ID, such as `e12` or `r5`, to see the quote and link, or the recommendation, behind it.

**Output:** `runs/<company>-pm.json` with `use_case`, `action_plan`, `one_pager`, and `mvp_idea`. Web UI runs save to `runs/gtm/<run id>.json` and `runs/pm/<run id>.json` instead.

## The result

On the command line, the end of a run prints a summary:

```text
GTM (complete): runs/baseten-gtm.json
Snapshot: complete
PM (complete): runs/baseten-pm.json
Use case: Help engineering and machine learning teams at AI-native startups putting models into production solve slow, fragile moves of models from prototype to production that break under real traffic with a pre-launch production readiness check for model endpoints.
Actions: 5
Report: runs/baseten-report.md
```

In the web UI, the result stays in the chat, and the chat is saved: **Chats** in the sidebar lists it, and clicking it reopens the whole transcript, even while a run is still going. You can keep talking in it, for example to answer the human check later. **Stored research** lists every run with its evidence, strategy, plan, rounds, and sources. Each card has a download button for its JSON.

`runs/<company>-report.md` puts everything in 1 readable file: the use case, action plan, 1-pager, MVP idea, snapshot, ranked hypotheses, and gaps, with a Sources section that turns every cited ID into its quote and URL. See the [full Baseten report](../examples/baseten.md).

From the Baseten run:
- **1-pager headline:** "Get models from prototype to production without the weeks-long fragile launch"
- **MVP features:** endpoint intake, a launch-style traffic test, a failure report, and a pass/fail summary
- **First action:** interview teams on prototype-to-production blockers

## How a run can end

| Status | Meaning | What to do |
| --- | --- | --- |
| `complete` | Everything ran and passed its checks | Review the plan |
| `partial` | It finished with gaps, or you chose proceed | Review it; the gaps are listed |
| `hitl_required` | PM needs your decision (pipeline exit code 5) | Click a button in the web UI, or rerun with `--decision proceed` or `--decision research` |
| `research_requested` | You chose research more (exit code 4) | Run Research again on the listed gaps |
| `clarify` | The website was unclear | Click the right website in the web UI, or rerun with `--website` |
| `research_failed`, `gtm_failed`, `pm_failed` | A step raised an error | Read the message; earlier results are kept |

## How to check a result

1. **Did it finish?** In the web UI, every step has a green check. On the command line, the last `[pipeline]` line says `complete`, and every step has a `duration_s`.
2. **Is it sourced?** Every ID in `*-pm.json` (such as `r9` or `e8`) exists in `*-gtm.json` or `*-research.json`. Code already enforces this, but spot-check a few: open the quote and URL in the Sources section of `*-report.md`.
3. **Is it honest?** Guesses are labeled `hypothesis`, and the key assumption says what is not yet proven.
4. **Is it useful?**
   - The use case is specific.
   - The use case is not just the company's own product.
   - The plan tests before it builds.
   - The 1-pager is written for the prospect, not for your own team.

Offline tests cover the rules without API calls:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Known limits

- Output changes from run to run. Review each result before you share it.
- **Research more** lists the gaps, but you start the new Research run yourself.
- Success metrics are often not numeric yet.
- Without a database, chats and Research runs live in memory and disappear from the sidebar when the server stops. GTM and PM results are saved as files in `runs/`. The Docker setup keeps them in PostgreSQL.

## 20-second demo

[`docs/demo.gif`](demo.gif) shows a real run on Clerk through the full Docker stack (gateway, Kafka, workers, PostgreSQL, Redis), about 3 minutes sped up to 20 seconds:

| Time | On screen | Caption |
| --- | --- | --- |
| 0 to 2 s | Empty chat. Type "Research for me Clerk" and send. | 1. Ask in plain words |
| 2 to 3.6 s | VentureOS asks which website to research. Click `clerk.com`, not Clerk Hotel Management. | 2. Pick the right website |
| 3.6 to 6.6 s | Sped up: Research rounds, the GTM strategy, then the PM plan. | 3. Research, GTM, and PM agents run live (3 min, sped up) |
| 6.6 to 8 s | The evidence pack card. | Evidence pack: every fact quoted from a real page |
| 8 to 9.3 s | The company snapshot. | Cited company snapshot: mission, ICP, market, competition |
| 9.3 to 10.6 s | The ranked competitive hypotheses. | Competitive gaps, scored and ranked by code |
| 10.6 to 11.8 s | The use case. | 1 clear use case, with the key assumption to test |
| 11.8 to 13.2 s | Hover a source ID to show its quote. | Hover any source ID: the exact quote and its link |
| 13.2 to 14.4 s | The action plan. | Action plan: validate before you build |
| 14.4 to 15.6 s | The 1-pager tab. | A 1-pager you can send to the prospect |
| 15.6 to 17 s | The MVP idea tab. | An MVP idea you could build (described, not built) |
| 17 to 18.4 s | Start a new chat, then click the saved chat in the sidebar. | Every chat is saved in the sidebar |
| 18.4 to 20 s | The reopened chat, with its full transcript. | Reopen it any time and keep going |

To record a new one, use a run you have already reviewed. Speed up the waiting rather than cutting it, so viewers see it is real. Keep the GIF 800 pixels wide or less.
