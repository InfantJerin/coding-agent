from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from llm.models import ModelRef


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolCallResponse:
    stop_reason: str  # "tool_use" | "end_turn"
    text: str
    tool_uses: list[ToolUseBlock] = field(default_factory=list)


class LLMClient(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...

    def tool_call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse:
        ...


@dataclass
class OpenAIClient:
    model: str
    api_key: str

    def _openai_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API {exc.code}: {body}") from exc

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        body = self._openai_request(payload)
        return body["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _to_oai_messages(
        system_prompt: str, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Translate Anthropic-format messages to OpenAI chat format.

        Anthropic uses structured content lists for tool_use / tool_result turns.
        OpenAI uses tool_calls on the assistant message and role="tool" messages.
        Plain string content passes through unchanged.
        """
        out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                out.append({"role": role, "content": content})
                continue

            # content is a list of blocks
            if role == "assistant":
                text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
                tool_uses = [b for b in content if b.get("type") == "tool_use"]
                oai_msg: dict[str, Any] = {"role": "assistant"}
                oai_msg["content"] = "\n".join(text_parts) if text_parts else None
                if tool_uses:
                    oai_msg["tool_calls"] = [
                        {
                            "id": tu["id"],
                            "type": "function",
                            "function": {
                                "name": tu["name"],
                                "arguments": json.dumps(tu.get("input", {})),
                            },
                        }
                        for tu in tool_uses
                    ]
                out.append(oai_msg)

            elif role == "user":
                # tool_result blocks → individual role="tool" messages
                for block in content:
                    if block.get("type") == "tool_result":
                        out.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })

        return out

    def tool_call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse:
        # Modern OpenAI tools API (not deprecated functions)
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in tools
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_oai_messages(system_prompt, messages),
            "tools": oai_tools,
            "temperature": 0,
        }
        body = self._openai_request(payload)
        choice = body["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")
        text = (message.get("content") or "").strip()
        tool_uses: list[ToolUseBlock] = []
        if finish_reason == "tool_calls":
            for tc in message.get("tool_calls", []):
                tool_uses.append(
                    ToolUseBlock(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        input=json.loads(tc["function"].get("arguments", "{}")),
                    )
                )
            return ToolCallResponse(stop_reason="tool_use", text=text, tool_uses=tool_uses)
        return ToolCallResponse(stop_reason="end_turn", text=text, tool_uses=[])


@dataclass
class AnthropicClient:
    model: str
    api_key: str

    def _anthropic_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API {exc.code}: {body}") from exc

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 800,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        body = self._anthropic_request(payload)
        parts = body.get("content", [])
        texts = [item.get("text", "") for item in parts if item.get("type") == "text"]
        return "\n".join(texts).strip()

    def tool_call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
            "tools": tools,
        }
        body = self._anthropic_request(payload)
        stop_reason = body.get("stop_reason", "end_turn")
        parts = body.get("content", [])
        text = "\n".join(item.get("text", "") for item in parts if item.get("type") == "text").strip()
        tool_uses: list[ToolUseBlock] = [
            ToolUseBlock(id=item["id"], name=item["name"], input=item.get("input", {}))
            for item in parts
            if item.get("type") == "tool_use"
        ]
        return ToolCallResponse(stop_reason=stop_reason, text=text, tool_uses=tool_uses)


@dataclass
class DisabledLLMClient:
    reason: str

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError(self.reason)

    def tool_call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse:
        raise RuntimeError(self.reason)


def build_llm_client(model_ref: ModelRef | None) -> LLMClient | None:
    if model_ref is None:
        return None

    if model_ref.provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        return OpenAIClient(model=model_ref.model, api_key=api_key)

    if model_ref.provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return None
        return AnthropicClient(model=model_ref.model, api_key=api_key)

    return None
