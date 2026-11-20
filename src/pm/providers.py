"""Claude through the Anthropic SDK: JSON calls and a LangChain chat model for DeepAgents.

The PM agent's own copy, so it never imports another agent's package.
"""

import json
import os
from typing import cast

from .contracts import JsonObject

DEFAULT_MODEL = "claude-haiku-5-5"


class AnthropicModel:
    def __init__(self, *, model: str | None = None, max_tokens: int = 16000,
                 max_retries: int = 5, timeout: float = 120) -> None:
        try:
            import anthropic
        except ImportError as error:
            raise ValueError("anthropic is not installed. Run: pip install -e '.[research]'") from error
        self._anthropic = anthropic
        self.model = model or os.getenv("PM_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic(max_retries=max_retries, timeout=timeout)

    def chat_model(self) -> object:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as error:
            raise ValueError("langchain-anthropic is not installed. "
                             "Run: pip install -e '.[research]'") from error
        return ChatAnthropic(model=self.model, max_tokens=8000, max_retries=6, timeout=120)

    def json(self, system: str, prompt: str) -> JsonObject:
        anthropic = self._anthropic
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                system=system + " Reply with the JSON object only: no prose and no code fences.",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as error:
            raise ValueError("Set ANTHROPIC_API_KEY to a valid key.") from error
        except anthropic.APIStatusError as error:
            raise ValueError(f"Language model returned HTTP {error.status_code}.") from error
        except anthropic.APIConnectionError as error:
            raise ValueError("Language model request failed: connection error.") from error
        if response.stop_reason == "max_tokens":
            raise ValueError("Language model output was truncated; no result was accepted.")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        start, end = text.find("{"), text.rfind("}")
        try:
            decoded = json.loads(text[start:end + 1]) if start >= 0 else None
        except json.JSONDecodeError as error:
            raise ValueError("Language model returned invalid JSON.") from error
        if not isinstance(decoded, dict):
            raise ValueError("Language model returned invalid JSON.")
        return cast(JsonObject, decoded)
