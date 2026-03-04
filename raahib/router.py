from __future__ import annotations

import re
from dataclasses import dataclass

from raahib.commands import CommandParser
from raahib.kb import KnowledgeBase, KnowledgeHit
from raahib.llm import CloudLLM
from raahib.modes import MODE_HINTS
from raahib.providers import DuaHit, DuaProvider, HadithHit, HadithProvider
from raahib.safety import SafetyGate
from raahib.state import AppState

_ISLAMIC_KEYWORDS = {
    "quran",
    "qur'an",
    "hadith",
    "dua",
    "du'a",
    "دعاء",
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
_EXPAND_WORDS = {"full", "more", "expand"}


@dataclass(slots=True)
class RouteResult:
    text: str
    metadata: dict[str, str]


class KnowledgeAggregator:
    def __init__(
        self,
        kb: KnowledgeBase,
        hadith_provider: HadithProvider,
        dua_provider: DuaProvider,
        top_k: int,
    ) -> None:
        self.kb = kb
        self.hadith_provider = hadith_provider
        self.dua_provider = dua_provider
        self.top_k = top_k

    def search(self, query: str) -> dict[str, list[object]]:
        return {
            "hadith": self.hadith_provider.search(query, limit=self.top_k)
            if self.hadith_provider.configured
            else [],
            "dua": self.dua_provider.search(query, limit=self.top_k) if self.dua_provider.configured else [],
            "kb": self.kb.search(query, limit=self.top_k),
        }


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
        self.dua_provider = dua_provider or DuaProvider(state.settings.DUAS_JSON_PATH)
        self.aggregator = KnowledgeAggregator(
            kb=self.kb,
            hadith_provider=self.hadith_provider,
            dua_provider=self.dua_provider,
            top_k=state.settings.PROVIDER_TOP_K,
        )

        self.commands = commands or CommandParser(self.kb, self.hadith_provider, self.dua_provider)
        self.safety = safety or SafetyGate()
        self.llm = llm or CloudLLM()

    def _is_islamic_query(self, user_text: str) -> bool:
        lowered = user_text.lower()
        return any(keyword in lowered for keyword in _ISLAMIC_KEYWORDS)

    def _intent_hint(self, user_text: str) -> str | None:
        lowered = user_text.lower()
        if "hadith" in lowered:
            return "hadith"
        if any(token in lowered for token in ("dua", "du'a", "دعاء")):
            return "dua"
        return None

    def _preview(self, text: str | None) -> str:
        if not text:
            return ""
        cleaned = " ".join(text.splitlines()).strip()
        max_chars = self.state.settings.MAX_PREVIEW_CHARS
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip() + "…"

    def _format_hadith_preview(self, hit: HadithHit) -> RouteResult:
        title = " — ".join(x for x in [hit.book_name, hit.hadith_number] if x)
        lines = [title or "Hadith"]
        if hit.english:
            lines.append(self._preview(hit.english))
        if hit.arabic and len(hit.arabic.strip()) < 120:
            lines.append(hit.arabic.strip())
        if hit.reference:
            lines.append(f"Reference: {hit.reference}")
        if hit.grading:
            lines.append(f"Grading: {hit.grading}")
        lines.append("Do you want the full narration? (say 'full' or 'more' or 'expand')")
        self.state.last_item = {"provider": "hadith", "id": hit.id}
        return RouteResult(
            text="\n".join(lines),
            metadata={"type": "hadith_preview", "provider": "hadith", "id": str(hit.id)},
        )

    def _dua_target(self, user_text: str) -> str | None:
        match = re.search(r"\bdua\s+for\s+(.+)$|\bdu['’]?a\s+for\s+(.+)$", user_text.lower())
        if not match:
            return None
        return (match.group(1) or match.group(2) or "").strip() or None

    def _format_dua_preview(self, hit: DuaHit, user_text: str) -> RouteResult:
        lines = [hit.title or "Dua"]
        if hit.description:
            lines.append(hit.description)
        preview_lines = hit.arabic_lines[:4]
        lines.extend(preview_lines)
        if len(hit.arabic_lines) > 4:
            lines.append("…")
        target = self._dua_target(user_text)
        if target and hit.score < 0.25:
            lines.append(
                f"I found a closest match saved, but I'm not fully confident it's specific to '{target}'."
            )
        lines.append("Do you want the full dua? (say 'full' or 'more' or 'expand')")
        self.state.last_item = {"provider": "dua", "id": hit.id}
        return RouteResult(
            text="\n".join(line for line in lines if line),
            metadata={"type": "dua_preview", "provider": "dua", "id": str(hit.id)},
        )

    def _format_kb(self, hit: KnowledgeHit) -> RouteResult:
        text_parts = [hit.card.title]
        if hit.card.arabic:
            text_parts.append(hit.card.arabic)
        if hit.card.translation_en:
            text_parts.append(hit.card.translation_en)
        if hit.card.explanation:
            text_parts.append(hit.card.explanation)
        text_parts.append(f"Source: {hit.card.source_name} ({hit.card.reference})")
        if hit.card.auth_grade:
            text_parts.append(f"Auth grade: {hit.card.auth_grade}")
        return RouteResult(
            text="\n".join(text_parts),
            metadata={
                "type": "kb",
                "card_id": str(hit.card.id),
                "score": f"{hit.score:.2f}",
                "source_name": hit.card.source_name,
                "reference": hit.card.reference,
                "auth_grade": hit.card.auth_grade or "",
            },
        )

    def _handle_expand(self) -> RouteResult:
        if not self.state.last_item:
            return RouteResult(text="I don’t have a recent item to expand.", metadata={"type": "expand_missing"})
        provider = str(self.state.last_item.get("provider"))
        item_id = self.state.last_item.get("id")

        if provider == "hadith":
            hit = self.hadith_provider.get_by_id(int(item_id))
            if not hit:
                return RouteResult(text="I don’t have a recent item to expand.", metadata={"type": "expand_missing"})
            lines = [" — ".join(x for x in [hit.book_name, hit.hadith_number] if x) or "Hadith"]
            if hit.arabic:
                lines.append(hit.arabic)
            if hit.english:
                lines.append(hit.english)
            if hit.reference:
                lines.append(f"Reference: {hit.reference}")
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
            lines = [hit.title]
            if hit.description:
                lines.append(hit.description)
            lines.extend(hit.arabic_lines[:200])
            if hit.translation:
                lines.append(hit.translation)
            lines.append(f"Reference: dua_id={hit.id}")
            return RouteResult(
                text="\n".join(line for line in lines if line),
                metadata={"type": "dua_full", "provider": "dua", "id": str(hit.id)},
            )

        return RouteResult(text="I don’t have a recent item to expand.", metadata={"type": "expand_missing"})

    def route(self, user_text: str) -> RouteResult:
        cleaned = user_text.strip()
        if cleaned.lower() in _EXPAND_WORDS:
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

        if self._is_islamic_query(user_text):
            merged = self.aggregator.search(user_text)
            hadith_hits: list[HadithHit] = merged["hadith"]  # type: ignore[assignment]
            dua_hits: list[DuaHit] = merged["dua"]  # type: ignore[assignment]
            kb_hits: list[KnowledgeHit] = merged["kb"]  # type: ignore[assignment]

            best_hadith = hadith_hits[0] if hadith_hits else None
            best_dua = dua_hits[0] if dua_hits else None
            best_kb = kb_hits[0] if kb_hits else None
            intent = self._intent_hint(user_text)

            if intent == "hadith" and best_hadith:
                return self._format_hadith_preview(best_hadith)
            if intent == "dua" and best_dua:
                return self._format_dua_preview(best_dua, user_text)

            provider_best_score = max(best_hadith.score if best_hadith else 0.0, best_dua.score if best_dua else 0.0)
            kb_score = best_kb.score if best_kb else 0.0

            if best_kb and kb_score >= self.state.settings.kb_strong_match_threshold and kb_score > (provider_best_score + 0.25):
                return self._format_kb(best_kb)
            if best_hadith and (not best_dua or best_hadith.score >= best_dua.score):
                return self._format_hadith_preview(best_hadith)
            if best_dua:
                return self._format_dua_preview(best_dua, user_text)
            if best_kb and kb_score >= self.state.settings.kb_strong_match_threshold:
                return self._format_kb(best_kb)

            return RouteResult(
                text="I don’t have a reliably sourced entry for that yet.",
                metadata={"type": "kb_miss"},
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
