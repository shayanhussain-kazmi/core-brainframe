# raahib-os (Raahib OS)

Minimal local "brain frame" for Raahib OS with strict routing order:

`command → safety → knowledge → llm`

## Requirements

- Python 3.11+
- Standard library only (no required external dependencies)

## Run

```bash
python -m raahib
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

- **`raahib/commands.py`**: Parses control commands (`mode:*`, `status`, stub KB/memory commands).
- **`raahib/safety.py`**: Blocks disallowed content; mode-specific handling for health and mood.
- **`raahib/kb.py`**: Placeholder local knowledge base (`search` currently returns empty list).
- **`raahib/llm.py`**: Cloud LLM stub using OpenAI Responses API when `OPENAI_API_KEY` is set; otherwise offline fallback.
- **`raahib/router.py`**: Enforces strict order:
  1. Command handling
  2. Safety gate
  3. Knowledge lookup + strong match placeholder threshold
  4. LLM generation
- **`raahib/state.py`**: Stores mode, short-term memory, and capability flags.
- **`raahib/__main__.py`**: REPL entrypoint used by `python -m raahib`.

## Test

```bash
python -m unittest
```
