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
    conn.execute(
        """
        INSERT INTO hadiths (id, book_name, hadith_number, arabic, english, grading, reference, full_content)
        VALUES (1, 'Sahih Muslim', '45', 'الدين النصيحة', 'Religion is sincere counsel', 'sahih', 'Muslim 45', 'Religion is sincere counsel. We said, To whom? He said: To Allah, His Book, His Messenger, and to the leaders and common folk.')
        """
    )
    conn.execute(
        "INSERT INTO hadiths_fts(rowid, arabic, english, full_content) VALUES (1, 'الدين النصيحة', 'Religion is sincere counsel', 'Religion is sincere counsel. We said, To whom? He said: To Allah, His Book, His Messenger, and to the leaders and common folk.')"
    )
    conn.commit()
    conn.close()


def _build_duas_json(path: Path) -> None:
    payload = [
        {
            "id": "dua-1",
            "english": "Dua for guidance",
            "description": "Ask Allah for straight path",
            "arabic": ["اهْدِنَا الصِّرَاطَ الْمُسْتَقِيمَ", "صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ"],
        }
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class CommandTests(unittest.TestCase):
    def test_mode_switch_command(self) -> None:
        state = AppState()
        parser = CommandParser()

        result = parser.parse("mode:tutor", state)

        self.assertTrue(result.handled)
        self.assertEqual(state.mode, Mode.TUTOR)

    def test_status_command(self) -> None:
        state = AppState()
        parser = CommandParser()

        result = parser.parse("status", state)

        self.assertTrue(result.handled)
        self.assertIn("mode=general", result.output)


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

    def test_kb_add_get_delete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "kb.sqlite"
            kb = KnowledgeBase(db_path)
            kb.init_db()

            card = kb.add_card(
                type="dua",
                title="Test Dua",
                source_name="Test Source",
                reference="T1",
                translation_en="A test dua",
                explanation="A test explanation",
            )
            fetched = kb.get_card(card.id)
            deleted = kb.delete_card(card.id)
            missing = kb.get_card(card.id)

            self.assertIsNotNone(fetched)
            self.assertTrue(deleted)
            self.assertIsNone(missing)


class RouterTests(unittest.TestCase):
    def test_router_chooses_command_over_llm(self) -> None:
        state = AppState()
        llm = StubLLM()
        router = Router(state=state, llm=llm)

        result = router.route("status")

        self.assertEqual(result.metadata["type"], "command")
        self.assertFalse(llm.called)

    def test_router_kb_strong_match_returns_kb(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            router = Router(state=state, llm=llm)

            result = router.route("Allah is with the patient")

            self.assertEqual(result.metadata["type"], "kb")
            self.assertIn("Source:", result.text)
            self.assertFalse(llm.called)

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
            self.assertIn("reliably sourced entry", result.text)
            self.assertFalse(llm.called)

    def test_router_provider_preview_and_full_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
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
            llm = StubLLM()
            kb = KnowledgeBase(settings.kb_db_path)
            kb.init_db()
            hadith = HadithProvider(settings.HADITH_DB_PATH)
            dua = DuaProvider(settings.DUAS_JSON_PATH)
            router = Router(state=state, kb=kb, llm=llm, hadith_provider=hadith, dua_provider=dua)

            preview = router.route("Share a hadith about sincere counsel")

            self.assertEqual(preview.metadata["type"], "hadith_preview")
            self.assertIn("Do you want the full narration", preview.text)
            self.assertEqual(state.last_item, {"provider": "hadith", "id": 1})

            full = router.route("full")

            self.assertEqual(full.metadata["type"], "hadith_full")
            self.assertIn("Religion is sincere counsel", full.text)

    def test_sources_command_shows_provider_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            router = Router(state=state, llm=StubLLM())

            result = router.route("sources")

            self.assertEqual(result.metadata["type"], "command")
            self.assertIn("hadith=off", result.text)
            self.assertIn("dua=off", result.text)

    def test_router_offline_fallback_when_llm_unavailable(self) -> None:
        state = AppState()
        router = Router(state=state, llm=CloudLLM())

        result = router.route("Tell me something useful")

        self.assertEqual(result.metadata["provider"], "offline")
        self.assertIn("Offline fallback", result.text)


if __name__ == "__main__":
    unittest.main()
