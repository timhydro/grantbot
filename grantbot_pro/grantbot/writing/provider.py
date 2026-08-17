from __future__ import annotations

from typing import Protocol, Any

try:
    # If the existing OllamaProvider is available, users can still import it and instantiate directly.
    from grantbot.writing.ollama_provider import OllamaProvider  # type: ignore
except Exception:  # pragma: no cover - optional provider
    OllamaProvider = None  # type: ignore


class Provider(Protocol):
    """Lightweight provider protocol used by writer code.

    Implementations must expose a `config` attribute with at least a `model` key,
    a `health()` method returning a dict, and `generate(prompt, system, ...)`.
    """

    config: Any

    def health(self) -> dict[str, Any]:
        ...

    def generate(self, prompt: str, system: str, temperature: float = 0.3, max_tokens: int | None = None) -> str:
        ...


class DefaultProvider:
    """Adapter that returns an OllamaProvider instance when available or raises a helpful error."""

    def __init__(self) -> None:
        if OllamaProvider is None:
            raise RuntimeError(
                "OllamaProvider is not available in this environment. Install/configure the provider or supply a custom Provider."
            )
        # instantiate with default config from OllamaProvider
        self._impl = OllamaProvider()

    @property
    def config(self) -> Any:
        return getattr(self._impl, "config", {})

    def health(self) -> dict[str, Any]:
        return getattr(self._impl, "health")()

    def generate(self, prompt: str, system: str, temperature: float = 0.3, max_tokens: int | None = None) -> str:
        # Mirror the common provider interface. OllamaProvider may accept different kwargs.
        return getattr(self._impl, "generate")(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
