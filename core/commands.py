from __future__ import annotations

from dataclasses import dataclass

from core.modes import parse_mode
from core.state import AppState


@dataclass(slots=True)
class CommandResult:
    handled: bool
    output: str = ""
    metadata: dict[str, str] | None = None


class CommandParser:
    def parse(self, text: str, state: AppState) -> CommandResult:
        cleaned = text.strip()
        if not cleaned:
            return CommandResult(handled=False)

        if cleaned.lower().startswith("mode:"):
            mode_name = cleaned.split(":", 1)[1].strip()
            mode = parse_mode(mode_name)
            if mode is None:
                return CommandResult(
                    handled=True,
                    output=f"Unknown mode '{mode_name}'. Allowed: {', '.join(m.value for m in state.mode.__class__)}",
                    metadata={"type": "command", "name": "mode", "success": "false"},
                )
            state.mode = mode
            return CommandResult(
                handled=True,
                output=f"Mode set to {mode.value}.",
                metadata={"type": "command", "name": "mode", "success": "true"},
            )

        if cleaned.lower() == "status":
            capabilities = ", ".join(
                f"{k}={'on' if v else 'off'}" for k, v in sorted(state.capabilities.items())
            )
            return CommandResult(
                handled=True,
                output=f"mode={state.mode.value}; capabilities: {capabilities}",
                metadata={"type": "command", "name": "status", "success": "true"},
            )

        if cleaned.lower().startswith("kb:search "):
            query = cleaned.split(" ", 1)[1].strip()
            return CommandResult(
                handled=True,
                output=f"KB search command received (stub): {query}",
                metadata={"type": "command", "name": "kb_search", "success": "true"},
            )

        if cleaned.lower() == "memory:show":
            return CommandResult(
                handled=True,
                output="Memory view (stub): " + " | ".join(state.short_term_history[-5:]),
                metadata={"type": "command", "name": "memory_show", "success": "true"},
            )

        return CommandResult(handled=False)
