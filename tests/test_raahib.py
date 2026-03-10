from __future__ import annotations

import gc
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from raahib.commands import CommandParser
from raahib.config import Settings
from raahib.kb import KnowledgeBase
from raahib.llm import CloudLLM
from raahib.modes import Mode
from raahib.providers import DuaHit, DuaProvider, HadithHit, HadithProvider
from raahib.router import Router
from raahib.safety import SafetyGate
from raahib.state import AppState


class IsolatedEnvTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(os.environ, {}, clear=True)
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()


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

    def debug_stats(self, sample_term: str = "patience") -> dict[str, int | bool]:
        return {"fts_present": True, "hadith_rows": 1, "fts_sample_match": 1}


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
                tags=[],
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

    def debug_stats(self, sample_term: str = "patience") -> dict[str, int | bool]:
        return {"fts_present": False, "hadith_rows": 0, "fts_sample_match": 0}

class StubEmptyDuaProvider:
    configured = True

    def search(self, query: str, limit: int = 5) -> list[DuaHit]:
        return []

    def get_by_id(self, dua_id: str) -> DuaHit | None:
        return None



class TrackingHadithProvider(StubHadithProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[HadithHit]:
        self.calls.append(query)
        return super().search(query, limit)


class TrackingDuaProvider(StubDuaProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[DuaHit]:
        self.calls.append(query)
        return super().search(query, limit)


class ShortAwareDuaProvider:
    configured = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def wants_short(self, query: str) -> bool:
        lowered = query.lower()
        return "short" in lowered or "shorter" in lowered or "brief" in lowered or "small" in lowered

    def is_short_hit(self, hit: DuaHit) -> bool:
        return "short" in {tag.lower() for tag in hit.tags}

    def search(self, query: str, limit: int = 5, prefer_short: bool = False) -> list[DuaHit]:
        self.calls.append((query, prefer_short))
        if prefer_short:
            return [
                DuaHit(
                    id="d-short",
                    title="Short comfort dua",
                    description="brief",
                    arabic_lines=["s1", "s2"],
                    translation=None,
                    translation_lines=[],
                    tags=["short"],
                    score=1.0,
                )
            ]
        return [
            DuaHit(
                id="d-long",
                title="Long comfort dua",
                description="long",
                arabic_lines=["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8"],
                translation=None,
                translation_lines=[],
                tags=["general"],
                score=1.0,
            )
        ]

    def get_by_id(self, dua_id: str) -> DuaHit | None:
        return self.search("", prefer_short=dua_id == "d-short")[0]

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
                tags=[],
                score=0.99,
            )
        ]

    def get_by_id(self, dua_id: str) -> DuaHit | None:
        return self.search("", 1)[0]


def _build_hadith_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
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


