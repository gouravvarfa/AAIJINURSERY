"""Provider-independent AI layer.

Every provider (Groq, Gemini, OpenRouter, ...) implements the same
`AIProvider` interface and is adapted to/from one universal message/tool
shape (OpenAI's function-calling format, since that's what Groq and
OpenRouter already speak natively -- Gemini is translated to/from it).
Nothing outside this file needs to know which provider is actually
answering a given request; app/ai/gateway.py just asks the chain for the
next configured provider and calls `.chat(...)`.

No provider here ever touches the database directly -- only app/ai/tools.py
does that, and only through the same read-only service functions the rest
of the app already uses. A provider's only job is: given a conversation and
a list of available tools, decide what to say or which tool to call next.
"""
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass
class AIResponse:
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider_name: str = ""


class ProviderError(Exception):
    """Raised for any provider failure (network, auth, rate limit, bad
    response) -- the gateway catches this and falls through to the next
    provider in the chain, never lets it become a 500 to the customer."""


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True only if this provider has everything it needs (an API key,
        mainly) to actually be tried -- lets the gateway skip straight past
        unconfigured providers instead of attempting and failing each one."""

    @abstractmethod
    async def chat(self, messages: list[dict], tools: list[dict]) -> AIResponse:
        """`messages`: OpenAI-style [{role, content, [tool_call_id], [name]}, ...].
        `tools`: OpenAI-style function-calling schema. Must raise
        ProviderError (never let a raw httpx/parsing exception escape) on
        any failure so the gateway's fallback chain can react uniformly."""


class _OpenAICompatibleProvider(AIProvider):
    """Shared implementation for any provider that speaks the OpenAI chat-
    completions wire format as-is (Groq and OpenRouter both do -- only the
    base URL, API key, and default model differ)."""

    base_url: str = ""
    env_key: str = ""
    default_model_env: str = ""
    default_model: str = ""
    extra_headers: dict = {}

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.env_key))

    def _model(self) -> str:
        return os.environ.get(self.default_model_env, self.default_model)

    async def chat(self, messages: list[dict], tools: list[dict]) -> AIResponse:
        api_key = os.environ.get(self.env_key)
        if not api_key:
            raise ProviderError(f"{self.name}: no API key configured")

        payload = {"model": self._model(), "messages": messages, "temperature": 0.3}
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {api_key}", **self.extra_headers},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: request failed ({exc})") from exc

        if resp.status_code == 401:
            raise ProviderError(f"{self.name}: invalid API key")
        if resp.status_code == 429:
            raise ProviderError(f"{self.name}: rate limited")
        if resp.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {resp.status_code} - {resp.text[:200]}")

        try:
            data = resp.json()
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"{self.name}: unexpected response shape ({exc})") from exc

        tool_calls = []
        for tc in message.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(call_id=tc.get("id", ""), name=tc["function"]["name"], arguments=args))

        return AIResponse(content=message.get("content"), tool_calls=tool_calls, provider_name=self.name)


class GroqProvider(_OpenAICompatibleProvider):
    """Primary provider -- Groq's free tier (generous rate limits, fast
    inference). https://console.groq.com"""

    name = "groq"
    base_url = "https://api.groq.com/openai/v1/chat/completions"
    env_key = "GROQ_API_KEY"
    default_model_env = "GROQ_MODEL"
    default_model = "llama-3.1-8b-instant"


class OpenRouterProvider(_OpenAICompatibleProvider):
    """Optional third provider -- OpenRouter proxies several providers'
    free-tier models behind one OpenAI-compatible API. The specific free
    model slug changes over time on OpenRouter's end; override via
    OPENROUTER_MODEL if the default below is ever retired."""

    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1/chat/completions"
    env_key = "OPENROUTER_API_KEY"
    default_model_env = "OPENROUTER_MODEL"
    default_model = "meta-llama/llama-3.1-8b-instruct:free"
    extra_headers = {"HTTP-Referer": "https://shreeaaijihightechnursery.in", "X-Title": "Aaiji Nursery"}


class GeminiProvider(AIProvider):
    """Fallback provider -- Gemini's free tier. Gemini's REST API shape
    (contents/parts, functionDeclarations, functionCall/functionResponse)
    is different enough from OpenAI's that it needs real translation, both
    ways, instead of just forwarding the payload."""

    name = "gemini"

    def is_configured(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def _model(self) -> str:
        return os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    @staticmethod
    def _to_gemini_tools(tools: list[dict]) -> list[dict]:
        declarations = []
        for t in tools:
            fn = t.get("function", t)
            declarations.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return [{"functionDeclarations": declarations}] if declarations else []

    @staticmethod
    def _to_gemini_contents(messages: list[dict]) -> tuple[Optional[str], list[dict]]:
        system_instruction = None
        contents = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                # Gemini has no "system" message role -- collapses into a
                # single system_instruction field sent alongside contents.
                system_instruction = (system_instruction + "\n" if system_instruction else "") + (m.get("content") or "")
                continue
            if role == "tool":
                contents.append(
                    {
                        "role": "function",
                        "parts": [{"functionResponse": {"name": m.get("name", ""), "response": {"result": m.get("content", "")}}}],
                    }
                )
                continue
            if role == "assistant" and m.get("tool_calls"):
                # Re-express a previous assistant tool-call turn as Gemini's
                # functionCall part so the model has its own prior turn in
                # context for the follow-up.
                parts = [
                    {"functionCall": {"name": tc["function"]["name"], "args": json.loads(tc["function"]["arguments"] or "{}")}}
                    for tc in m["tool_calls"]
                ]
                contents.append({"role": "model", "parts": parts})
                continue
            gem_role = "model" if role == "assistant" else "user"
            contents.append({"role": gem_role, "parts": [{"text": m.get("content") or ""}]})
        return system_instruction, contents

    async def chat(self, messages: list[dict], tools: list[dict]) -> AIResponse:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ProviderError("gemini: no API key configured")

        system_instruction, contents = self._to_gemini_contents(messages)
        payload: dict = {"contents": contents, "generationConfig": {"temperature": 0.3}}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        gemini_tools = self._to_gemini_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model()}:generateContent?key={api_key}"
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"gemini: request failed ({exc})") from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise ProviderError("gemini: invalid API key")
        if resp.status_code == 429:
            raise ProviderError("gemini: rate limited")
        if resp.status_code >= 400:
            raise ProviderError(f"gemini: HTTP {resp.status_code} - {resp.text[:200]}")

        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"gemini: unexpected response shape ({exc})") from exc

        tool_calls, text_parts = [], []
        for i, part in enumerate(parts):
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(ToolCall(call_id=f"gemini-{i}", name=fc["name"], arguments=fc.get("args") or {}))
            elif "text" in part:
                text_parts.append(part["text"])

        return AIResponse(content="\n".join(text_parts) or None, tool_calls=tool_calls, provider_name=self.name)


def build_provider_chain() -> list[AIProvider]:
    """Primary -> fallback -> optional, in the order the gateway should try
    them. Each entry always exists (so the list length/order never changes
    based on config), is_configured() is what actually gates whether the
    gateway attempts it."""
    return [GroqProvider(), GeminiProvider(), OpenRouterProvider()]
