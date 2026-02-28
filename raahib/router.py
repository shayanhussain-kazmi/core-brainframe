from __future__ import annotations

from dataclasses import dataclass

from raahib.commands import CommandParser
from raahib.kb import KnowledgeBase
from raahib.llm import CloudLLM
from raahib.modes import MODE_HINTS
from raahib.safety import SafetyGate
from raahib.state import AppState

_ISLAMIC_KEYWORDS = {
    "quran",
    "qur'an",
    "hadith",
    "dua",
    "imam",
    "fiqh",
    "fatwa",
    "marja",
    "najaf",
    "karbala",
    "allah",
    "sabr",
    "ayah",
    "tafsir",
    "sunnah",
}


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
        self.kb = kb or KnowledgeBase(state.settings.kb_db_path)
        self.kb.init_db()
        self.kb.seed_if_empty()

        self.commands = commands or CommandParser(self.kb)
        self.safety = safety or SafetyGate()
        self.llm = llm or CloudLLM()

    def _is_islamic_query(self, user_text: str) -> bool:
        lowered = user_text.lower()
        return any(keyword in lowered for keyword in _ISLAMIC_KEYWORDS)

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
                text_parts = [top.card.title]
                if top.card.arabic:
                    text_parts.append(top.card.arabic)
                if top.card.translation_en:
                    text_parts.append(top.card.translation_en)
                if top.card.explanation:
                    text_parts.append(top.card.explanation)
                text_parts.append(f"Source: {top.card.source_name} ({top.card.reference})")
                if top.card.auth_grade:
                    text_parts.append(f"Auth grade: {top.card.auth_grade}")
                return RouteResult(
                    text="\n".join(text_parts),
                    metadata={
                        "type": "kb",
                        "card_id": str(top.card.id),
                        "score": f"{top.score:.2f}",
                        "source_name": top.card.source_name,
                        "reference": top.card.reference,
                        "auth_grade": top.card.auth_grade or "",
                    },
                )

        if self._is_islamic_query(user_text):
            return RouteResult(
                text="I don’t have a reliably sourced entry for that yet. You can add it with kb:add.",
                metadata={"type": "kb_miss"},
            )

        hints = MODE_HINTS[self.state.mode]
        mode_hint = f"tone={hints['tone']}; verbosity={hints['verbosity']}"
        llm_text, llm_meta = self.llm.generate(user_text, mode_hint=mode_hint)

        if safety_result.message:
            llm_text = f"{safety_result.message} {llm_text}".strip()

        self.state.remember(f"user:{user_text}")
        self.state.remember(f"assistant:{llm_text}")
        return RouteResult(text=llm_text, metadata={"type": "llm", **llm_meta})
