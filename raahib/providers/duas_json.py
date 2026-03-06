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
    score: float


_SYNONYMS: dict[str, set[str]] = {
    "grief": {"sadness", "anxiety", "worry", "huzn", "ham", "despair"},
    "sadness": {"grief", "huzn", "ham", "worry", "despair"},
    "anxiety": {"worry", "fear", "panic"},
}


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w']+", text.lower()) if len(token) >= 2}


class DuaProvider:
    def __init__(self, json_path: str | None = None, tags_path: str | None = None) -> None:
        self.json_path = Path(json_path).expanduser() if json_path else None
        self.tags_path = Path(tags_path).expanduser() if tags_path else None
        self._duas: list[dict[str, object]] = []
        self._tags: dict[str, set[str]] = {}
        self._loaded = False

    @property
    def configured(self) -> bool:
        return self.json_path is not None and self.json_path.exists()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.configured:
            self._duas = []
            self._tags = {}
            return
        try:
            payload = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._duas = []
            self._tags = {}
            return
        if not isinstance(payload, list):
            self._duas = []
            self._tags = {}
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
                }
            )
        self._duas = parsed
        self._tags = self._load_tags()

    def _load_tags(self) -> dict[str, set[str]]:
        if not self.tags_path or not self.tags_path.exists():
            return {}
        try:
            payload = json.loads(self.tags_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        tags: dict[str, set[str]] = {}
        for key, value in payload.items():
            if isinstance(value, list):
                tags[str(key)] = {str(v).lower().strip() for v in value if str(v).strip()}
        return tags

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
        terms = [term.lower() for term in query.split() if term.strip() and len(term.strip()) >= 2]
        if not terms:
            return []
        query_tokens = _tokens(query)
        expanded_terms = set(query_tokens)
        for token in list(query_tokens):
            expanded_terms |= _SYNONYMS.get(token, set())

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
            tags = self._tags.get(str(dua["id"]), set())
            tag_overlap = len(query_tokens & tags)
            if matched_terms == 0 and tag_overlap == 0:
                continue
            score = matched_terms / max(len(expanded_terms), 1)
            if query.lower().strip() and query.lower().strip() in searchable:
                score = max(score, 0.95)
            if tag_overlap:
                score += 1.5 + (tag_overlap / max(len(query_tokens), 1))
            hits.append(
                DuaHit(
                    id=str(dua["id"]),
                    title=str(dua["title"]),
                    description=str(dua["description"]),
                    arabic_lines=list(dua["arabic_lines"]),
                    translation=str(dua.get("translation") or "") or None,
                    translation_lines=list(dua.get("translation_lines") or []),
                    score=score,
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

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
                    score=1.0,
                )
        return None
