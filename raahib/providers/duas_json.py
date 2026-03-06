from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DuaHit:
    id: str
    title: str
    description: str
    arabic_lines: list[str]
    translation: str | None
    translation_lines: list[str]
    tags: list[str]
    score: float


_TOPIC_SYNONYMS: dict[str, set[str]] = {
    "grief": {
        "grief",
        "sadness",
        "huzn",
        "ham",
        "sorrow",
        "depressed",
        "depression",
        "hopeless",
        "hopelessness",
    },
    "anxiety": {"anxiety", "anxious", "worry", "worried", "panic", "fear"},
}

_GENERAL_SYNONYMS: dict[str, set[str]] = {
    token: {alias for alias in synonyms if alias != token}
    for synonyms in _TOPIC_SYNONYMS.values()
    for token in synonyms
}


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w']+", text.lower()) if len(token) >= 2}


class DuaProvider:
    def __init__(self, json_path: str | None = None, tags_path: str | None = None) -> None:
        self.json_path = Path(json_path).expanduser() if json_path else None
        self.tags_path = Path(tags_path).expanduser() if tags_path else None
        self._duas: list[dict[str, object]] = []
        self._loaded = False

    @property
    def configured(self) -> bool:
        return self.json_path is not None and self.json_path.exists()

    @property
    def tags_configured(self) -> bool:
        return self.tags_path is not None and self.tags_path.exists()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.configured:
            self._duas = []
            return
        try:
            payload = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._duas = []
            return
        if not isinstance(payload, list):
            self._duas = []
            return
        parsed: list[dict[str, object]] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            arabic_lines = raw.get("arabic") or []
            if not isinstance(arabic_lines, list):
                arabic_lines = []
            parsed.append(
                {
                    "id": str(raw.get("id", "")),
                    "title": str(raw.get("english", "")).strip(),
                    "description": str(raw.get("description", "")).strip(),
                    "arabic_lines": [str(line).strip() for line in arabic_lines if str(line).strip()],
                    "translation": self._normalize_translation(raw.get("translation")),
                    "translation_lines": self._normalize_translation_lines(raw.get("translation_lines")),
                    "tags": set(),
                }
            )
        self._duas = parsed
        self._attach_tags(self._load_tags())

    def _load_tags(self) -> list[dict[str, object]]:
        if not self.tags_path or not self.tags_path.exists():
            return []
        try:
            payload = json.loads(self.tags_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _attach_tags(self, tags_payload: list[dict[str, object]]) -> None:
        if not tags_payload:
            return
        by_id = {str(dua["id"]): dua for dua in self._duas}
        by_title = {str(dua["title"]).strip().lower(): dua for dua in self._duas}
        for raw in tags_payload:
            raw_tags = raw.get("tags")
            if not isinstance(raw_tags, list):
                continue
            tags = {str(tag).strip().lower() for tag in raw_tags if str(tag).strip()}
            if not tags:
                continue

            target = None
            raw_id = raw.get("id")
            if raw_id is not None:
                target = by_id.get(str(raw_id))
            if target is None:
                raw_title = str(raw.get("english", "")).strip().lower()
                if raw_title:
                    target = by_title.get(raw_title)
            if target is None:
                continue
            target_tags = target.get("tags")
            if not isinstance(target_tags, set):
                target_tags = set()
                target["tags"] = target_tags
            target_tags.update(tags)

    def _normalize_translation(self, value: object) -> str | None:
        if isinstance(value, list):
            lines = [str(line).strip() for line in value if str(line).strip()]
            return "\n".join(lines) or None
        text = str(value or "").strip()
        return text or None

    def _normalize_translation_lines(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(line).strip() for line in value if str(line).strip()]

    def search(self, query: str, limit: int = 5) -> list[DuaHit]:
        self._ensure_loaded()
        if not query.strip():
            return []
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        expanded_terms = set(query_tokens)
        for token in list(query_tokens):
            expanded_terms |= _GENERAL_SYNONYMS.get(token, set())

        topic = self._extract_topic(query_tokens)
        topic_tags = _TOPIC_SYNONYMS.get(topic, set()) if topic else set()

        hits: list[DuaHit] = []
        for dua in self._duas:
            searchable = " ".join(
                [
                    str(dua["title"]),
                    str(dua["description"]),
                    " ".join(dua["arabic_lines"]),
                ]
            ).lower()
            searchable_tokens = _tokens(searchable)
            matched_terms = len(expanded_terms & searchable_tokens)
            tags = dua.get("tags") if isinstance(dua.get("tags"), set) else set()
            tag_overlap = len(query_tokens & tags)
            topic_overlap = len(topic_tags & tags)
            if matched_terms == 0 and tag_overlap == 0 and topic_overlap == 0:
                continue
            score = matched_terms / max(len(expanded_terms), 1)
            if query.lower().strip() and query.lower().strip() in searchable:
                score = max(score, 0.95)
            if tag_overlap:
                score += 1.5 + (tag_overlap / max(len(query_tokens), 1))
            if topic_overlap:
                score += 5.0 + (topic_overlap / max(len(topic_tags), 1))
            hits.append(
                DuaHit(
                    id=str(dua["id"]),
                    title=str(dua["title"]),
                    description=str(dua["description"]),
                    arabic_lines=list(dua["arabic_lines"]),
                    translation=str(dua.get("translation") or "") or None,
                    translation_lines=list(dua.get("translation_lines") or []),
                    tags=sorted(tags),
                    score=score,
                )
            )

        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:limit]

    def _extract_topic(self, query_tokens: set[str]) -> str | None:
        for topic, synonyms in _TOPIC_SYNONYMS.items():
            if query_tokens & synonyms:
                return topic
        return None

    def get_by_id(self, dua_id: str) -> DuaHit | None:
        self._ensure_loaded()
        for dua in self._duas:
            if str(dua["id"]) == str(dua_id):
                return DuaHit(
                    id=str(dua["id"]),
                    title=str(dua["title"]),
                    description=str(dua["description"]),
                    arabic_lines=list(dua["arabic_lines"]),
                    translation=str(dua.get("translation") or "") or None,
                    translation_lines=list(dua.get("translation_lines") or []),
                    tags=sorted(dua.get("tags") if isinstance(dua.get("tags"), set) else set()),
                    score=1.0,
                )
        return None
