# Generic Headless Agent with Finance Tool Pack

This repo contains a minimal implementation of a generic agent runtime and a pluggable finance-document profile.

## OpenClaw-Aligned Components

- `src/llm/`: model catalog + model selection + provider adapter layer
- `src/tools/document_tools.py`: document map, anchors, section/definition extraction, xrefs
- `src/tools/state_tools.py`: scratchpad + reading trail tools
- `skills/finance-docs/SKILL.md`: skill-pack style finance instructions

## Run (Agent Mode - Default)

```bash
cd /Users/infantjerin/Projects/git/coding-agent-doc
PYTHONPATH=src python3 src/main.py \
  --query "What is the facility amount?" \
  --documents examples/sample_credit_agreement.txt
```

Optional LLM integration via environment:

```bash
cp .env.example .env
# Fill keys in .env
```

Provider selection behavior:

- If `OPENAI_API_KEY` is set, it uses OpenAI (`openai/gpt-4.1-mini`).
- Else if `ANTHROPIC_API_KEY` is set, it uses Anthropic (`anthropic/claude-3-5-sonnet-latest`).
- `AGENT_MODEL` can explicitly override provider/model.

## Ops-Like Workflow (Implemented)

The agent now follows:

1. Build document map (sections, definitions, xrefs, anchors)
2. Search in scoped regions
3. Read spans at anchors
4. Follow cross-references
5. Read referenced definitions
6. Write findings to scratchpad + reading trail
7. Quote evidence and run consistency check
8. Produce cited answer

Extraction is schema-driven and multi-pass:

1. Structure pass: use section/page index and definition map.
2. Field pass: extract target terms per document schema.
3. Validation pass: run consistency checks and report issues.

`document_type` can be set in task metadata (for example: `credit_agreement`, `compliance_certificate`).

## LLM Index Fallback

If TOC extraction is unavailable or weak, `build_doc_map` can use the configured LLM to propose a basic section index (`source: "llm"`), then merge it with parsed headings/outlines.

Section nodes now also include:

- `summary`
- `key_events`

This is used for tree-guided navigation and query matching.

## Run (Headless Mode)

```bash
cd /Users/infantjerin/Projects/git/coding-agent-doc
PYTHONPATH=src python3 src/main.py --mode headless \
  --task examples/task_credit_agreement.json \
  --output-dir output/run-1
```

## Output Artifacts

- `summary_report.md`
- `extraction.json`
- `run_trace.json`
- `run_result.json`

## Architecture

See:

- `docs/architecture/generic-agent-finance.md`

https://deepwiki.com/openclaw/openclaw/1-overview
