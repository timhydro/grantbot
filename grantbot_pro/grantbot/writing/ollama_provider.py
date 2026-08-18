from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_models(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    output: list[str] = []
    for item in raw.split(","):
        model = item.strip()
        if model and model not in output:
            output.append(model)
    return tuple(output)


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
    fallback_models: tuple[str, ...] = _env_models("OLLAMA_FALLBACK_MODELS")
    allow_any_installed: bool = _env_bool("OLLAMA_ALLOW_ANY_INSTALLED", True)
    timeout_seconds: int = _env_int("OLLAMA_TIMEOUT_SECONDS", 300)
    context_tokens: int = _env_int("OLLAMA_NUM_CTX", 4096)
    max_output_tokens: int = _env_int("OLLAMA_NUM_PREDICT", 2048)
    keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "15m").strip() or "15m"


class OllamaProvider:
    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig()
        if not self.config.model:
            raise RuntimeError("OLLAMA_MODEL cannot be empty")
        if not self.config.base_url.startswith(("http://", "https://")):
            raise RuntimeError("OLLAMA_URL must start with http:// or https://")
        self.last_model = ""

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(
            f"{self.config.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=timeout or self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Ollama unavailable: {reason}") from exc
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise RuntimeError("Ollama returned a non-object response")
        return body

    def installed_models(self) -> list[str]:
        body = self._request_json("/api/tags", timeout=10)
        output: list[str] = []
        for item in body.get("models", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "").strip()
            if name and name not in output:
                output.append(name)
        return output

    @staticmethod
    def _matches(requested: str, installed: str) -> bool:
        requested = requested.strip()
        installed = installed.strip()
        if requested == installed:
            return True
        if ":" not in requested and installed.startswith(requested + ":"):
            return True
        return False

    def select_model(self, installed: list[str] | None = None) -> str:
        available = installed if installed is not None else self.installed_models()
        candidates = (self.config.model, *self.config.fallback_models)
        for candidate in candidates:
            for installed_name in available:
                if self._matches(candidate, installed_name):
                    return installed_name
        if self.config.allow_any_installed and available:
            return available[0]
        configured = ", ".join(candidates)
        raise RuntimeError(
            "No usable local Ollama model is installed. "
            f"Configured model(s): {configured}. "
            f"Install one with: ollama pull {self.config.model}"
        )

    def health(self) -> dict[str, Any]:
        try:
            installed = self.installed_models()
            selected = self.select_model(installed)
        except RuntimeError as exc:
            return {
                "available": False,
                "configured_model": self.config.model,
                "selected_model": None,
                "installed_models": [],
                "error": str(exc),
            }
        return {
            "available": True,
            "configured_model": self.config.model,
            "selected_model": selected,
            "installed_models": installed,
            "fallback_enabled": self.config.allow_any_installed,
            "context_tokens": self.config.context_tokens,
            "max_output_tokens": self.config.max_output_tokens,
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

        selected_model = self.select_model()
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": self.config.context_tokens,
                "num_predict": self.config.max_output_tokens,
            },
        }
        body = self._request_json("/api/generate", method="POST", payload=payload)
        text = body.get("response")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Ollama returned empty response")
        self.last_model = selected_model
        return text.strip()
