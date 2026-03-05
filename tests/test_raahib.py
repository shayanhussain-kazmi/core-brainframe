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
from raahib.providers import DuaHit, DuaProvider, HadithHit, HadithProvider
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


class StubHadithProvider:
    configured = True

    def search(self, query: str, limit: int = 5) -> list[HadithHit]:
        return [
            HadithHit(
                id=9,
                book_name="Sahih Muslim",
                hadith_number="9",
                arabic="النصيحة",
                english="Patience brings relief",
                grading="sahih",
                reference="Muslim 9",
                score=0.2,
            )
        ]

    def get_by_id(self, hadith_id: int) -> HadithHit | None:
        return self.search("", 1)[0]


class StubDuaProvider:
    configured = True

    def search(self, query: str, limit: int = 5) -> list[DuaHit]:
        return [
            DuaHit(
                id="d-1",
                title="Dua with higher score",
                description="desc",
                arabic_lines=["line 1", "line 2"],
                translation=None,
                translation_lines=[],
                score=0.99,
            )
        ]

    def get_by_id(self, dua_id: str) -> DuaHit | None:
        return self.search("", 1)[0]


class StubHadithMissProvider:
    configured = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[HadithHit]:
        self.calls.append(query)
        return []

    def get_by_id(self, hadith_id: int) -> HadithHit | None:
        return None


class StubDuaHadithKisaProvider:
    configured = True

    def search(self, query: str, limit: int = 5) -> list[DuaHit]:
        return [
            DuaHit(
                id="d-kisa",
                title="Hadith Kisa",
                description="Ahlul Bayt gathering.",
                arabic_lines=["line1", "line2"],
                translation=None,
                translation_lines=[],
                score=0.99,
            )
        ]

    def get_by_id(self, dua_id: str) -> DuaHit | None:
        return self.search("", 1)[0]


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
            "translation": "Guide us on the straight path",
            "arabic": [
                "اهْدِنَا الصِّرَاطَ الْمُسْتَقِيمَ",
                "صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ",
                "غَيْرِ الْمَغْضُوبِ عَلَيْهِمْ",
                "وَلَا الضَّالِّينَ",
                "آمِينَ",
            ],
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


class HadithProviderTests(unittest.TestCase):
    def test_synonym_expansion_second_pass_finds_results(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            hadith_path = Path(td) / "raah_e_bahisht.db"
            conn = sqlite3.connect(hadith_path)
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
                VALUES (1, 'Sahih Muslim', '1', '', 'Sabr during hardship brings reward', 'sahih', 'Muslim 1', 'Sabr during hardship brings reward')
                """
            )
            conn.execute(
                "INSERT INTO hadiths_fts(rowid, arabic, english, full_content) VALUES (1, '', 'Sabr during hardship brings reward', 'Sabr during hardship brings reward')"
            )
            conn.commit()
            conn.close()

            provider = HadithProvider(str(hadith_path))
            hits = provider.search("patience")

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].id, 1)


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

    def test_hadith_keyword_prefers_hadith_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=StubLLM(),
                hadith_provider=StubHadithProvider(),
                dua_provider=StubDuaProvider(),
            )

            result = router.route("Hadith about patience")

            self.assertEqual(result.metadata["type"], "hadith_preview")
            self.assertEqual(result.metadata["provider"], "hadith")

    def test_explicit_hadith_intent_no_fallback_to_dua(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            hadith = StubHadithMissProvider()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=StubLLM(),
                hadith_provider=hadith,
                dua_provider=StubDuaHadithKisaProvider(),
            )

            result = router.route("Hadith about patience")

            self.assertEqual(result.metadata["type"], "hadith_miss")
            self.assertEqual(result.metadata["attempted_query"], "Hadith about patience")
            self.assertIn("couldn't find a hadith match", result.text)


    def test_router_provider_preview_and_expand_flow(self) -> None:
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
            self.assertEqual(preview.metadata["provider"], "hadith")
            self.assertIn("Do you want the full narration", preview.text)
            self.assertEqual(state.last_item, {"provider": "hadith", "id": 1})

            full = router.route("expand")

            self.assertEqual(full.metadata["type"], "hadith_full")
            self.assertEqual(full.metadata["provider"], "hadith")
            self.assertIn("Religion is sincere counsel", full.text)
            self.assertFalse(llm.called)
            self.assertEqual(state.last_item, {"provider": "hadith", "id": 1})

    def test_dua_preview_is_limited_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            kb_path = td_path / "kb.sqlite"
            duas_path = td_path / "duas.json"
            _build_duas_json(duas_path)
            settings = Settings(data_dir=td_path, kb_db_path=kb_path, DUAS_JSON_PATH=str(duas_path))
            state = AppState(settings=settings)
            router = Router(state=state, kb=KnowledgeBase(settings.kb_db_path), llm=StubLLM(), dua_provider=DuaProvider(settings.DUAS_JSON_PATH))

            preview = router.route("dua for guidance")

            self.assertEqual(preview.metadata["type"], "dua_preview")
            self.assertEqual(preview.metadata["provider"], "dua")
            self.assertLessEqual(preview.text.count("\n"), 9)
            self.assertIn("…", preview.text)

    def test_last_item_cleared_on_new_non_expand_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            kb_path = td_path / "kb.sqlite"
            hadith_path = td_path / "raah_e_bahisht.db"
            _build_hadith_db(hadith_path)
            settings = Settings(data_dir=td_path, kb_db_path=kb_path, HADITH_DB_PATH=str(hadith_path))
            state = AppState(settings=settings)
            llm = StubLLM()
            router = Router(state=state, kb=KnowledgeBase(settings.kb_db_path), llm=llm, hadith_provider=HadithProvider(settings.HADITH_DB_PATH))

            preview = router.route("hadith about sincere counsel")
            self.assertEqual(preview.metadata["type"], "hadith_preview")
            self.assertIsNotNone(state.last_item)

            non_expand = router.route("Tell me something useful")
            self.assertEqual(non_expand.metadata["type"], "llm")
            self.assertIsNone(state.last_item)

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
