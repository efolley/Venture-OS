"""Streamlit visualization client for the local FastAPI Web Intelligence API."""

import json
import os
import re
import time
from typing import cast
from urllib.parse import quote, urlsplit

import requests
import streamlit as st

from web_intelligence.contracts import HistoryTurn, JsonObject


API_URL = os.getenv("WEB_INTEL_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="VentureOS Web Intelligence", page_icon="🔎")
st.title("VentureOS | Web Intelligence")
st.caption("Research a company, inspect each backend step, and ask grounded follow-ups.")


def _object(value: object, message: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(message)
    entries = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in entries):
        raise ValueError(message)
    return cast(JsonObject, entries)


def _object_list(value: object, message: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise ValueError(message)
    return [_object(item, message) for item in cast(list[object], value)]


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        return None
    return cast(list[str], items)


def _markdown_text(value: str) -> str:
    normalized = " ".join(value.split())
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", normalized)


def _markdown_value(value: object) -> str:
    return _markdown_text(value) if isinstance(value, str) else ""


def _markdown_link(label: str, url: str) -> str:
    return f"[{_markdown_text(label)}]({quote(url, safe=':/?&=#%+@')})"


def _report_markdown(report_value: object) -> str:
    report = _object(report_value, "Backend returned an invalid report.")
    company = _object(report.get("company"), "Backend returned an invalid company section.")
    problem = _object(report.get("problem"), "Backend returned an invalid problem section.")
    market = _object(report.get("market"), "Backend returned an invalid market section.")
    icp = _object(report.get("icp"), "Backend returned an invalid ICP section.")
    solution = _object(report.get("solution"), "Backend returned an invalid solution section.")
    positioning = _object(
        report.get("positioning"),
        "Backend returned an invalid positioning section.",
    )

    name = company.get("name")
    website = company.get("website")
    description = company.get("description")
    name_text = name if isinstance(name, str) else "Company"
    if isinstance(website, str) and _is_https_link(website):
        company_name = _markdown_link(name_text, website)
    else:
        company_name = _markdown_text(name_text)

    value_proposition = positioning.get("statement")
    if not isinstance(value_proposition, str) or not value_proposition.strip():
        who = positioning.get("who")
        what = positioning.get("what")
        how = positioning.get("how")
        value_proposition = " ".join(
            item.strip() for item in (who, what, how)
            if isinstance(item, str) and item.strip()
        )

    pain_points = _string_list(problem.get("pain_points")) or []
    users = _string_list(icp.get("users")) or []
    sources = _string_list(report.get("sources")) or []

    sections = [
        f"**Company:** {company_name} - {_markdown_value(description)}",
        f"**Value proposition:** {_markdown_value(value_proposition)}",
        "\n".join([
            f"**Problem:** {_markdown_value(problem.get('statement'))}",
            *[f"- {_markdown_text(point)}" for point in pain_points],
        ]),
        f"**Market:** {_markdown_value(market.get('industry'))} | {_markdown_value(market.get('category'))}",
        f"**Business model:** {_markdown_value(market.get('business_model'))}",
        f"**Target client:** {_markdown_value(icp.get('primary'))}",
        f"**Target ICP buyer:** {_markdown_value(icp.get('buyer'))}",
        f"**End users:** {', '.join(_markdown_text(user) for user in users)}",
        f"**Solution:** {_markdown_value(solution.get('product'))} - {_markdown_value(solution.get('approach'))}",
        "\n".join(["**Sources:**", *[f"- {_markdown_link(source, source)}" for source in sources]]),
    ]
    return "\n\n".join(sections)


def _is_https_link(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def _render_answer(answer: JsonObject) -> None:
    report = answer.get("report")
    if isinstance(report, dict):
        st.markdown(_report_markdown(cast(object, report)))
        return
    st.write(answer.get("message", ""))
    citations = _string_list(answer.get("citations"))
    if citations is not None:
        st.caption("Sources: " + ", ".join(citations))


def api(method: str, path: str, json_data: JsonObject | None = None) -> JsonObject:
    response = requests.request(
        method,
        f"{API_URL}{path}",
        data=json.dumps(json_data) if json_data is not None else None,
        headers={"Content-Type": "application/json"} if json_data is not None else None,
        timeout=15,
    )
    if not response.ok:
        detail = response.text
        try:
            body = response.json()
        except requests.JSONDecodeError:
            body = None
        if isinstance(body, dict):
            payload = cast(dict[object, object], body)
            detail_value = payload.get("detail")
            if isinstance(detail_value, str):
                detail = detail_value
        raise ValueError(f"Backend error ({response.status_code}): {detail}")
    return _object(response.json(), "Backend returned an invalid response.")


if "session_id" not in st.session_state:
    try:
        session_id_value = api("POST", "/api/sessions").get("session_id")
        if not isinstance(session_id_value, str):
            raise ValueError("Backend did not return a session ID.")
        st.session_state["session_id"] = session_id_value
    except (requests.RequestException, ValueError) as error:
        st.error(f"Cannot connect to FastAPI at {API_URL}: {error}")
        st.stop()

session_id = cast(str, st.session_state["session_id"])
try:
    conversation = api("GET", f"/api/sessions/{session_id}")
    history_data = conversation.get("history", [])
    if not isinstance(history_data, list):
        raise ValueError("Backend returned invalid conversation history.")
    history = cast(list[HistoryTurn], history_data)
except (requests.RequestException, ValueError) as error:
    st.error(f"Could not load the conversation: {error}")
    st.stop()

for turn in history:
    with st.chat_message("user"):
        st.write(turn["user"])
    answer = turn["assistant"]
    with st.chat_message("assistant"):
        _render_answer(answer)

message = st.chat_input("Company name, HTTPS website, or follow-up question")
if message:
    try:
        job = api(
            "POST",
            f"/api/sessions/{session_id}/messages",
            {"message": message},
        )
        job_id = job.get("job_id")
        if not isinstance(job_id, str):
            raise ValueError("Backend did not return a research job ID.")
        cursor = 0
        events: list[JsonObject] = []
        latest_status = st.empty()
        answer: JsonObject | None = None
        job_error: str | None = None
        with st.status("Processing request", expanded=True) as status:
            while True:
                snapshot = api("GET", f"/api/jobs/{job_id}?after={cursor}")
                new_events = _object_list(snapshot.get("events"), "Backend returned invalid progress data.")
                events.extend(new_events)
                next_cursor = snapshot.get("next_cursor")
                if not isinstance(next_cursor, int):
                    raise ValueError("Backend returned an invalid progress cursor.")
                cursor = next_cursor
                if new_events:
                    current = new_events[-1]
                    latest_status.write(
                        f"{current.get('module')}: {current.get('status')}"
                    )
                job_status = snapshot.get("status")
                if not isinstance(job_status, str):
                    raise ValueError("Backend returned an invalid job status.")
                if job_status != "running":
                    break
                time.sleep(0.35)
            if job_status == "succeeded":
                status.update(label="Request complete", state="complete")
                answer = _object(snapshot.get("result"), "Backend returned no research result.")
            else:
                status.update(label="Request failed", state="error")
                error = snapshot.get("error")
                job_error = error if isinstance(error, str) else "Research failed."
        if answer is not None:
            st.success("Request complete")
            with st.chat_message("user"):
                st.write(message)
            with st.chat_message("assistant"):
                _render_answer(answer)
        elif job_error is not None:
            st.error(job_error)
        with st.expander("Backend steps, inputs, outputs, and results"):
            for event in events:
                st.markdown(f"**{event.get('module')}** · {event.get('status')}")
                st.json({
                    "input": event.get("input"),
                    "output": event.get("output"),
                    "result": event.get("status"),
                })
    except (requests.RequestException, ValueError) as error:
        st.error(str(error))
