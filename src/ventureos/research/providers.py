"""Small provider adapters for web search and Gemini."""

import json
import os
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import JsonObject, SearchResult
from .logs import logged, logged_debug, logger


@logged_debug
def _object(value: object, error: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(error)
    entries = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in entries):
        raise ValueError(error)
    return cast(JsonObject, entries)


class TavilySearch:
    @logged_debug
    def __init__(self, api_key: str | None = None, *, timeout: float = 30) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "")
        self.timeout = timeout

    @logged
    def search(
        self, query: str, limit: int = 5, *, include_domains: list[str] | None = None
    ) -> list[SearchResult]:
        if not self.api_key:
            raise ValueError("Set TAVILY_API_KEY to enable live web search.")
        payload = json.dumps({
            "api_key": self.api_key,
            "query": query,
            "max_results": min(max(limit, 1), 5),
            "include_raw_content": "text",
            **({"include_domains": include_domains} if include_domains else {}),
        }).encode()
        request = Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = _object(json.loads(response.read()), "Web search returned invalid JSON.")
        except HTTPError as error:
            raise ValueError(f"Web search returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(f"Web search failed: {error}") from error
        values = body.get("results")
        if not isinstance(values, list):
            raise ValueError("Web search returned an invalid response.")

        results: list[SearchResult] = []
        for raw_item in cast(list[object], values):
            if not isinstance(raw_item, dict):
                continue
            item = _object(cast(dict[object, object], raw_item), "Web search returned an invalid result.")
            url = item.get("url")
            text = item.get("raw_content") or item.get("content")
            if isinstance(url, str) and isinstance(text, str) and text.strip():
                result: SearchResult = {
                    "url": url,
                    "title": str(item.get("title") or "")[:300],
                    "text": text.strip()[:20000],
                }
                published = item.get("published_date")
                if isinstance(published, str) and published.strip():
                    result["published_at"] = published.strip()
                results.append(result)
        logger.info("tavily results=%d", len(results))
        return results


class GeminiModel:
    @logged_debug
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 90,
    ) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.timeout = timeout

    @logged_debug
    def chat_model(self) -> object:
        """LangChain chat model for the DeepAgents loop (needs langchain-google-genai)."""
        if not self.api_key:
            raise ValueError("Set GEMINI_API_KEY to enable Gemini.")
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as error:
            raise ValueError(
                "langchain-google-genai is not installed. Run: pip install -e '.[agent]'"
            ) from error
        return ChatGoogleGenerativeAI(
            model=self.model, google_api_key=self.api_key, temperature=0, max_output_tokens=8192
        )

    @logged
    def json(self, system: str, prompt: str) -> JsonObject:
        if not self.api_key:
            raise ValueError("Set GEMINI_API_KEY to enable Gemini.")
        if not self.model.strip():
            raise ValueError("Set GEMINI_MODEL to a JSON-capable Gemini model.")
        payload = json.dumps({
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }).encode()
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = _object(json.loads(response.read()), "Language model returned invalid JSON.")
        except HTTPError as error:
            raise ValueError(f"Language model returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(f"Language model request failed: {error}") from error
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Language model returned invalid JSON.")
        candidate = _object(cast(list[object], candidates)[0], "Language model returned invalid JSON.")
        if candidate.get("finishReason") == "MAX_TOKENS":
            # A truncated JSON body must never be reported as a successful run.
            raise ValueError("Language model output was truncated; no result was accepted.")
        content = _object(candidate.get("content"), "Language model returned invalid JSON.")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("Language model returned invalid JSON.")
        text_parts: list[str] = []
        for raw_part in cast(list[object], parts):
            part = _object(raw_part, "Language model returned invalid JSON.")
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        if not text_parts:
            raise ValueError("Language model returned invalid JSON.")
        try:
            decoded = json.loads("".join(text_parts))
        except json.JSONDecodeError as error:
            raise ValueError("Language model returned invalid JSON.") from error
        logger.info(
            "gemini model=%s response_chars=%d finish=%s",
            self.model, sum(len(part) for part in text_parts), candidate.get("finishReason"),
        )
        return _object(decoded, "Language model returned invalid JSON.")
