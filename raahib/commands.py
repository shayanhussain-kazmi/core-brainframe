from __future__ import annotations

from dataclasses import dataclass

from raahib.kb import KnowledgeBase
from raahib.modes import parse_mode
from raahib.state import AppState


@dataclass(slots=True)
class CommandResult:
    handled: bool
    output: str = ""
    metadata: dict[str, str] | None = None


class CommandParser:
    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or KnowledgeBase()

    def _read_multiline(self, prompt: str) -> str | None:
        print(prompt)
        print("Finish with a single '.' on its own line.")
        lines: list[str] = []
        while True:
            line = input().rstrip("\n")
            if line.strip() == ".":
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        return text or None

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
            hits = self.kb.search(query)
            if not hits:
                return CommandResult(
                    handled=True,
                    output="No KB hits found.",
                    metadata={"type": "command", "name": "kb_search", "success": "true", "count": "0"},
                )
            lines = [
                f"{h.card.id} | {h.card.type} | {h.card.title} | {h.score:.2f}" for h in hits
            ]
            return CommandResult(
                handled=True,
                output="\n".join(lines),
                metadata={
                    "type": "command",
                    "name": "kb_search",
                    "success": "true",
                    "count": str(len(hits)),
                },
            )

        if cleaned.lower().startswith("kb:show "):
            try:
                card_id = int(cleaned.split(" ", 1)[1].strip())
            except ValueError:
                return CommandResult(
                    handled=True,
                    output="Invalid KB id.",
                    metadata={"type": "command", "name": "kb_show", "success": "false"},
                )
            card = self.kb.get_card(card_id)
            if card is None:
                return CommandResult(
                    handled=True,
                    output="Card not found.",
                    metadata={"type": "command", "name": "kb_show", "success": "false"},
                )
            out = (
                f"type: {card.type}\n"
                f"title: {card.title}\n"
                f"arabic: {card.arabic or ''}\n"
                f"translation: {card.translation_en or ''}\n"
                f"explanation: {card.explanation or ''}\n"
                f"source_name: {card.source_name}\n"
                f"reference: {card.reference}\n"
                f"auth_grade: {card.auth_grade or ''}\n"
                f"tags: {card.tags or ''}"
            )
            return CommandResult(
                handled=True,
                output=out,
                metadata={"type": "command", "name": "kb_show", "success": "true", "card_id": str(card.id)},
            )

        if cleaned.lower().startswith("kb:delete "):
            try:
                card_id = int(cleaned.split(" ", 1)[1].strip())
            except ValueError:
                return CommandResult(
                    handled=True,
                    output="Invalid KB id.",
                    metadata={"type": "command", "name": "kb_delete", "success": "false"},
                )
            deleted = self.kb.delete_card(card_id)
            return CommandResult(
                handled=True,
                output="Deleted." if deleted else "Card not found.",
                metadata={
                    "type": "command",
                    "name": "kb_delete",
                    "success": "true" if deleted else "false",
                    "card_id": str(card_id),
                },
            )

        if cleaned.lower().startswith("kb:export "):
            path = cleaned.split(" ", 1)[1].strip()
            out_path = self.kb.export_json(path)
            return CommandResult(
                handled=True,
                output=f"Exported KB to {out_path}",
                metadata={"type": "command", "name": "kb_export", "success": "true", "path": str(out_path)},
            )

        if cleaned.lower() == "kb:add":
            ctype = input("type: ").strip()
            title = input("title: ").strip()
            source_name = input("source_name: ").strip()
            reference = input("reference: ").strip()
            auth_grade = input("auth_grade (optional): ").strip() or None
            tags = input("tags (optional): ").strip() or None
            arabic = self._read_multiline("arabic (optional multiline)")
            translation = self._read_multiline("translation (optional multiline)")
            explanation = self._read_multiline("explanation (optional multiline)")
            card = self.kb.add_card(
                type=ctype,
                title=title,
                source_name=source_name,
                reference=reference,
                auth_grade=auth_grade,
                tags=tags,
                arabic=arabic,
                translation_en=translation,
                explanation=explanation,
            )
            return CommandResult(
                handled=True,
                output=f"Added KB card #{card.id}: {card.title}",
                metadata={"type": "command", "name": "kb_add", "success": "true", "card_id": str(card.id)},
            )

        if cleaned.lower() == "memory:show":
            return CommandResult(
                handled=True,
                output="Memory view (stub): " + " | ".join(state.short_term_history[-5:]),
                metadata={"type": "command", "name": "memory_show", "success": "true"},
            )

        return CommandResult(handled=False)
