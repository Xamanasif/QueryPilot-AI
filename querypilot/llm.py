"""Chat model clients: Groq for real runs, a scripted model for deterministic tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence, Union


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model produced it


@dataclass(frozen=True)
class AssistantTurn:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def to_message(self) -> dict:
        msg: dict = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return msg


class LLMError(RuntimeError):
    pass


class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...


class GroqChatModel:
    def __init__(self, api_key: str, model: str, temperature: float = 0.0, timeout: float = 60.0,
                 max_retries: int = 2, http_client=None):
        from groq import Groq

        self.client = Groq(api_key=api_key, timeout=timeout, max_retries=max_retries, http_client=http_client)
        self.model = model
        self.temperature = temperature

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=tools, tool_choice="auto",
                temperature=self.temperature,
            )
        except Exception as exc:  # network, auth, rate limit, malformed tool call
            raise LLMError(f"Groq request failed: {exc}") from exc
        msg = resp.choices[0].message
        calls = tuple(
            ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in (msg.tool_calls or [])
        )
        return AssistantTurn(msg.content, calls)


# --- scripted model for tests and offline demos --------------------------------

ScriptStep = Union[AssistantTurn, Callable[[list[dict]], AssistantTurn], Exception]


def call(name: str, call_id: str | None = None, raw: str | None = None, **arguments) -> ToolCall:
    return ToolCall(call_id or f"call_{name}", name, raw if raw is not None else json.dumps(arguments))


def tool_turn(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(None, tuple(calls))


def final(text: str) -> AssistantTurn:
    return AssistantTurn(text)


@dataclass
class ScriptedChatModel:
    """Replays a fixed sequence of model turns. A step may be a callable that
    inspects the conversation so far, or an exception to raise."""
    script: Sequence[ScriptStep]
    received: list[list[dict]] = field(default_factory=list)

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.received.append([dict(m) for m in messages])
        index = len(self.received) - 1
        if index >= len(self.script):
            raise LLMError("Scripted model has no more responses")
        step = self.script[index]
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step
