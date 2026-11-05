"""LLM provider adapter: one interface for Groq, any OpenAI-compatible endpoint, and Ollama.

LLM_PROVIDER may list several providers in order of preference, e.g. "groq,ollama":
if the first one fails or times out, the next is tried. Keys come from .env only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from . import config  # noqa: F401  (loads .env)


class LLMError(RuntimeError):
    pass


@dataclass
class OpenAICompatible:
    base_url: str
    api_key: str
    model: str
    name: str = "openai"
    timeout: float = 25.0
    reasoning_effort: str | None = None

    def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 900) -> str:
        if not self.api_key:
            raise LLMError(f"{self.name}: no API key set in .env")
        body: dict = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if self.reasoning_effort and "gpt-oss" in self.model:
            body["reasoning_effort"] = self.reasoning_effort
        try:
            r = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"{self.name}: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {r.status_code}: {r.text[:300]}")
        content = r.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise LLMError(f"{self.name}: empty response")
        return content.strip()

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"


@dataclass
class Ollama:
    base_url: str
    model: str
    name: str = "ollama"
    timeout: float = 60.0

    def _resolve_model(self) -> str:
        """'llama3.2' -> an installed tag such as 'llama3.2:3b'."""
        try:
            tags = httpx.get(f"{self.base_url}/api/tags", timeout=3).json().get("models", [])
        except httpx.HTTPError:
            return self.model
        names = [t["name"] for t in tags]
        if self.model in names:
            return self.model
        return next((n for n in names if n.split(":")[0] == self.model.split(":")[0]), self.model)

    def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 900) -> str:
        model = self._resolve_model()
        try:
            r = httpx.post(
                f"{self.base_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"ollama: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"ollama: HTTP {r.status_code}: {r.text[:300]}")
        content = r.json().get("message", {}).get("content", "")
        if not content.strip():
            raise LLMError("ollama: empty response")
        return content.strip()

    @property
    def label(self) -> str:
        return f"ollama:{self.model}"


@dataclass
class ChainLLM:
    """Try providers in order; the first that answers wins."""

    providers: list
    last_used: str = ""

    def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 900) -> str:
        errors = []
        for p in self.providers:
            try:
                out = p.complete(messages, temperature=temperature, max_tokens=max_tokens)
                self.last_used = p.label
                return out
            except LLMError as e:
                errors.append(str(e))
        raise LLMError(" | ".join(errors) or "no LLM provider configured")

    @property
    def label(self) -> str:
        return self.last_used or "+".join(p.label for p in self.providers)


def make_provider(name: str):
    name = name.strip().lower()
    timeout = float(os.getenv("LLM_TIMEOUT", "25"))
    effort = os.getenv("LLM_REASONING_EFFORT", "low") or None
    if name == "groq":
        return OpenAICompatible(
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key=os.getenv("GROQ_API_KEY", ""),
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            name="groq",
            timeout=timeout,
            reasoning_effort=effort,
        )
    if name == "openai":
        return OpenAICompatible(
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            name="openai",
            timeout=timeout,
            reasoning_effort=effort,
        )
    if name == "ollama":
        return Ollama(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", "90")),
        )
    raise ValueError(f"Unknown LLM provider '{name}' (use groq, openai or ollama)")


def get_llm(spec: str | None = None) -> ChainLLM:
    spec = spec or os.getenv("LLM_PROVIDER", "groq,ollama")
    return ChainLLM([make_provider(n) for n in spec.split(",") if n.strip()])
