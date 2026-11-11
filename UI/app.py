"""Simple Streamlit page: enter a company or ask a question, search the web, read the cited result."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st
from dotenv import load_dotenv

from ventureos.research import ResearchEngine
from ventureos.research.logs import log_progress, logged, logger, setup_logging
from ventureos.research.providers import GeminiModel, TavilySearch
from ventureos.research.render import brief_markdown

load_dotenv(ROOT / ".env")
os.environ.setdefault("VENTUREOS_LOG_DIR", str(ROOT / "logs"))
setup_logging()

st.set_page_config(page_title="VentureOS Research", page_icon="🔎")
st.title("VentureOS | Research")
st.caption("Enter a company name or website. Then ask follow-up questions about it.")

missing = [key for key in ("TAVILY_API_KEY", "GEMINI_API_KEY") if not os.getenv(key)]
if missing:
    st.error(f"Add {' and '.join(missing)} to the .env file in the project root, then restart.")
    st.stop()

if "engine" not in st.session_state:
    st.session_state.engine = ResearchEngine(GeminiModel(), TavilySearch())
    st.session_state.state = {"history": []}
    st.session_state.turns = []


@logged
def show(result: dict) -> None:
    brief = result.get("brief")
    if isinstance(brief, dict):
        st.markdown(brief_markdown(brief))
        return
    st.write(result.get("message", ""))
    citations = result.get("citations")
    if citations:
        st.caption("Sources: " + ", ".join(citations))


for user_message, result in st.session_state.turns:
    with st.chat_message("user"):
        st.write(user_message)
    with st.chat_message("assistant"):
        show(result)

message = st.chat_input("Company name, website, or question")
if message:
    logger.info("ui message chars=%d", len(message))
    with st.chat_message("user"):
        st.write(message)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the web and reading sources..."):
                result = st.session_state.engine.turn(
                    message, st.session_state.state, log_progress
                )
        except Exception as error:
            logger.error("ui request failed %s: %s", type(error).__name__, error)
            st.error(f"{type(error).__name__}: {error}")
        else:
            show(result)
            st.session_state.turns.append((message, result))
            st.session_state.state["history"].append(
                {"user": message,
                 "assistant": {"kind": result.get("kind"), "message": result.get("message", "")}}
            )
