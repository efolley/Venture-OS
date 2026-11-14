"""Streamlit UI for the Research agent. It only sends input to the FastAPI backend and shows output.

Run the backend first (python -m research.api), then: streamlit run UI/app.py
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
from render import evidence_rows, pack_markdown  # noqa: E402

API = os.getenv("RESEARCH_API_URL", "http://127.0.0.1:8000").rstrip("/")
POLL_SECONDS = 1.0
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
                           "PYTHONPATH=src python -m research.api") from error


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


def show_reply(message: dict, key: str) -> None:
    st.markdown(message.get("message", "").replace("\n", "  \n"))
    if message.get("pack"):
        show_pack(message["pack"], key)


# ----- chat tab -------------------------------------------------------------------------

def chat_tab() -> None:
    st.title("Research chat")
    st.caption("Send a company name or website. The agent asks follow-up questions when it needs to.")
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
    pack_tab, rounds_tab, sources_tab = st.tabs(["Evidence pack", "Rounds", "Sources"])
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


# ----- layout ---------------------------------------------------------------------------

st.set_page_config(page_title="Research agent", page_icon="🔎", layout="wide")
with st.sidebar:
    st.header("🔎 Research agent")
    page = st.radio("View", ["Chat", "Data management"], label_visibility="collapsed")
    st.divider()
if page == "Chat":
    chat_tab()
else:
    data_tab()
