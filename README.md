# core-brainframe

Minimal local "brain frame" core with strict routing order:

`command → safety → knowledge → llm`

## Requirements

- Python 3.11+
- Standard library only (no required external dependencies)

## Run

```bash
python -m core
```

You will enter a REPL. Type text and receive:
- `response: ...`
- `metadata: {...}`

Type `quit` or `exit` to leave.

## Example commands

- `mode:tutor`
- `mode:health`
- `status`
- `kb:search mitochondria`
- `memory:show`

## Architecture

- **`core/commands.py`**: Parses control commands (`mode:*`, `status`, stub KB/memory commands).
- **`core/safety.py`**: Blocks disallowed content; mode-specific handling for health and mood.
- **`core/kb.py`**: Placeholder local knowledge base (`search` currently returns empty list).
- **`core/llm.py`**: Cloud LLM stub using OpenAI Responses API when `OPENAI_API_KEY` is set; otherwise offline fallback.
- **`core/router.py`**: Enforces strict order:
  1. Command handling
  2. Safety gate
  3. Knowledge lookup + strong match placeholder threshold
  4. LLM generation
- **`core/state.py`**: Stores mode, short-term memory, and capability flags.
- **`core/__main__.py`**: REPL entrypoint used by `python -m core`.

## Test

```bash
python -m unittest
```
