"""Provider adapters: Tavily web search, and Claude (default) or Gemini for JSON output."""

import json
import os
import time
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import JsonObject, SearchResult
from .logs import logged, logger


def _object(value: object, error: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(error)
    return cast(JsonObject, value)


RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (3.0, 10.0, 25.0)  # seconds between attempts for rate limits and server errors


def _post(url: str, payload: JsonObject, headers: dict[str, str], timeout: float, label: str) -> JsonObject:
    data = json.dumps(payload).encode()
    for attempt in range(len(RETRY_DELAYS) + 1):
        request = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return _object(json.loads(response.read()), f"{label} returned invalid JSON.")
        except HTTPError as error:
            if error.code in RETRY_STATUS and attempt < len(RETRY_DELAYS):
                logger.info("%s HTTP %d, retrying", label, error.code)
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise ValueError(f"{label} returned HTTP {error.code}.") from error
        except (URLError, TimeoutError) as error:
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise ValueError(f"{label} request failed: {type(error).__name__}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"{label} returned invalid JSON.") from error
    raise ValueError(f"{label} request failed.")


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


DEFAULT_MODEL = "claude-haiku-5-5"  # Anthropic's lowest-cost current model


class AnthropicModel:
    """Claude through the official Anthropic SDK. Returns 1 JSON object per call."""

    def __init__(self, *, model: str | None = None, max_tokens: int = 16000,
                 max_retries: int = 5, timeout: float = 120) -> None:
        try:
            import anthropic
        except ImportError as error:
            raise ValueError("anthropic is not installed. Run: pip install -e '.[research]'") from error
        self._anthropic = anthropic
        self.model = model or os.getenv("RESEARCH_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        # The SDK retries 429, 5xx, and connection errors with backoff and honors retry-after.
        self.client = anthropic.Anthropic(max_retries=max_retries, timeout=timeout)

    def chat_model(self) -> object:
        """LangChain chat model for the DeepAgents loop (same model, same API key)."""
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as error:
            raise ValueError("langchain-anthropic is not installed. "
                             "Run: pip install -e '.[research]'") from error
        return ChatAnthropic(model=self.model, max_tokens=8000, max_retries=6, timeout=120)

    @logged
    def json(self, system: str, prompt: str) -> JsonObject:
        anthropic = self._anthropic
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system + " Reply with the JSON object only: no prose and no code fences.",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as error:
            raise ValueError("Set ANTHROPIC_API_KEY to a valid key.") from error
        except anthropic.RateLimitError as error:
            raise ValueError("Language model rate limit reached after retries.") from error
        except anthropic.APIStatusError as error:
            raise ValueError(f"Language model returned HTTP {error.status_code}.") from error
        except anthropic.APIConnectionError as error:
            raise ValueError("Language model request failed: connection error.") from error
        if response.stop_reason == "max_tokens":
            raise ValueError("Language model output was truncated; no result was accepted.")
        if response.stop_reason == "refusal":
            raise ValueError("Language model declined the request.")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        start, end = text.find("{"), text.rfind("}")
        try:
            decoded = json.loads(text[start:end + 1]) if start >= 0 else None
        except json.JSONDecodeError as error:
            raise ValueError("Language model returned invalid JSON.") from error
        logger.info("claude model=%s in=%d out=%d", self.model, response.usage.input_tokens,
                    response.usage.output_tokens)
        return _object(decoded, "Language model returned invalid JSON.")


def default_model() -> "AnthropicModel | GeminiModel":
    """Pick the model from RESEARCH_MODEL: a claude-* ID uses Anthropic, a gemini-* ID uses Gemini."""
    name = os.getenv("RESEARCH_MODEL", DEFAULT_MODEL)
    return GeminiModel(model=name) if name.startswith("gemini") else AnthropicModel(model=name)
