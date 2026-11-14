"""Small provider adapters for Tavily web search and Gemini JSON output (standard library only)."""

import json
import os
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import JsonObject, SearchResult
from .logs import logged, logger


def _object(value: object, error: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(error)
    return cast(JsonObject, value)


def _post(url: str, payload: JsonObject, headers: dict[str, str], timeout: float, label: str) -> JsonObject:
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return _object(json.loads(response.read()), f"{label} returned invalid JSON.")
    except HTTPError as error:
        raise ValueError(f"{label} returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} request failed: {type(error).__name__}") from error


class TavilySearch:
    def __init__(self, api_key: str | None = None, *, timeout: float = 30) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "")
        self.timeout = timeout

    @logged
    def search(
        self, query: str, limit: int = 5, *, include_domains: list[str] | None = None
    ) -> list[SearchResult]:
        if not self.api_key:
            raise ValueError("Set TAVILY_API_KEY to enable live web search.")
        body = _post(
            "https://api.tavily.com/search",
            {"query": query, "max_results": min(max(limit, 1), 5), "include_raw_content": "text",
             **({"include_domains": include_domains} if include_domains else {})},
            {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            self.timeout, "Web search",
        )
        values = body.get("results")
        if not isinstance(values, list):
            raise ValueError("Web search returned an invalid response.")
        results: list[SearchResult] = []
        for raw in cast(list[object], values):
            if not isinstance(raw, dict):
                continue
            item = cast(JsonObject, raw)
            url, text = item.get("url"), item.get("raw_content") or item.get("content")
            if isinstance(url, str) and isinstance(text, str) and text.strip():
                result: SearchResult = {
                    "url": url, "title": str(item.get("title") or "")[:300], "text": text.strip()[:20000],
                }
                published = item.get("published_date")
                if isinstance(published, str) and published.strip():
                    result["published_at"] = published.strip()
                results.append(result)
        logger.info("tavily results=%d", len(results))
        return results


class GeminiModel:
    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 timeout: float = 90, max_output_tokens: int = 8192) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens

    @logged
    def json(self, system: str, prompt: str) -> JsonObject:
        if not self.api_key:
            raise ValueError("Set GEMINI_API_KEY to enable Gemini.")
        body = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            {"systemInstruction": {"parts": [{"text": system}]},
             "contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": 0, "maxOutputTokens": self.max_output_tokens,
                                  "responseMimeType": "application/json"}},
            {"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            self.timeout, "Language model",
        )
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Language model returned no candidates.")
        candidate = _object(candidates[0], "Language model returned invalid JSON.")
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise ValueError("Language model output was truncated; no result was accepted.")
        content = _object(candidate.get("content"), "Language model returned invalid JSON.")
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise ValueError("Language model returned invalid JSON.")
        text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        try:
            return _object(json.loads(text), "Language model returned invalid JSON.")
        except json.JSONDecodeError as error:
            raise ValueError("Language model returned invalid JSON.") from error
