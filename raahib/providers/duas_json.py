from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DuaHit:
    id: str
    title: str
    description: str
    arabic_lines: list[str]
    score: float


class DuaProvider:
    def __init__(self, json_path: str | None = None) -> None:
        self.json_path = Path(json_path).expanduser() if json_path else None
        self._duas: list[dict[str, object]] = []
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
                    "arabic_lines": [str(line) for line in arabic_lines],
                }
            )
        self._duas = parsed

    def search(self, query: str, limit: int = 5) -> list[DuaHit]:
        self._ensure_loaded()
        terms = [term.lower() for term in query.split() if term.strip() and len(term.strip()) >= 2]
        if not terms:
            return []

        hits: list[DuaHit] = []
        for dua in self._duas:
            searchable = " ".join(
                [
                    str(dua["title"]),
                    str(dua["description"]),
                    " ".join(dua["arabic_lines"]),
                ]
            ).lower()
            matched_terms = sum(1 for term in terms if term in searchable)
            if matched_terms == 0:
                continue
            score = matched_terms / len(terms)
            if query.lower().strip() and query.lower().strip() in searchable:
                score = max(score, 0.95)
            hits.append(
                DuaHit(
                    id=str(dua["id"]),
                    title=str(dua["title"]),
                    description=str(dua["description"]),
                    arabic_lines=list(dua["arabic_lines"]),
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
                    score=1.0,
                )
        return None
