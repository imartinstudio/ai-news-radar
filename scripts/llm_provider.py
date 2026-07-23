from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import requests


def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None and str(value).strip() else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None and str(value).strip() else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout: float = 35.0
    max_calls: int = 20

    @classmethod
    def from_env(cls) -> "LLMSettings":
        key = (os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        base = (
            os.environ.get("LLM_BASE_URL")
            or os.environ.get("DEEPSEEK_API_BASE_URL")
            or "https://api.deepseek.com"
        ).strip().rstrip("/")
        model = (os.environ.get("LLM_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
        provider = (os.environ.get("LLM_PROVIDER") or "deepseek").strip().lower()
        timeout = _positive_float(os.environ.get("LLM_TIMEOUT_SECONDS"), 35.0)
        max_calls = _bounded_int(os.environ.get("LLM_MAX_CALLS_PER_RUN"), 20, 0, 40)
        return cls(provider, key, base, model, timeout, max_calls)


@dataclass
class CallBudget:
    limit: int
    used: int = 0

    def consume(self) -> bool:
        if self.used >= max(0, self.limit):
            return False
        self.used += 1
        return True


def _decode_json_content(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else None


class OpenAICompatibleProvider:
    def __init__(self, settings: LLMSettings, budget: CallBudget | None = None):
        self.settings = settings
        self.budget = budget or CallBudget(settings.max_calls)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.api_key and self.settings.max_calls > 0)

    @property
    def calls_used(self) -> int:
        return self.budget.used

    def complete_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled or not self.budget.consume():
            return None
        try:
            response = requests.post(
                f"{self.settings.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.model,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": str(system_prompt)},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
                timeout=self.settings.timeout,
            )
            response.raise_for_status()
            body = response.json()
            choices = body.get("choices") if isinstance(body, dict) else None
            if not isinstance(choices, list) or not choices:
                return None
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if not isinstance(message, dict):
                return None
            return _decode_json_content(message.get("content"))
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return None
