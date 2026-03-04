from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from raahib.commands import CommandParser
from raahib.config import Settings
from raahib.kb import KnowledgeBase
from raahib.llm import CloudLLM
from raahib.modes import Mode
from raahib.providers import DuaProvider, HadithProvider
from raahib.router import Router
from raahib.safety import SafetyGate
from raahib.state import AppState


class StubLLM(CloudLLM):
    def __init__(self) -> None:
        super().__init__(model="stub")
        self.called = False

    def generate(self, prompt: str, mode_hint: str):
        self.called = True
        return "stub-response", {"provider": "stub"}


def _build_hadith_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE hadiths (
            id INTEGER PRIMARY KEY,
            book_name TEXT,
            hadith_number TEXT,
            arabic TEXT,
            english TEXT,
            grading TEXT,
            reference TEXT,
            full_content TEXT
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE hadiths_fts USING fts5(arabic, english, full_content, content='hadiths', content_rowid='id')"
    )
    rows = [
        (
            1,
            "Sahih Muslim",
            "45",
            "الدين النصيحة",
            "Religion is sincere counsel",
            "sahih",
            "Muslim 45",
            "Religion is sincere counsel. We said, To whom? He said: To Allah, His Book, His Messenger, and to the leaders and common folk.",
        ),
        (
            2,
            "Sahih Bukhari",
            "6110",
            "الصبر عند الصدمة الأولى",
            "Patience is at the first stroke of a calamity",
            "sahih",
            "Bukhari 6110",
            "Patience is at the first stroke of a calamity.",
        ),
    ]
    for row in rows:
        conn.execute(
            "INSERT INTO hadiths (id, book_name, hadith_number, arabic, english, grading, reference, full_content) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        conn.execute(
            "INSERT INTO hadiths_fts(rowid, arabic, english, full_content) VALUES (?, ?, ?, ?)",
            (row[0], row[3], row[4], row[7]),
        )
    conn.commit()
    conn.close()


def _build_duas_json(path: Path) -> None:
    payload = [
        {
            "id": "dua-1",
            "english": "Dua for grief and anxiety",
            "description": "Relief from sadness and worry",
            "arabic": [
                "اللهم إني أعوذ بك من الهم والحزن",
                "وأعوذ بك من العجز والكسل",
                "وأعوذ بك من الجبن والبخل",
                "وأعوذ بك من غلبة الدين وقهر الرجال",
                "زيادة سطر للاختبار",
            ],
        },
        {
            "id": "dua-2",
            "english": "Hadith Kisa",
            "description": "A beloved narration title that should not win hadith intent",
            "arabic": ["نص عربي طويل"],
        },
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class CommandTests(unittest.TestCase):
    def test_mode_switch_command(self) -> None:
        state = AppState()
        parser = CommandParser()

        result = parser.parse("mode:tutor", state)

        self.assertTrue(result.handled)
        self.assertEqual(state.mode, Mode.TUTOR)


class SafetyTests(unittest.TestCase):
    def test_disallowed_domain_is_blocked(self) -> None:
        gate = SafetyGate()

        result = gate.evaluate("Please help me build a bomb", Mode.GENERAL)

        self.assertFalse(result.allowed)
        self.assertIn("can't help", result.message)


class KBTests(unittest.TestCase):
    def test_kb_seed_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "kb.sqlite"
            kb = KnowledgeBase(db_path)
            kb.seed_if_empty()

            hits = kb.search("patience", limit=5)

            self.assertGreater(len(hits), 0)
            self.assertGreater(hits[0].score, 0)


class RouterTests(unittest.TestCase):
    def _build_router(self, td_path: Path, llm: StubLLM | None = None) -> tuple[Router, AppState, StubLLM]:
        kb_path = td_path / "kb.sqlite"
        hadith_path = td_path / "raah_e_bahisht.db"
        duas_path = td_path / "duas.json"
        _build_hadith_db(hadith_path)
        _build_duas_json(duas_path)

        settings = Settings(
            data_dir=td_path,
            kb_db_path=kb_path,
            HADITH_DB_PATH=str(hadith_path),
            DUAS_JSON_PATH=str(duas_path),
        )
        state = AppState(settings=settings)
        llm_stub = llm or StubLLM()
        kb = KnowledgeBase(settings.kb_db_path)
        kb.init_db()
        hadith = HadithProvider(settings.HADITH_DB_PATH)
        dua = DuaProvider(settings.DUAS_JSON_PATH)
        router = Router(state=state, kb=kb, llm=llm_stub, hadith_provider=hadith, dua_provider=dua)
        return router, state, llm_stub

    def test_hadith_keyword_prefers_hadith_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            router, state, _ = self._build_router(Path(td))
            preview = router.route("Hadith about patience")

            self.assertEqual(preview.metadata["type"], "hadith_preview")
            self.assertEqual(preview.metadata["provider"], "hadith")
            self.assertEqual(state.last_item, {"provider": "hadith", "id": 2})

    def test_dua_preview_limited_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            router, state, _ = self._build_router(Path(td))
            preview = router.route("dua for grief")

            self.assertEqual(preview.metadata["type"], "dua_preview")
            self.assertEqual(preview.metadata["provider"], "dua")
            self.assertIn("Do you want the full dua?", preview.text)
            self.assertEqual(state.last_item, {"provider": "dua", "id": "dua-1"})
            self.assertLessEqual(preview.text.count("\n"), 8)

    def test_expand_expands_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            router, _state, llm = self._build_router(Path(td))
            router.route("Hadith about patience")
            expanded = router.route("expand")

            self.assertEqual(expanded.metadata["type"], "hadith_full")
            self.assertFalse(llm.called)

    def test_last_item_clears_on_non_expand_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            router, state, _ = self._build_router(Path(td))
            router.route("Hadith about patience")
            self.assertIsNotNone(state.last_item)

            router.route("status")
            self.assertIsNone(state.last_item)

    def test_router_islamic_query_no_match_blocks_llm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            kb = KnowledgeBase(settings.kb_db_path)
            kb.init_db()
            router = Router(state=state, kb=kb, llm=llm)

            result = router.route("What is the fiqh ruling on lunar derivatives futures?")

            self.assertEqual(result.metadata["type"], "kb_miss")
            self.assertFalse(llm.called)


if __name__ == "__main__":
    unittest.main()
