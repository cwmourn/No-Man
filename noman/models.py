"""Thin clients for the chat models No-Man can test.

Models are named "provider:model", for example "openai:gpt-4o-mini" or
"anthropic:claude-sonnet-4-5". Only the Python standard library is used, so
there is nothing to install beyond No-Man itself.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

Message = dict  # {"role": "user" | "assistant", "content": str}


class Model:
    name: str = "model"

    def chat(self, messages: list[Message], system: str | None = None) -> str:
        raise NotImplementedError

    def check(self) -> None:
        """Raise a clear error before a run if the model can't be used."""


def _post_json(url: str, headers: dict, body: dict, timeout: float = 120) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"{url} returned {error.code}: {detail}") from error


def _require_key(env_var: str) -> str:
    key = os.environ.get(env_var)
    if not key:
        raise RuntimeError(f"Set the {env_var} environment variable to use this model.")
    return key


class OpenAIModel(Model):
    def __init__(self, model: str):
        self.model = model
        self.name = f"openai:{model}"
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def check(self) -> None:
        _require_key("OPENAI_API_KEY")

    def chat(self, messages: list[Message], system: str | None = None) -> str:
        key = _require_key("OPENAI_API_KEY")
        payload = ([{"role": "system", "content": system}] if system else []) + messages
        data = _post_json(
            f"{self.base_url}/chat/completions",
            {"authorization": f"Bearer {key}"},
            {"model": self.model, "messages": payload},
        )
        return data["choices"][0]["message"]["content"]


class AnthropicModel(Model):
    def __init__(self, model: str):
        self.model = model
        self.name = f"anthropic:{model}"

    def check(self) -> None:
        _require_key("ANTHROPIC_API_KEY")

    def chat(self, messages: list[Message], system: str | None = None) -> str:
        key = _require_key("ANTHROPIC_API_KEY")
        body = {"model": self.model, "max_tokens": 1024, "messages": messages}
        if system:
            body["system"] = system
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            body,
        )
        return "".join(block.get("text", "") for block in data["content"])


class FunctionModel(Model):
    """Wraps a plain Python function. Used for tests and offline demos."""

    def __init__(self, fn: Callable[[list[Message], str | None], str], name: str = "function"):
        self.fn = fn
        self.name = name

    def chat(self, messages: list[Message], system: str | None = None) -> str:
        return self.fn(messages, system)


PROVIDERS = {"openai": OpenAIModel, "anthropic": AnthropicModel}


def load_model(spec: str) -> Model:
    """Turn "provider:model" into a model client."""
    provider, sep, model = spec.partition(":")
    if not sep or not model:
        raise ValueError(f"Model must look like 'provider:model', got {spec!r}")
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Choose from: {', '.join(PROVIDERS)}")
    return PROVIDERS[provider](model)
