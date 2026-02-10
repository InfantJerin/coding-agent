# Generic Agent Architecture with Finance Tool Packs

## Goal

Build a generic agent runtime (interactive response mode by default) that remains domain-agnostic while enabling specialized financial-document workflows through pluggable tools and profiles.

This follows the same design direction used in OpenClaw: keep the runtime generic and move domain behavior into skills/tools/config.

## Reference Mapping to OpenClaw

This design is aligned to the following OpenClaw implementation areas:

- Embedded Pi agent runner and session execution flow:
  - `/Users/infantjerin/Projects/git/open-source/openclaw/src/agents/pi-embedded-runner.ts`
  - `/Users/infantjerin/Projects/git/open-source/openclaw/src/agents/pi-embedded-subscribe.ts`
- Tool policy and gating:
  - `/Users/infantjerin/Projects/git/open-source/openclaw/src/agents/tool-policy.ts`
  - `/Users/infantjerin/Projects/git/open-source/openclaw/src/agents/pi-tools.policy.ts`
- Skill loading and prompt composition:
  - `/Users/infantjerin/Projects/git/open-source/openclaw/src/agents/skills.ts`
  - `/Users/infantjerin/Projects/git/open-source/openclaw/docs/tools/skills.md`
- High-level architecture and loop references:
  - `/Users/infantjerin/Projects/git/open-source/openclaw/docs/concepts/architecture.md`
  - `/Users/infantjerin/Projects/git/open-source/openclaw/docs/concepts/agent-loop.md`

## Design Principles

1. Keep one runtime loop for all domains.
2. Treat finance capabilities as pluggable tool packs and profiles.
3. Make headless execution the default entrypoint.
4. Keep output contracts explicit and machine-readable.
5. Capture evidence and execution traces for auditability.

## Runtime Layers

1. Core Runtime
- Task lifecycle (plan -> execute -> validate -> render).
- Tool registry and policy enforcement.
- Run state and artifact collection.

2. Profile Layer
- Defines the tool set, defaults, and policy for a given run.
- Example profiles:
  - `generic`: no domain assumptions.
  - `finance-docs`: adds financial extraction and analysis tools.

3. Tool Packs
- Independent functions with typed input/output contracts.
- Categories:
  - Document/text tools (file read, normalization).
  - Shell tools (controlled command execution).
  - Finance tools (key-term extraction, covenant lookup, Q&A support).
  - Retrieval tools (chunking, indexing, ranked retrieval).

4. Output Contracts
- Always produce deterministic artifacts:
  - `run_trace.json`
  - `summary_report.md`
  - `extraction.json` (when extraction tools are used)

## LLM Layer

- `src/llm/catalog.py`: model catalog loading.
- `src/llm/selection.py`: provider/model resolution from explicit refs or aliases.
- `src/llm/providers.py`: provider adapters (OpenAI, Anthropic) with env-key activation.
- Runtime falls back to deterministic retrieval evidence when no API key/model is configured.

## Execution Flow

1. Load task request and selected profile.
2. Build the allowed tool registry from profile policy.
3. Normalize source documents into text context.
4. Execute planned steps using tools.
5. Validate tool outputs and evidence links.
6. Persist artifacts and return a final run result.

## Deployment Modes

1. Agent Response (Primary)
- CLI/entrypoint accepts a user query and returns an answer directly.

2. Headless (Optional)
- CLI or batch runner executes tasks autonomously and writes artifacts.

3. Conversational Inbox (Optional)
- Same runtime, different interaction channel.

4. API Service (Later)
- Wrap headless runner with HTTP endpoints.

## Repo Structure

- `docs/architecture/generic-agent-finance.md`: architecture reference.
- `src/agent_core/`: generic runtime engine.
- `src/tools/`: tool implementations.
- `src/profiles/`: profile definitions and tool policies.
- `src/main.py`: headless entrypoint.
- `examples/`: sample task payloads.

## Milestone M1 (Implemented in this repo)

1. Generic headless runtime and profile selection.
2. Pluggable tool registry with policy filters.
3. Finance document tools for extraction + Q&A scaffolding.
4. Dual-output artifacts (report + JSON + trace).

## Next Milestones

1. Add PDF/DOCX parsers and OCR fallback.
2. Add richer finance schema extraction with confidence scoring.
3. Add retrieval index for long credit agreements.
4. Add API wrapper for remote execution.
