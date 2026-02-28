from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class KnowledgeHit:
    source: str
    snippet: str
    score: float


class KnowledgeBase:
    """Placeholder KB implementation for future local retrieval."""

    def search(self, query: str) -> list[KnowledgeHit]:
        _ = query
        return []
