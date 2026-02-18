from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from agent_core.session import DealMeta, Session, SessionStore
from agent_core.system_prompt import build_chat_system_prompt
from agent_core.tooling import ToolPolicy, ToolRegistry
from llm.providers import LLMClient, ToolCallResponse
from tools.chat_tools import CHAT_TOOLS, TOOL_BOUND_PARAMS, TOOL_SPECS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trunc(value: Any, limit: int = 400) -> str:
    s = json.dumps(value, default=str) if not isinstance(value, str) else value
    return s[:limit] + " …" if len(s) > limit else s


class ContextBoundToolSet:
    """Wraps the registry and pre-binds doc_map + scratchpad state so the LLM
    only needs to pass user-facing parameters."""

    def __init__(
        self,
        registry: ToolRegistry,
        policy: ToolPolicy,
        doc_map: dict[str, Any] | None,
        scratchpad_state: dict[str, Any],
        chunk_index: dict[str, Any] | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.doc_map = doc_map or {}
        self.scratchpad_state = scratchpad_state
        self.chunk_index = chunk_index or {}

    def run(self, tool_name: str, user_params: dict[str, Any]) -> Any:
        self.policy.check(tool_name)
        try:
            tool = self.registry.resolve(tool_name)
        except KeyError:
            raise ValueError(f"Tool not found: {tool_name}")

        bound = TOOL_BOUND_PARAMS.get(tool_name, [])
        kwargs = dict(user_params)
        if "doc_map" in bound:
            kwargs["doc_map"] = self.doc_map
        if "state" in bound:
            kwargs["state"] = self.scratchpad_state
        if "text" in bound:
            text_parts = [str(v.get("text", "")) for v in self.doc_map.get("anchors", {}).values()]
            kwargs["text"] = "\n".join(text_parts)
        if "chunk_index" in bound:
            kwargs["chunk_index"] = self.chunk_index

        return tool.run(**kwargs)


class ChatAgent:
    def __init__(
        self,
        session: Session,
        deal_meta: DealMeta | None,
        doc_map: dict[str, Any] | None,
        registry: ToolRegistry,
        policy: ToolPolicy,
        llm_client: LLMClient,
        session_store: SessionStore,
        max_turns: int = 12,
        debug: bool = False,
        chunk_index: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.deal_meta = deal_meta
        self.doc_map = doc_map or {}
        self.chunk_index = chunk_index or {}
        self.registry = registry
        self.policy = policy
        self.llm_client = llm_client
        self.session_store = session_store
        self.max_turns = max_turns
        self.debug = debug
        self._scratchpad: dict[str, Any] = {}
        self._toolset = ContextBoundToolSet(
            registry=registry,
            policy=policy,
            doc_map=self.doc_map,
            scratchpad_state=self._scratchpad,
            chunk_index=self.chunk_index,
        )

    def _dbg(self, *parts: str) -> None:
        if self.debug:
            print(" ".join(parts), file=sys.stderr, flush=True)

    def update_doc_map(self, doc_map: dict[str, Any]) -> None:
        self.doc_map = doc_map
        self._toolset.doc_map = doc_map

    def update_chunk_index(self, chunk_index: dict[str, Any]) -> None:
        self.chunk_index = chunk_index
        self._toolset.chunk_index = chunk_index

    def _tools_spec(self) -> list[dict[str, Any]]:
        allowed: list[dict[str, Any]] = []
        for name in CHAT_TOOLS:
            try:
                self.policy.check(name)
                if name in TOOL_SPECS:
                    allowed.append(TOOL_SPECS[name])
            except PermissionError:
                pass
        return allowed

    def _build_api_messages(self) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        for msg in self.session.messages:
            api_messages.append({"role": msg["role"], "content": msg["content"]})
        return api_messages

    def send(self, user_message: str) -> str:
        self.session.messages.append({
            "role": "user",
            "content": user_message,
            "at": _now(),
        })

        tools_spec = self._tools_spec()
        system_prompt = build_chat_system_prompt(
            deal_meta=self.deal_meta,
            available_tool_names=[t["name"] for t in tools_spec],
        )

        api_messages = self._build_api_messages()
        initial_depth = len(api_messages)  # messages before this turn's tool loop
        final_text = ""

        if self.debug:
            anchors = len(self.doc_map.get("anchors", {}))
            sections = len(self.doc_map.get("sections", []))
            defs = len(self.doc_map.get("definitions", []))
            self._dbg(f"\n{'─'*60}")
            self._dbg(f"[debug] doc_map: {anchors} anchors, {sections} sections, {defs} definitions")
            self._dbg(f"[debug] tools available: {[t['name'] for t in tools_spec]}")
            self._dbg(f"[debug] history depth: {len(api_messages)} messages")
            self._dbg(f"{'─'*60}")

        for turn in range(self.max_turns):
            self._dbg(f"\n[turn {turn + 1}/{self.max_turns}] calling LLM …")

            response: ToolCallResponse = self.llm_client.tool_call(
                system_prompt=system_prompt,
                messages=api_messages,
                tools=tools_spec,
            )

            self._dbg(f"  stop_reason = {response.stop_reason}")
            if response.text:
                self._dbg(f"  text        = {_trunc(response.text, 200)}")

            if response.tool_uses:
                assistant_content: list[dict[str, Any]] = []
                if response.text:
                    assistant_content.append({"type": "text", "text": response.text})
                for tu in response.tool_uses:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tu.id,
                        "name": tu.name,
                        "input": tu.input,
                    })
                api_messages.append({"role": "assistant", "content": assistant_content})

                tool_results: list[dict[str, Any]] = []
                for tu in response.tool_uses:
                    self._dbg(f"  → {tu.name}({_trunc(tu.input, 120)})")
                    try:
                        result = self._toolset.run(tu.name, tu.input)
                        result_str = json.dumps(result, default=str)
                        self._dbg(f"  ← {_trunc(result_str, 300)}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": result_str,
                        })
                    except Exception as exc:
                        self._dbg(f"  ← ERROR: {exc}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": f"Error: {exc}",
                            "is_error": True,
                        })

                api_messages.append({"role": "user", "content": tool_results})

            else:
                # end_turn
                final_text = response.text
                self._dbg(f"  [end_turn] final text ({len(final_text)} chars)")
                break

        if not final_text:
            # Only look at messages produced during THIS turn's loop — not the prior history.
            # This prevents returning stale text from a previous user message's exchange.
            new_messages = api_messages[initial_depth:]
            for msg in reversed(new_messages):
                if msg["role"] == "assistant":
                    content = msg["content"]
                    if isinstance(content, str) and content.strip():
                        final_text = content.strip()
                        break
                    if isinstance(content, list):
                        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
                        joined = "\n".join(t for t in texts if t).strip()
                        if joined:
                            final_text = joined
                            break

        if not final_text:
            final_text = "(Reached turn limit — could not produce a final answer. Try rephrasing your question.)"
            self._dbg("  [warn] agent hit turn limit with no final text")

        self.session.messages.append({
            "role": "assistant",
            "content": final_text,
            "at": _now(),
        })
        self.session_store.save(self.session)
        return final_text