def _build_duas_json(path: Path) -> None:
    payload = [
        {
            "id": "dua-1",
            "english": "Dua for guidance",
            "description": "Ask Allah for straight path",
            "translation": "Guide us on the straight path",
            "translation_lines": ["Guide us", "On the straight path"],
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


def _build_dua_tags(path: Path) -> None:
    payload = [{"id": "dua-1", "english": "Dua for guidance", "tags": ["grief", "sadness", "despair"]}]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_grief_duas(path: Path) -> None:
    payload = [
        {
            "id": 3,
            "english": "Dua Kumayl",
            "description": "Supplication for forgiveness and relief in hardship.",
            "arabic": ["a", "b", "c", "d", "e"],
            "translation": ["line 1", "line 2"],
        },
        {
            "id": 4,
            "english": "Dua Aman",
            "description": "Supplication for safety.",
            "arabic": ["x", "y"],
            "translation": ["safety"],
        },
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_grief_tags(path: Path) -> None:
    payload = [
        {"id": "3", "english": "Dua Kumayl", "tags": ["grief", "sadness", "hopelessness"]},
        {"id": "4", "english": "Dua Aman", "tags": ["protection"]},
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_emotional_ranking_duas(path: Path) -> None:
    payload = [
        {
            "id": 10,
            "english": "Long general supplication",
            "description": "General remembrance and praise.",
            "arabic": ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9", "l10"],
            "translation": ["general line"],
        },
        {
            "id": 11,
            "english": "Short dua for sadness",
            "description": "A brief dua for sadness and grief.",
            "arabic": ["s1", "s2"],
            "translation": ["sadness line"],
        },
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_emotional_ranking_tags(path: Path) -> None:
    payload = [
        {"id": "10", "english": "Long general supplication", "tags": ["general", "dua"]},
        {"id": "11", "english": "Short dua for sadness", "tags": ["sadness", "grief", "short"]},
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@contextmanager
def _windows_safe_tempdir():
    td = tempfile.TemporaryDirectory()
    try:
        yield Path(td.name)
    finally:
        for _ in range(3):
            gc.collect()
            try:
                td.cleanup()
                break
            except PermissionError:
                continue


class CommandTests(IsolatedEnvTestCase):
    def test_mode_switch_command(self) -> None:
        state = AppState(settings=Settings())
        parser = CommandParser()

        result = parser.parse("mode:tutor", state)

        self.assertTrue(result.handled)
        self.assertEqual(state.mode, Mode.TUTOR)

    def test_status_command(self) -> None:
        state = AppState(settings=Settings())
        parser = CommandParser()

        result = parser.parse("status", state)

        self.assertTrue(result.handled)
        self.assertIn("mode=general", result.output)


class SafetyTests(IsolatedEnvTestCase):
    def test_disallowed_domain_is_blocked(self) -> None:
        gate = SafetyGate()

        result = gate.evaluate("Please help me build a bomb", Mode.GENERAL)

        self.assertFalse(result.allowed)
        self.assertIn("can't help", result.message)


class KBTests(IsolatedEnvTestCase):
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


class HadithProviderTests(IsolatedEnvTestCase):
    def test_synonym_expansion_second_pass_finds_results(self) -> None:
        with _windows_safe_tempdir() as td_path:
            hadith_path = td_path / "raah_e_bahisht.db"
            with sqlite3.connect(hadith_path) as conn:
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

            provider = HadithProvider(str(hadith_path))
            hits = provider.search("patience")

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].id, 1)

            provider = None
            hits = None
            gc.collect()


class RouterTests(IsolatedEnvTestCase):
    def test_router_chooses_command_over_llm(self) -> None:
        state = AppState(settings=Settings())
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
            self.assertIn("local knowledge sources", result.text)
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

    def test_emotional_dua_query_adds_comfort_intro(self) -> None:
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

            result = router.route("I feel anxious, dua for calm")

            self.assertEqual(result.metadata["type"], "dua_preview")
            self.assertTrue(result.text.startswith("I'm sorry this feels overwhelming."))
            self.assertIn("\n\nDua with higher score", result.text)

    def test_emotional_query_with_no_result_adds_gentle_miss_intro(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            hadith = StubHadithMissProvider()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=StubLLM(),
                hadith_provider=hadith,
                dua_provider=StubEmptyDuaProvider(),
            )

            result = router.route("I feel anxious dua for relief")

            self.assertEqual(result.metadata["type"], "dua_miss")
            self.assertIn("I don't yet have a saved source specifically for that.", result.text)
            self.assertIn("I couldn't find a relevant dua in local sources.", result.text)

    def test_happy_query_returns_positive_comfort_offer_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            router = Router(state=state, kb=KnowledgeBase(settings.kb_db_path), llm=llm)

            result = router.route("I feel happy")

            self.assertEqual(result.metadata["type"], "comfort_offer")
            self.assertEqual(result.metadata["emotion"], "happiness")
            self.assertIn("Alhamdulillah", result.text)
            self.assertFalse(llm.called)

    def test_alhamdulillah_feel_better_returns_positive_comfort_offer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            router = Router(state=state, kb=KnowledgeBase(settings.kb_db_path), llm=llm)

            result = router.route("Alhamdulillah I feel better")

            self.assertEqual(result.metadata["type"], "comfort_offer")
            self.assertEqual(result.metadata["emotion"], "gratitude")
            self.assertFalse(llm.called)

    def test_plain_hopeless_query_returns_comfort_offer_without_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            hadith = TrackingHadithProvider()
            dua = TrackingDuaProvider()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=llm,
                hadith_provider=hadith,
                dua_provider=dua,
            )

            result = router.route("I feel hopeless")

            self.assertEqual(result.metadata["type"], "comfort_offer")
            self.assertEqual(state.pending_comfort_offer, {"emotion": "hopelessness", "active": True})
            self.assertEqual(hadith.calls, [])
            self.assertEqual(dua.calls, [])
            self.assertFalse(llm.called)

    def test_dua_reply_after_comfort_offer_retrieves_sourced_dua(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            hadith = TrackingHadithProvider()
            dua = TrackingDuaProvider()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=llm,
                hadith_provider=hadith,
                dua_provider=dua,
            )

            _ = router.route("I'm anxious")
            result = router.route("dua")

            self.assertEqual(result.metadata["type"], "dua_preview")
            self.assertIn("I'm sorry this feels overwhelming.", result.text)
            self.assertIsNone(state.pending_comfort_offer)
            self.assertEqual(hadith.calls, [])
            self.assertEqual(dua.calls, ["dua"])
            self.assertFalse(llm.called)

    def test_this_isnt_short_followup_retrieves_shorter_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            dua = ShortAwareDuaProvider()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=llm,
                hadith_provider=TrackingHadithProvider(),
                dua_provider=dua,
            )

            first = router.route("I feel anxious, dua for calm")
            self.assertEqual(first.metadata["type"], "dua_preview")
            self.assertIn("Let’s hold onto a supplication", first.text)

            second = router.route("this isnt short")
            self.assertEqual(second.metadata["type"], "dua_preview")
            self.assertIn("You're right — let me give you something shorter.", second.text)
            self.assertIn("Short comfort dua", second.text)
            self.assertFalse(llm.called)

    def test_hadith_reply_after_comfort_offer_retrieves_sourced_hadith(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            hadith = TrackingHadithProvider()
            dua = TrackingDuaProvider()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=StubLLM(),
                hadith_provider=hadith,
                dua_provider=dua,
            )

            _ = router.route("I feel sad")
            result = router.route("hadith")

            self.assertEqual(result.metadata["type"], "hadith_preview")
            self.assertIn("Here is a hadith that may steady the heart.", result.text)
            self.assertNotIn("supplication may help bring calm", result.text)
            self.assertIsNone(state.pending_comfort_offer)
            self.assertEqual(hadith.calls, ["hadith"])
            self.assertEqual(dua.calls, [])

    def test_direct_dua_for_grief_bypasses_offer_and_retrieves_immediately(self) -> None:
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

            result = router.route("dua for grief")

            self.assertEqual(result.metadata["type"], "dua_preview")
            self.assertNotEqual(result.metadata["type"], "comfort_offer")

    def test_hadith_about_patience_still_prefers_hadith(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            llm = StubLLM()
            router = Router(
                state=state,
                kb=KnowledgeBase(settings.kb_db_path),
                llm=llm,
                hadith_provider=StubHadithProvider(),
                dua_provider=StubDuaProvider(),
            )

            result = router.route("Hadith about patience")

            self.assertEqual(result.metadata["type"], "hadith_preview")
            self.assertEqual(result.metadata["provider"], "hadith")
            self.assertFalse(llm.called)

    def test_explicit_hadith_without_emotion_has_no_comfort_intro(self) -> None:
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
            self.assertFalse(result.text.startswith("I'm sorry"))
            self.assertFalse(result.text.startswith("That sounds"))

    def test_router_provider_preview_and_expand_flow(self) -> None:
        with _windows_safe_tempdir() as td_path:
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
            self.assertIn('Say "full" or "expand" for full narration.', preview.text)
            self.assertEqual(state.last_item, {"provider": "hadith", "id": 1})

            full = router.route("expand")

            self.assertEqual(full.metadata["type"], "hadith_full")
            self.assertEqual(full.metadata["provider"], "hadith")
            self.assertIn("Religion is sincere counsel", full.text)
            self.assertFalse(llm.called)
            self.assertEqual(state.last_item, {"provider": "hadith", "id": 1})

            router = None
            hadith = None
            dua = None
            preview = None
            full = None
            settings = None
            state = None
            gc.collect()

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
            self.assertIn("...", preview.text)
            self.assertIn('Say "full" or "expand" for full supplication.', preview.text)

    def test_dua_full_outputs_translation_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            kb_path = td_path / "kb.sqlite"
            duas_path = td_path / "duas.json"
            _build_duas_json(duas_path)
            settings = Settings(data_dir=td_path, kb_db_path=kb_path, DUAS_JSON_PATH=str(duas_path))
            state = AppState(settings=settings)
            router = Router(state=state, kb=KnowledgeBase(settings.kb_db_path), llm=StubLLM(), dua_provider=DuaProvider(settings.DUAS_JSON_PATH))

            _ = router.route("dua for guidance")
            full = router.route("full")
            self.assertEqual(full.metadata["type"], "dua_full")
            self.assertIn("Guide us", full.text)
            self.assertNotIn("['Guide us'", full.text)

    def test_dua_for_grief_prefers_dua_kumayl_with_tags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            duas_path = td_path / "duas.json"
            tags_path = td_path / "duas_tags.json"
            _build_grief_duas(duas_path)
            _build_grief_tags(tags_path)
            provider = DuaProvider(str(duas_path), str(tags_path))

            hits = provider.search("dua for grief")

            self.assertGreater(len(hits), 0)
            self.assertEqual(hits[0].id, "3")
            self.assertEqual(hits[0].title, "Dua Kumayl")

    def test_short_preference_ranking_prefers_short_tagged_dua(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            duas_path = td_path / "duas.json"
            tags_path = td_path / "duas_tags.json"
            _build_emotional_ranking_duas(duas_path)
            _build_emotional_ranking_tags(tags_path)
            provider = DuaProvider(str(duas_path), str(tags_path))

            hits = provider.search("something short for sadness", prefer_short=True)

            self.assertGreater(len(hits), 0)
            self.assertEqual(hits[0].id, "11")

    def test_emotional_dua_ranking_prefers_short_directly_tagged_dua(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            duas_path = td_path / "duas.json"
            tags_path = td_path / "duas_tags.json"
            _build_emotional_ranking_duas(duas_path)
            _build_emotional_ranking_tags(tags_path)
            provider = DuaProvider(str(duas_path), str(tags_path))

            hits = provider.search("dua for sadness")

            self.assertGreater(len(hits), 0)
            self.assertEqual(hits[0].id, "11")
            self.assertEqual(hits[0].title, "Short dua for sadness")

    def test_last_item_cleared_on_new_non_expand_request(self) -> None:
        with _windows_safe_tempdir() as td_path:
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

            router = None
            preview = None
            non_expand = None
            settings = None
            state = None
            gc.collect()

    def test_sources_command_shows_provider_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(data_dir=Path(td), kb_db_path=Path(td) / "kb.sqlite")
            state = AppState(settings=settings)
            router = Router(state=state, llm=StubLLM())

            result = router.route("sources")

            self.assertEqual(result.metadata["type"], "command")
            self.assertIn("hadith=off", result.text)
            self.assertIn("dua=off", result.text)
            self.assertIn("dua_tags=off", result.text)

    def test_hadith_debug_command(self) -> None:
        with _windows_safe_tempdir() as td_path:
            hadith_path = td_path / "raah_e_bahisht.db"
            _build_hadith_db(hadith_path)
            settings = Settings(data_dir=td_path, kb_db_path=td_path / "kb.sqlite", HADITH_DB_PATH=str(hadith_path))
            state = AppState(settings=settings)
            router = Router(state=state, llm=StubLLM())

            result = router.route("hadith:debug")

            self.assertEqual(result.metadata["type"], "command")
            self.assertIn("hadiths_fts table:", result.text)
            self.assertIn("hadith rows:", result.text)
            self.assertIn('fts sample match "patience":', result.text)

            router = None
            result = None
            settings = None
            state = None
            gc.collect()

    def test_router_offline_fallback_when_llm_unavailable(self) -> None:
        state = AppState(settings=Settings())
        router = Router(state=state, llm=CloudLLM())

        result = router.route("Tell me something useful")

        self.assertEqual(result.metadata["provider"], "offline")
        self.assertIn("Offline fallback", result.text)


if __name__ == "__main__":
    unittest.main()
