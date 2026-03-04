# raahib-os (Raahib OS)

Minimal local "brain frame" for Raahib OS with strict routing order:

`command → safety → knowledge → llm`

## Requirements

- Python 3.11+
- Standard library only (no required external dependencies)

## Configure external Islamic providers (optional)

Raahib can use external knowledge sources at runtime:

- `HadithProvider` from SQLite FTS5 DB
- `DuaProvider` from JSON

Set environment variables before running:

```bash
RAAHIB_HADITH_DB_PATH="C:\path\to\raah_e_bahisht.db"
RAAHIB_DUAS_JSON_PATH="C:\path\to\duas.json"
python -m raahib
```

If either path is missing/unset/invalid, that provider is automatically disabled (no crash).

> Do **not** commit runtime databases (for example `raah_e_bahisht.db`) into git.

## Run

```bash
python -m raahib
```

You will enter a REPL. Type text and receive:
- `response: ...`
- `metadata: {...}`

Type `quit` or `exit` to leave.

## Preview/full behavior for Islamic sources

For Islamic-intent queries, Raahib only answers from sourced providers/KB (no LLM hallucination path):

- Hadith result: returns a concise preview and asks if you want the full narration.
- Dua result: returns a concise preview and asks if you want the full dua.
- Reply with `full` or `more` to expand the most recent preview.

## Example commands

- `mode:tutor`
- `mode:health`
- `status`
- `sources`
- `hadith:search patience`
- `dua:search guidance`
- `kb:search mitochondria`
- `memory:show`

## Architecture

- **`raahib/commands.py`**: Parses control commands (`mode:*`, `status`, `sources`, KB/admin searches).
- **`raahib/safety.py`**: Blocks disallowed content; mode-specific handling for health and mood.
- **`raahib/kb.py`**: Local knowledge base with seeded Islamic cards and search.
- **`raahib/providers/`**: External providers for hadith SQLite FTS and duas JSON.
- **`raahib/llm.py`**: Cloud LLM stub using OpenAI Responses API when `OPENAI_API_KEY` is set; otherwise offline fallback.
- **`raahib/router.py`**: Enforces strict order, Islamic sourced-only behavior, and preview/full flow.
- **`raahib/state.py`**: Stores mode, short-term memory, capability flags, and last expandable item.
- **`raahib/__main__.py`**: REPL entrypoint used by `python -m raahib`.

## Test

```bash
python -m unittest
```
