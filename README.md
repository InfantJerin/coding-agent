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
