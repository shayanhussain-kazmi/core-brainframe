from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class CloudLLM:
    """Cloud LLM wrapper with offline fallback behavior."""

    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        self.model = model

    @property
    def available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def generate(self, prompt: str, mode_hint: str) -> tuple[str, dict[str, str]]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return (
                "Offline fallback: no cloud API key configured. Please set OPENAI_API_KEY to enable cloud responses.",
                {"provider": "offline", "reason": "missing_api_key"},
            )

        payload = {
            "model": self.model,
            "input": f"Mode hint: {mode_hint}\nUser: {prompt}",
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError:
            return (
                "Offline fallback: cloud call failed, so local response mode is active.",
                {"provider": "offline", "reason": "network_error"},
            )

        text = data.get("output_text")
        if text:
            return text, {"provider": "openai", "model": self.model}
        return (
            "Cloud response unavailable; using offline fallback.",
            {"provider": "offline", "reason": "empty_output"},
        )
