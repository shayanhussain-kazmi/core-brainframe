from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


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
        "patience": ("sabr", "steadfast", "endurance"),
        "trial": ("ibtila", "bala", "hardship", "affliction"),
        "grief": ("sorrow", "anxiety", "huzn"),
        "test": ("fitnah", "trial"),
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
        if not query_terms:
            return []

        fts_primary = self._dedupe(query_terms)
        fts_expanded = self._expand_terms(query_terms)

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
            ORDER BY rank ASC, hadiths.id ASC
        """

        like_sql = """
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
            WHERE (
                lower(COALESCE(hadiths.english, '')) LIKE ? OR
                lower(COALESCE(hadiths.full_content, '')) LIKE ?
            )
            ORDER BY hadiths.id ASC
            LIMIT ?
        """

        rows: list[sqlite3.Row] = []
        try:
            with self._conn() as conn:
                rows = self._fts_query(conn, sql, fts_primary, limit)
                if not rows:
                    rows = self._fts_query(conn, sql, fts_expanded, limit)
                if not rows:
                    rows = self._like_fallback(conn, like_sql, fts_expanded, limit)
        except (sqlite3.Error, RuntimeError):
            return []

        hits = [self._row_to_hit(row) for row in rows]
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:limit]

    def _fts_query(
        self,
        conn: sqlite3.Connection,
        sql: str,
        terms: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        if not terms:
            return []
        fts_query = " OR ".join(terms)
        try:
            return conn.execute(sql, (fts_query, limit)).fetchall()
        except sqlite3.OperationalError:
            return []

    def _like_fallback(
        self,
        conn: sqlite3.Connection,
        like_sql: str,
        terms: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        for term in terms[:12]:
            pattern = f"%{term.lower()}%"
            for row in conn.execute(like_sql, (pattern, pattern, limit)).fetchall():
                if all(existing["id"] != row["id"] for existing in rows):
                    rows.append(row)
                if len(rows) >= limit:
                    return rows
        return rows

    def _terms(self, query: str) -> list[str]:
        return [token for token in re.findall(r"[\w']+", query.lower()) if len(token) >= 2]

    def _expand_terms(self, terms: list[str]) -> list[str]:
        expanded: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term not in seen:
                expanded.append(term)
                seen.add(term)
            for synonym in self._SYNONYMS.get(term, ()):  # deterministic order
                if synonym not in seen:
                    expanded.append(synonym)
                    seen.add(synonym)
        return expanded

    def _dedupe(self, terms: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term not in seen:
                out.append(term)
                seen.add(term)
        return out

    def debug_stats(self, sample_term: str = "patience") -> dict[str, int | bool]:
        if not self.configured:
            return {"fts_present": False, "hadith_rows": 0, "fts_sample_match": 0}
        try:
            with self._conn() as conn:
                table_row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hadiths_fts'"
                ).fetchone()
                hadith_rows = conn.execute("SELECT COUNT(*) AS c FROM hadiths").fetchone()
                fts_sample_match = 0
                if table_row:
                    try:
                        sample_row = conn.execute(
                            "SELECT COUNT(*) AS c FROM hadiths_fts WHERE hadiths_fts MATCH ?",
                            (sample_term,),
                        ).fetchone()
                        fts_sample_match = int(sample_row["c"]) if sample_row else 0
                    except sqlite3.OperationalError:
                        fts_sample_match = 0
        except (sqlite3.Error, RuntimeError):
            return {"fts_present": False, "hadith_rows": 0, "fts_sample_match": 0}

        return {
            "fts_present": bool(table_row),
            "hadith_rows": int(hadith_rows["c"]) if hadith_rows else 0,
            "fts_sample_match": fts_sample_match,
        }

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
