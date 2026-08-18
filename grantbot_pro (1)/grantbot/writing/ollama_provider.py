from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
    timeout_seconds: int = 300


class OllamaProvider:
    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig()
        if not self.config.model:
            raise RuntimeError("OLLAMA_MODEL cannot be empty")

    def health(self) -> dict[str, Any]:
        req = Request(f"{self.config.base_url}/api/tags", method="GET")
        try:
            with urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError) as exc:
            return {"available": False, "model": self.config.model, "error": str(exc)}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        names = {
            str(item.get("name", ""))
            for item in body.get("models", [])
            if isinstance(item, dict)
        }
        return {
            "available": True,
            "model": self.config.model,
            "model_installed": self.config.model in names,
        }

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float = 0.3,
    ) -> str:
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        if not system.strip():
            raise ValueError("system cannot be empty")
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be between 0 and 1")

        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature},
        }
        req = Request(
            f"{self.config.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Ollama unavailable: {exc.reason}") from exc

        body = json.loads(raw)
        text = body.get("response")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Ollama returned empty response")
        return text.strip()
