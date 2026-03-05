from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(slots=True)
class HadithHit:
    id: int
    book_name: str | None
    hadith_number: str | None
    arabic: str | None
    english: str | None
    grading: str | None
    reference: str | None
    score: float


class HadithProvider:
    _SYNONYMS: dict[str, tuple[str, ...]] = {
        "patience": ("sabr", "steadfast", "endure", "endurance"),
        "test": ("trial", "ibtila", "bala", "fitnah", "hardship", "affliction"),
        "grief": ("huzn", "sorrow", "worry", "anxiety"),
    }

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path else None

    @property
    def configured(self) -> bool:
        return self.db_path is not None and self.db_path.exists()

    def _conn(self) -> sqlite3.Connection:
        if not self.configured:
            raise RuntimeError("Hadith provider is not configured")
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def search(self, query: str, limit: int = 5) -> list[HadithHit]:
        if not self.configured or not query.strip():
            return []

        query_terms = self._terms(query)
        passes: list[str] = []
        if query_terms:
            passes.append(" OR ".join(query_terms))
            expanded_terms = self._expand_terms(query_terms)
            expanded_query = " OR ".join(expanded_terms)
            if expanded_query and expanded_query != passes[0]:
                passes.append(expanded_query)
        else:
            passes.append(query)

        sql = """
            SELECT
                hadiths.id,
                hadiths.book_name,
                hadiths.hadith_number,
                hadiths.arabic,
                hadiths.english,
                hadiths.grading,
                hadiths.reference,
                bm25(hadiths_fts) AS rank
            FROM hadiths
            JOIN hadiths_fts ON hadiths_fts.rowid = hadiths.id
            WHERE hadiths.id IN (
                SELECT rowid FROM hadiths_fts
                WHERE hadiths_fts MATCH ?
                LIMIT ?
            )
            ORDER BY rank ASC
        """
        fallback_sql = """
            SELECT
                hadiths.id,
                hadiths.book_name,
                hadiths.hadith_number,
                hadiths.arabic,
                hadiths.english,
                hadiths.grading,
                hadiths.reference,
                0.0 AS rank
            FROM hadiths
            WHERE hadiths.id IN (
                SELECT rowid FROM hadiths_fts
                WHERE hadiths_fts MATCH ?
                LIMIT ?
            )
            ORDER BY hadiths.id ASC
        """

        try:
            with self._conn() as conn:
                rows = []
                for fts_query in passes[:2]:
                    try:
                        rows = conn.execute(sql, (fts_query, limit)).fetchall()
                    except sqlite3.OperationalError:
                        rows = conn.execute(fallback_sql, (fts_query, limit)).fetchall()
                    if rows:
                        break
        except (sqlite3.Error, RuntimeError):
            return []

        hits = [self._row_to_hit(r) for r in rows]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]

    def _terms(self, query: str) -> list[str]:
        return [t for t in re.findall(r"[\w']+", query.lower()) if len(t) >= 2]

    def _expand_terms(self, terms: list[str]) -> list[str]:
        expanded: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term not in seen:
                expanded.append(term)
                seen.add(term)
            for synonym in self._SYNONYMS.get(term, ()):
                if synonym not in seen:
                    expanded.append(synonym)
                    seen.add(synonym)
        return expanded

    def get_by_id(self, hadith_id: int) -> HadithHit | None:
        if not self.configured:
            return None
        sql = """
            SELECT id, book_name, hadith_number, arabic, english, grading, reference
            FROM hadiths
            WHERE id = ?
        """
        try:
            with self._conn() as conn:
                row = conn.execute(sql, (hadith_id,)).fetchone()
        except (sqlite3.Error, RuntimeError):
            return None
        if not row:
            return None
        row_data = dict(row)
        row_data["rank"] = 0.0
        return self._row_to_hit(row_data)

    def _row_to_hit(self, row: sqlite3.Row | dict[str, object]) -> HadithHit:
        rank = float(row["rank"] if row["rank"] is not None else 0.0)
        score = 1.0 / (1.0 + max(rank, 0.0)) if rank >= 0 else 1.0 + abs(rank)
        return HadithHit(
            id=int(row["id"]),
            book_name=row["book_name"],
            hadith_number=str(row["hadith_number"]) if row["hadith_number"] is not None else None,
            arabic=row["arabic"],
            english=row["english"],
            grading=row["grading"],
            reference=row["reference"],
            score=score,
        )
