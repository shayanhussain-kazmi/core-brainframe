from __future__ import annotations

from dataclasses import dataclass

from raahib.commands import CommandParser
from raahib.kb import KnowledgeBase
from raahib.llm import CloudLLM
from raahib.modes import MODE_HINTS
from raahib.safety import SafetyGate
from raahib.state import AppState


@dataclass(slots=True)
class RouteResult:
    text: str
    metadata: dict[str, str]


class Router:
    """Strict order routing: command -> safety -> knowledge -> llm."""

    def __init__(
        self,
        state: AppState,
        commands: CommandParser | None = None,
        safety: SafetyGate | None = None,
        kb: KnowledgeBase | None = None,
        llm: CloudLLM | None = None,
    ) -> None:
        self.state = state
        self.commands = commands or CommandParser()
        self.safety = safety or SafetyGate()
        self.kb = kb or KnowledgeBase()
        self.llm = llm or CloudLLM()

    def route(self, user_text: str) -> RouteResult:
        command_result = self.commands.parse(user_text, self.state)
        if command_result.handled:
            return RouteResult(
                text=command_result.output,
                metadata=command_result.metadata or {"type": "command"},
            )

        safety_result = self.safety.evaluate(user_text, self.state.mode)
        if not safety_result.allowed:
            return RouteResult(
                text=safety_result.message,
                metadata=safety_result.metadata or {"type": "safety", "blocked": "true"},
            )

        hits = self.kb.search(user_text)
        if hits:
            top = max(hits, key=lambda hit: hit.score)
            if top.score >= self.state.settings.kb_strong_match_threshold:
                return RouteResult(
                    text=f"KB strong match from {top.source}: {top.snippet}",
                    metadata={
                        "type": "knowledge",
                        "match": "strong",
                        "score": f"{top.score:.2f}",
                    },
                )

        hints = MODE_HINTS[self.state.mode]
        mode_hint = f"tone={hints['tone']}; verbosity={hints['verbosity']}"
        llm_text, llm_meta = self.llm.generate(user_text, mode_hint=mode_hint)

        if safety_result.message:
            llm_text = f"{safety_result.message} {llm_text}".strip()

        self.state.remember(f"user:{user_text}")
        self.state.remember(f"assistant:{llm_text}")
        return RouteResult(text=llm_text, metadata={"type": "llm", **llm_meta})
