from __future__ import annotations

from dataclasses import dataclass
import re

from raahib.commands import CommandParser
from raahib.comfort import comfort_intro_for, comfort_miss_intro, detect_emotion_category
from raahib.kb import KnowledgeBase, KnowledgeHit
from raahib.llm import CloudLLM
from raahib.modes import MODE_HINTS
from raahib.providers import DuaHit, DuaProvider, HadithHit, HadithProvider
from raahib.safety import SafetyGate
from raahib.state import AppState

_ISLAMIC_COMFORT_EMOTIONS = {"sadness", "grief", "anxiety", "hopelessness", "fear", "guilt"}

_ISLAMIC_KEYWORDS = {
    "quran",
    "qur'an",
    "hadith",
    "dua",
    "du'a",
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
    "حديث",
    "دعاء",
}

_EXPAND_TRIGGERS = {"full", "more", "expand"}


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
        hadith_provider: HadithProvider | None = None,
        dua_provider: DuaProvider | None = None,
    ) -> None:
        self.state = state
        self.kb = kb or KnowledgeBase(state.settings.kb_db_path)
        self.kb.init_db()
        self.kb.seed_if_empty()

        self.hadith_provider = hadith_provider or HadithProvider(state.settings.HADITH_DB_PATH)
        self.dua_provider = dua_provider or DuaProvider(
            state.settings.DUAS_JSON_PATH,
            state.settings.DUA_TAGS_PATH,
        )

        self.commands = commands or CommandParser(self.kb, self.hadith_provider, self.dua_provider)
        self.safety = safety or SafetyGate()
        self.llm = llm or CloudLLM()

    def _is_expand_intent(self, cleaned_text: str) -> bool:
        return cleaned_text.lower() in _EXPAND_TRIGGERS

    def _is_explicit_hadith_intent(self, text: str) -> bool:
        return bool(re.search(r"\bhadith\b|حديث", text, flags=re.IGNORECASE))

    def _is_explicit_dua_intent(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith("dua for"):
            return True
        return bool(re.search(r"\b(dua|du['’]a)\b|دعاء", text, flags=re.IGNORECASE))

    def _is_islamic_query(self, user_text: str) -> bool:
        lowered = user_text.lower()
        if self._is_explicit_hadith_intent(user_text) or self._is_explicit_dua_intent(user_text):
            return True
        return any(keyword in lowered for keyword in _ISLAMIC_KEYWORDS)

    def _with_comfort(self, result: RouteResult, emotion_category: str | None) -> RouteResult:
        if not emotion_category:
            return result
        return RouteResult(
            text=f"{comfort_intro_for(emotion_category)}\n\n{result.text}",
            metadata=result.metadata,
        )

    def _with_comfort_miss(self, result: RouteResult, emotion_category: str | None) -> RouteResult:
        if not emotion_category:
            return result
        return RouteResult(
            text=f"{comfort_miss_intro()}\n\n{result.text}",
            metadata=result.metadata,
        )

    def _preview(self, text: str | None) -> str:
        if not text:
            return ""
        max_chars = self.state.settings.MAX_PREVIEW_CHARS
        text = " ".join(text.splitlines()).strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "…"

    def _format_hadith_miss(self, query: str) -> RouteResult:
        return RouteResult(
            text=(
                "I couldn't find a hadith match for that wording in the hadith database.\n"
                "Try keywords like:\n"
                "sabr (patience)\n"
                "ibtila / bala (trial)\n"
                "fitnah\n"
                "hardship"
            ),
            metadata={"type": "hadith_miss", "attempted_query": query},
        )

    def _parse_reference(self, reference: str | None) -> str | None:
        if not reference:
            return None
        parts = reference.split("URL:", 1)
        if len(parts) == 2:
            left = parts[0].strip()
            right = parts[1].strip()
            return f"{left} | URL: {right}" if left else f"URL: {right}"
        return reference.strip()

    def _format_hadith_preview(self, hit: HadithHit) -> RouteResult:
        number = hit.hadith_number or "?"
        lines = [f"{hit.book_name or 'Hadith'} — {number}", ""]
        lines.extend([self._preview(hit.english), ""])
        parsed_reference = self._parse_reference(hit.reference)
        if parsed_reference:
            lines.append(parsed_reference)
        if hit.grading:
            lines.append(f"Grading: {hit.grading}")
        lines.extend(["", 'Say "full" or "expand" for full narration.'])
        self.state.last_item = {"provider": "hadith", "id": hit.id}
        return RouteResult(
            text="\n".join(lines),
            metadata={"type": "hadith_preview", "provider": "hadith", "id": str(hit.id)},
        )

    def _format_dua_preview(self, hit: DuaHit) -> RouteResult:
        description = self._preview(hit.description)
        lines = [hit.title or "Dua", ""]
        if description:
            lines.extend([description, ""])
        preview_lines = hit.arabic_lines[:4]
        lines.extend(preview_lines)
        if len(hit.arabic_lines) > 4:
            lines.append("...")
        lines.extend(["", 'Say "full" or "expand" for full supplication.'])
        self.state.last_item = {"provider": "dua", "id": hit.id}
        return RouteResult(
            text="\n".join(lines),
            metadata={"type": "dua_preview", "provider": "dua", "id": str(hit.id)},
        )

    def _format_kb(self, hit: KnowledgeHit) -> RouteResult:
        top = hit
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

    def _handle_expand(self) -> RouteResult:
        if not self.state.last_item:
            return RouteResult(
                text="I don’t have a recent item to expand.",
                metadata={"type": "expand_missing"},
            )
        provider = str(self.state.last_item.get("provider"))
        item_id = self.state.last_item.get("id")
        if provider == "hadith":
            hit = self.hadith_provider.get_by_id(int(item_id))
            if not hit:
                return RouteResult(text="I don’t have a recent item to expand.", metadata={"type": "expand_missing"})
            lines = [f"{hit.book_name or 'Hadith'} — {hit.hadith_number or '?'}", ""]
            if hit.arabic:
                lines.extend([hit.arabic, ""])
            if hit.english:
                lines.extend([hit.english, ""])
            parsed_reference = self._parse_reference(hit.reference)
            if parsed_reference:
                lines.append(parsed_reference)
            if hit.grading:
                lines.append(f"Grading: {hit.grading}")
            return RouteResult(
                text="\n".join(lines),
                metadata={"type": "hadith_full", "provider": "hadith", "id": str(hit.id)},
            )
        if provider == "dua":
            hit = self.dua_provider.get_by_id(str(item_id))
            if not hit:
                return RouteResult(text="I don’t have a recent item to expand.", metadata={"type": "expand_missing"})
            lines = [hit.title, "", *hit.arabic_lines]
            if hit.translation_lines:
                lines.extend(["", *hit.translation_lines])
            elif hit.translation:
                lines.extend(["", *hit.translation.splitlines()])
            return RouteResult(
                text="\n".join(lines),
                metadata={"type": "dua_full", "provider": "dua", "id": str(hit.id)},
            )
        return RouteResult(text="I don’t have a recent item to expand.", metadata={"type": "expand_missing"})

    def route(self, user_text: str) -> RouteResult:
        cleaned = user_text.strip()
        if self._is_expand_intent(cleaned):
            return self._handle_expand()

        self.state.last_item = None

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

        emotion_category = detect_emotion_category(user_text)
        explicit_hadith = self._is_explicit_hadith_intent(user_text)
        explicit_dua = self._is_explicit_dua_intent(user_text)
        emotional_islamic = emotion_category in _ISLAMIC_COMFORT_EMOTIONS
        islamic = self._is_islamic_query(user_text) or emotional_islamic
        emotional_prefer_dua = bool(emotional_islamic and not explicit_hadith and not explicit_dua)

        if explicit_hadith:
            hadith_hits = self.hadith_provider.search(user_text, limit=self.state.settings.PROVIDER_TOP_K)
            if hadith_hits:
                return self._with_comfort(self._format_hadith_preview(hadith_hits[0]), emotion_category)
            return self._with_comfort_miss(self._format_hadith_miss(user_text), emotion_category)

        if explicit_dua:
            dua_hits = self.dua_provider.search(user_text, limit=self.state.settings.PROVIDER_TOP_K)
            if dua_hits:
                return self._with_comfort(self._format_dua_preview(dua_hits[0]), emotion_category)
            return self._with_comfort_miss(
                RouteResult(
                    text="I couldn't find a relevant dua in local sources.",
                    metadata={"type": "dua_miss"},
                ),
                emotion_category,
            )

        if islamic:
            kb_hits = self.kb.search(user_text, limit=self.state.settings.PROVIDER_TOP_K)
            if kb_hits and kb_hits[0].score >= self.state.settings.kb_strong_match_threshold and not emotional_prefer_dua:
                return self._with_comfort(self._format_kb(kb_hits[0]), emotion_category)

            hadith_hits = self.hadith_provider.search(user_text, limit=self.state.settings.PROVIDER_TOP_K)
            dua_hits = self.dua_provider.search(user_text, limit=self.state.settings.PROVIDER_TOP_K)

            best_hadith: HadithHit | None = hadith_hits[0] if hadith_hits else None
            best_dua: DuaHit | None = dua_hits[0] if dua_hits else None

            if emotional_islamic:
                if best_dua:
                    return self._with_comfort(self._format_dua_preview(best_dua), emotion_category)
                if kb_hits:
                    return self._with_comfort(self._format_kb(kb_hits[0]), emotion_category)
                if best_hadith:
                    return self._with_comfort(self._format_hadith_preview(best_hadith), emotion_category)
            else:
                if best_hadith and best_dua:
                    if best_hadith.score >= best_dua.score:
                        return self._format_hadith_preview(best_hadith)
                    return self._format_dua_preview(best_dua)
                if best_hadith:
                    return self._format_hadith_preview(best_hadith)
                if best_dua:
                    return self._format_dua_preview(best_dua)

            return self._with_comfort_miss(
                RouteResult(
                    text="I couldn't find a relevant Islamic reference in the local knowledge sources.",
                    metadata={"type": "kb_miss"},
                ),
                emotion_category,
            )

        hits = self.kb.search(user_text)
        if hits:
            top = max(hits, key=lambda hit: hit.score)
            if top.score >= self.state.settings.kb_strong_match_threshold:
                return self._format_kb(top)

        hints = MODE_HINTS[self.state.mode]
        mode_hint = f"tone={hints['tone']}; verbosity={hints['verbosity']}"
        llm_text, llm_meta = self.llm.generate(user_text, mode_hint=mode_hint)

        if safety_result.message:
            llm_text = f"{safety_result.message} {llm_text}".strip()

        self.state.remember(f"user:{user_text}")
        self.state.remember(f"assistant:{llm_text}")
        return RouteResult(text=llm_text, metadata={"type": "llm", **llm_meta})
