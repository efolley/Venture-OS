"""Streamlit UI for VentureOS: Research, then the GTM orchestrator. It only sends input to the
FastAPI backend and shows output.

Run the backend first (PYTHONPATH=src python -m pipeline.api), then: streamlit run UI/app.py
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import (  # noqa: E402
    competitive_markdown, evidence_rows, gaps_markdown, pack_markdown, pm_markdown,
    one_pager_markdown, mvp_idea_markdown, recommendations_markdown,
    snapshot_markdown, themes_markdown,
)

API = os.getenv("RESEARCH_API_URL", "http://127.0.0.1:8000").rstrip("/")
POLL_SECONDS = 1.0
GTM_POLL_SECONDS = 2.0
STEP_LABELS = {
    "understand": "Understanding the request", "plan": "Planning the next search",
    "collect": "Collecting pages", "coverage": "Checking coverage", "done": "Done",
    "failed": "Failed",
}


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(f"{API}{path}", data=data, method=method,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as error:
        detail = json.loads(error.read() or b"{}").get("detail", f"HTTP {error.code}")
        raise RuntimeError(str(detail)) from error
    except URLError as error:
        raise RuntimeError(f"Cannot reach the backend at {API}. Start it with: "
                           "PYTHONPATH=src python -m pipeline.api") from error


def event_line(event: dict) -> str:
    data = event.get("data", {})
    label = STEP_LABELS.get(event["step"], event["step"])
    if event["step"] == "plan":
        return f"Round {data.get('round')}: searching for {data.get('gap')}"
    if event["step"] == "collect":
        return f"Round {data.get('round')}: kept {data.get('kept')} pages, skipped {data.get('skipped')}"
    if event["step"] == "coverage":
        return f"Round {data.get('round')}: {data.get('items')} new evidence items"
    return f"{label}: {event['status']}"


def show_pack(pack: dict, key: str) -> None:
    st.markdown(pack_markdown(pack))
    with st.expander(f"Evidence ({len(pack.get('evidence', []))} items)"):
        st.dataframe(evidence_rows(pack), hide_index=True, use_container_width=True)
    st.download_button("Download JSON", json.dumps(pack, indent=2, ensure_ascii=False),
                       file_name=f"evidence-pack-{pack['run_id']}.json",
                       mime="application/json", key=f"download-{key}")


def show_strategy(strategy: dict, key: str) -> None:
    st.markdown(snapshot_markdown(strategy))
    competitive, sales, market, themes = st.tabs(
        ["Competitive analysis", "Sales strategy", "Market analysis", "Themes and gaps"])
    with competitive:
        st.markdown(competitive_markdown(strategy))
    with sales:
        st.markdown(recommendations_markdown(strategy, "challenger_salesman"))
    with market:
        st.markdown(recommendations_markdown(strategy, "market_analysis"))
    with themes:
        st.markdown("**Themes** (ideas the sub-agents agree on)")
        st.markdown(themes_markdown(strategy))
        st.markdown("**Gaps** (missing evidence)")
        st.markdown(gaps_markdown(strategy))
    st.download_button("Download strategy JSON", json.dumps(strategy, indent=2, ensure_ascii=False),
                       file_name=f"gtm-strategy-{strategy['input_run_id']}.json",
                       mime="application/json", key=f"download-gtm-{key}")


def run_gtm(research_run_id: str, instructions: str) -> dict:
    """Start GTM on a stored evidence pack and wait for the strategy pack."""
    try:
        job_id = call("POST", "/api/gtm/runs",
                      {"research_run_id": research_run_id, "instructions": instructions})["job_id"]
    except RuntimeError as error:
        return {"kind": "error", "message": f"⚠️ GTM did not start: {error}"}
    with st.status("Building the GTM strategy (3 sub-agents, merge, snapshot)...",
                   expanded=False) as status:
        while True:
            try:
                job = call("GET", f"/api/gtm/jobs/{job_id}")
            except RuntimeError as error:
                status.update(label="Lost contact with the backend", state="error")
                return {"kind": "error", "message": f"⚠️ {error}"}
            if job["status"] != "running":
                break
            time.sleep(GTM_POLL_SECONDS)
        if job["status"] != "done" or not job["strategy"]:
            status.update(label="GTM failed", state="error")
            return {"kind": "error", "message": f"⚠️ GTM failed: {job['error'] or 'no result'}"}
        status.update(label="GTM strategy ready", state="complete")
    strategy = job["strategy"]
    return {"kind": "strategy", "message": "Here is the GTM strategy and company snapshot.",
            "strategy": strategy}


def choose_hitl(run_id: str, decision: str) -> None:
    """Button callback: runs before the page re-runs, so the choice is never lost."""
    st.session_state.pending_pm = (run_id, decision)


def show_pm(result: dict, key: str) -> None:
    st.markdown(pm_markdown(result))
    if result["status"] == "hitl_required":
        st.caption("HITL 1: choose how to continue.")
        research_col, proceed_col = st.columns(2)
        run_id = result["input_run_id"]
        research_col.button("Research more", key=f"hitl-research-{key}",
                            on_click=choose_hitl, args=(run_id, "research"))
        proceed_col.button("Proceed with gaps", key=f"hitl-proceed-{key}",
                           on_click=choose_hitl, args=(run_id, "proceed"))
        return
    if result.get("one_pager") or result.get("mvp_idea"):
        presentation, product = st.tabs(["1-pager", "MVP idea"])
        with presentation:
            st.markdown(one_pager_markdown(result.get("one_pager")))
        with product:
            st.markdown(mvp_idea_markdown(result.get("mvp_idea")))
    st.download_button("Download PM JSON", json.dumps(result, indent=2, ensure_ascii=False),
                       file_name=f"pm-plan-{result['input_run_id']}.json",
                       mime="application/json", key=f"download-pm-{key}")


def run_pm(research_run_id: str, instructions: str, decision: str | None = None) -> dict:
    """Run PM on the saved GTM strategy and wait for the PM result."""
    body = {"research_run_id": research_run_id, "instructions": instructions}
    if decision:
        body["decision"] = decision
    try:
        job_id = call("POST", "/api/pm/runs", body)["job_id"]
    except RuntimeError as error:
        return {"kind": "error", "message": f"⚠️ PM did not start: {error}"}
    with st.status("PM: checking the baseline and establishing the use case...",
                   expanded=False) as status:
        while True:
            try:
                job = call("GET", f"/api/pm/jobs/{job_id}")
            except RuntimeError as error:
                status.update(label="Lost contact with the backend", state="error")
                return {"kind": "error", "message": f"⚠️ {error}"}
            if job["status"] != "running":
                break
            time.sleep(GTM_POLL_SECONDS)
        if job["status"] != "done" or not job["result"]:
            status.update(label="PM failed", state="error")
            return {"kind": "error", "message": f"⚠️ PM failed: {job['error'] or 'no result'}"}
        result = job["result"]
        label = {"hitl_required": "PM needs your decision (HITL 1)",
                 "research_requested": "PM sent the gaps back to Research"}.get(
            result["status"], "PM plan ready")
        status.update(label=label, state="complete")
    message = {"hitl_required": "The strategy pack misses required information. Choose below.",
               "research_requested": "Gaps sent back to Research. Run a re-run in the chat to "
                                     "fill them."}.get(result["status"],
                                                       "Here is the use case and action plan.")
    return {"kind": "pm", "message": message, "pm": result}


def show_reply(message: dict, key: str) -> None:
    st.markdown(message.get("message", "").replace("\n", "  \n"))
    if message.get("pack"):
        show_pack(message["pack"], key)
    if message.get("strategy"):
        show_strategy(message["strategy"], key)
    if message.get("pm"):
        show_pm(message["pm"], key)


# ----- chat tab -------------------------------------------------------------------------

def chat_tab() -> None:
    st.title("Research, GTM, and PM chat")
    st.caption("Send a company name or website. Research collects the evidence, the GTM "
               "orchestrator builds the snapshot and strategy, and PM establishes the use case "
               "and action plan.")
    if "session_id" not in st.session_state:
        try:
            st.session_state.session_id = call("POST", "/api/sessions")["session_id"]
        except RuntimeError as error:
            st.error(str(error))
            return
        st.session_state.messages = []
    with st.sidebar:
        instructions = st.text_input("Instructions (optional)", placeholder="for example: EU only",
                                     max_chars=300)
        if st.button("New chat"):
            st.session_state.pop("session_id", None)
            st.rerun()
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            show_reply(message, f"history-{index}")
    pending = st.session_state.pop("pending_pm", None)
    if pending:
        # A HITL 1 button was clicked: rerun PM with the chosen decision.
        run_id, decision = pending
        st.session_state.messages.append({"role": "user", "message": f"HITL 1 decision: {decision}"})
        with st.chat_message("user"):
            st.markdown(f"HITL 1 decision: **{decision}**")
        with st.chat_message("assistant"):
            answer = run_pm(run_id, instructions, decision)
            show_reply(answer, f"history-{len(st.session_state.messages)}")
        st.session_state.messages.append({"role": "assistant", **answer})
    prompt = st.chat_input("Company name or website")
    if not prompt:
        return
    st.session_state.messages.append({"role": "user", "message": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        answer = run_message(prompt, instructions)
        show_reply(answer, f"history-{len(st.session_state.messages)}")
    st.session_state.messages.append({"role": "assistant", **answer})
    if answer.get("pack"):
        # Research finished with an evidence pack: hand it to GTM automatically.
        with st.chat_message("assistant"):
            strategy = run_gtm(answer["pack"]["run_id"], instructions)
            show_reply(strategy, f"history-{len(st.session_state.messages)}")
        st.session_state.messages.append({"role": "assistant", **strategy})
        if strategy.get("strategy"):
            # GTM finished: hand the strategy pack to PM automatically.
            with st.chat_message("assistant"):
                plan = run_pm(answer["pack"]["run_id"], instructions)
                show_reply(plan, f"history-{len(st.session_state.messages)}")
            st.session_state.messages.append({"role": "assistant", **plan})


def run_message(prompt: str, instructions: str) -> dict:
    try:
        job_id = call("POST", f"/api/sessions/{st.session_state.session_id}/messages",
                      {"message": prompt, "instructions": instructions})["job_id"]
    except RuntimeError as error:
        return {"kind": "error", "message": f"⚠️ {error}"}
    after = 0
    with st.status("Researching...", expanded=True) as status:
        while True:
            try:
                job = call("GET", f"/api/jobs/{job_id}?after={after}")
            except RuntimeError as error:
                status.update(label="Lost contact with the backend", state="error")
                return {"kind": "error", "message": f"⚠️ {error}"}
            for event in job["events"]:
                st.write(event_line(event))
            after = job["next"]
            if job["status"] != "running":
                break
            time.sleep(POLL_SECONDS)
        reply = job["reply"] or {"kind": "error", "message": "No reply."}
        state = "error" if job["status"] == "failed" else "complete"
        status.update(label="Finished" if state == "complete" else "Failed", state=state,
                      expanded=False)
    if reply["kind"] == "error":
        reply = {**reply, "message": f"⚠️ {reply['message']}"}
    return reply


# ----- data management tab --------------------------------------------------------------

def data_tab() -> None:
    st.title("Stored research")
    try:
        runs = call("GET", "/api/runs?limit=200")["runs"]
        store = call("GET", "/api/health")["store"]
    except RuntimeError as error:
        st.error(str(error))
        return
    st.caption(f"{len(runs)} runs in {store}.")
    if not runs:
        st.info("No runs yet. Start one in the Chat tab.")
        return
    statuses = sorted({run["status"] for run in runs})
    chosen = st.multiselect("Status", statuses, default=statuses)
    visible = [run for run in runs if run["status"] in chosen]
    st.dataframe([{
        "company": run["company"], "website": run["website"], "status": run["status"],
        "rounds": run["usage"].get("rounds", 0), "sources": run["usage"].get("sources", 0),
        "model calls": run["usage"].get("model_calls", 0), "created": run["created_at"][:19],
        "re-run of": (run["parent_run_id"] or "")[:8], "run id": run["id"],
    } for run in visible], hide_index=True, use_container_width=True)
    labels = {f"{run['company'] or run['website']} · {run['status']} · {run['created_at'][:16]}": run["id"]
              for run in visible}
    if not labels:
        return
    run_id = labels[st.selectbox("Open a run", list(labels))]
    try:
        detail = call("GET", f"/api/runs/{run_id}")
        trail = call("GET", f"/api/runs/{run_id}/rounds")
    except RuntimeError as error:
        st.error(str(error))
        return
    pack_tab, gtm_tab, pm_tab, rounds_tab, sources_tab = st.tabs(
        ["Evidence pack", "GTM strategy", "PM plan", "Rounds", "Sources"])
    with pack_tab:
        if detail["pack"]:
            show_pack(detail["pack"], f"data-{run_id}")
        else:
            run = detail["run"]
            st.info(f"No pack stored. Run status: {run['status']}.")
            if run.get("candidates"):
                st.write("Candidates:", run["candidates"])
            if run.get("error"):
                st.error(run["error"])
    with gtm_tab:
        gtm_section(run_id, has_pack=bool(detail["pack"]))
    with pm_tab:
        pm_section(run_id)
    with rounds_tab:
        for entry in trail["rounds"]:
            title = "Round 0: understand" if entry["number"] == 0 else (
                f"Round {entry['number']}: {entry['gap']}")
            with st.expander(title):
                st.write({"query": entry["query"], "site": entry["site"],
                          "model calls": entry["model_calls"], "error": entry["error"]})
                if entry.get("dropped"):
                    st.write("Dropped or adjusted:", entry["dropped"])
                if entry.get("coverage"):
                    st.write("Coverage after this round:", entry["coverage"])
    with sources_tab:
        st.dataframe(trail["sources"], hide_index=True, use_container_width=True)


def gtm_section(run_id: str, *, has_pack: bool) -> None:
    try:
        result = call("GET", f"/api/gtm/runs/{run_id}")
    except RuntimeError as error:
        st.error(str(error))
        return
    if result["strategy"]:
        show_strategy(result["strategy"], f"data-{run_id}")
        label = "Run GTM again"
    elif result["running_job_id"]:
        st.info("A GTM run is in progress for this research run. Refresh in a minute.")
        return
    elif not has_pack:
        st.info("This run has no evidence pack, so there is nothing for GTM to analyze.")
        return
    else:
        st.info("No GTM strategy for this run yet.")
        label = "Run GTM strategy"
    if st.button(label, key=f"run-gtm-{run_id}"):
        answer = run_gtm(run_id, "")
        if answer.get("kind") == "error":
            st.error(answer["message"])
        else:
            st.rerun()


def pm_section(run_id: str) -> None:
    try:
        result = call("GET", f"/api/pm/runs/{run_id}")
        has_strategy = bool(call("GET", f"/api/gtm/runs/{run_id}")["strategy"])
    except RuntimeError as error:
        st.error(str(error))
        return
    if result["running_job_id"]:
        st.info("A PM run is in progress for this research run. Refresh in a minute.")
        return
    if result["result"]:
        show_pm(result["result"], f"data-{run_id}")
    elif not has_strategy:
        st.info("Run GTM first; PM plans from the GTM strategy.")
        return
    else:
        st.info("No PM plan for this run yet.")
    pending = st.session_state.pop("pending_pm", None)
    if pending and pending[0] == run_id:
        answer = run_pm(run_id, "", pending[1])
        if answer.get("kind") == "error":
            st.error(answer["message"])
        else:
            st.rerun()
    if st.button("Run PM again" if result["result"] else "Run PM", key=f"run-pm-{run_id}"):
        answer = run_pm(run_id, "")
        if answer.get("kind") == "error":
            st.error(answer["message"])
        else:
            st.rerun()


# ----- layout ---------------------------------------------------------------------------

st.set_page_config(page_title="VentureOS", page_icon="🔎", layout="wide")
with st.sidebar:
    st.header("🔎 VentureOS")
    st.caption("Research → GTM orchestrator → PM")
    page = st.radio("View", ["Chat", "Data management"], label_visibility="collapsed")
    st.divider()
if page == "Chat":
    chat_tab()
else:
    data_tab()
