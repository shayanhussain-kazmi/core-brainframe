from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class KnowledgeCard:
    id: int
    type: str
    title: str
    arabic: str | None
    translation_en: str | None
    explanation: str | None
    source_name: str
    reference: str
    auth_grade: str | None
    tags: str | None
    created_at: str


@dataclass(slots=True)
class KnowledgeHit:
    card: KnowledgeCard
    score: float


class KnowledgeBase:
    def __init__(self, db_path: str | Path = "./data/raahib_kb.sqlite") -> None:
        self.db_path = Path(db_path)

    def _conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    arabic TEXT,
                    translation_en TEXT,
                    explanation TEXT,
                    source_name TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    auth_grade TEXT,
                    tags TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def seed_if_empty(self) -> None:
        self.init_db()
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM cards").fetchone()
            if row and row["c"] > 0:
                return

        for item in _SEED_CARDS:
            self.add_card(**item)

    def add_card(
        self,
        type: str,
        title: str,
        source_name: str,
        reference: str,
        arabic: str | None = None,
        translation_en: str | None = None,
        explanation: str | None = None,
        auth_grade: str | None = None,
        tags: str | None = None,
    ) -> KnowledgeCard:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO cards(type, title, arabic, translation_en, explanation, source_name, reference, auth_grade, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    type,
                    title,
                    arabic,
                    translation_en,
                    explanation,
                    source_name,
                    reference,
                    auth_grade,
                    tags,
                    created_at,
                ),
            )
            conn.commit()
            card_id = int(cursor.lastrowid)
        card = self.get_card(card_id)
        if card is None:
            raise RuntimeError("Inserted card could not be retrieved.")
        return card

    def get_card(self, card_id: int) -> KnowledgeCard | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return _row_to_card(row) if row else None

    def delete_card(self, card_id: int) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            conn.commit()
        return cursor.rowcount > 0

    def search(self, query: str, limit: int = 5) -> list[KnowledgeHit]:
        terms = [t.lower() for t in query.split() if t.strip()]
        if not terms:
            return []

        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM cards").fetchall()

        weights = {
            "title": 4,
            "tags": 3,
            "arabic": 2,
            "translation_en": 2,
            "explanation": 1,
            "source_name": 1,
            "reference": 1,
        }
        max_per_term = sum(weights.values())

        hits: list[KnowledgeHit] = []
        for row in rows:
            card = _row_to_card(row)
            score = 0.0
            for term in terms:
                if term in (card.title or "").lower():
                    score += weights["title"]
                if term in (card.tags or "").lower():
                    score += weights["tags"]
                if term in (card.arabic or "").lower():
                    score += weights["arabic"]
                if term in (card.translation_en or "").lower():
                    score += weights["translation_en"]
                if term in (card.explanation or "").lower():
                    score += weights["explanation"]
                if term in (card.source_name or "").lower():
                    score += weights["source_name"]
                if term in (card.reference or "").lower():
                    score += weights["reference"]
            normalized = min(1.0, score / (max_per_term * len(terms)))
            full_query = query.lower().strip()
            if full_query and full_query in (card.title or "").lower():
                normalized = max(normalized, 0.9)
            if normalized > 0:
                hits.append(KnowledgeHit(card=card, score=normalized))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def export_json(self, path: str | Path) -> Path:
        out_path = Path(path)
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM cards ORDER BY id").fetchall()
        payload = [dict(r) for r in rows]
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path


def _row_to_card(row: sqlite3.Row) -> KnowledgeCard:
    return KnowledgeCard(
        id=int(row["id"]),
        type=str(row["type"]),
        title=str(row["title"]),
        arabic=row["arabic"],
        translation_en=row["translation_en"],
        explanation=row["explanation"],
        source_name=str(row["source_name"]),
        reference=str(row["reference"]),
        auth_grade=row["auth_grade"],
        tags=row["tags"],
        created_at=str(row["created_at"]),
    )


_SEED_CARDS = [
    {
        "type": "quran",
        "title": "Tests are part of faith",
        "arabic": "أَحَسِبَ النَّاسُ أَنْ يُتْرَكُوا أَنْ يَقُولُوا آمَنَّا وَهُمْ لَا يُفْتَنُونَ",
        "translation_en": "Do people think they will be left to say, 'We believe' and they will not be tested?",
        "explanation": "Hardship is expected in a believer's path and does not mean abandonment.",
        "source_name": "Qur'an",
        "reference": "Q29:2",
        "auth_grade": None,
        "tags": "tests,sabr,faith",
    },
    {
        "type": "quran",
        "title": "Allah is with the patient",
        "arabic": "إِنَّ اللَّهَ مَعَ الصَّابِرِينَ",
        "translation_en": "Indeed, Allah is with the patient.",
        "explanation": "Patience is not passive; it is steadfast trust with action.",
        "source_name": "Qur'an",
        "reference": "Q2:153",
        "auth_grade": None,
        "tags": "patience,sabr,hope",
    },
    {
        "type": "quran",
        "title": "Ease follows hardship",
        "arabic": "فَإِنَّ مَعَ الْعُسْرِ يُسْرًا",
        "translation_en": "For indeed, with hardship comes ease.",
        "explanation": "Relief is promised alongside struggle.",
        "source_name": "Qur'an",
        "reference": "Q94:5",
        "auth_grade": None,
        "tags": "hope,hardship,ease",
    },
    {
        "type": "quran",
        "title": "Do not despair of Allah's mercy",
        "arabic": "لَا تَقْنَطُوا مِنْ رَحْمَةِ اللَّهِ",
        "translation_en": "Do not despair of the mercy of Allah.",
        "explanation": "Even after mistakes, repentance remains open.",
        "source_name": "Qur'an",
        "reference": "Q39:53",
        "auth_grade": None,
        "tags": "mercy,forgiveness,hope",
    },
    {
        "type": "quran",
        "title": "Remember Me and I will remember you",
        "arabic": "فَاذْكُرُونِي أَذْكُرْكُمْ",
        "translation_en": "So remember Me; I will remember you.",
        "explanation": "Dhikr reconnects the heart during stress.",
        "source_name": "Qur'an",
        "reference": "Q2:152",
        "auth_grade": None,
        "tags": "dhikr,anxiety,connection",
    },
    {
        "type": "dua",
        "title": "Dua for anxiety and grief",
        "arabic": "اللَّهُمَّ إِنِّي أَعُوذُ بِكَ مِنَ الْهَمِّ وَالْحَزَنِ",
        "translation_en": "O Allah, I seek refuge in You from anxiety and sorrow.",
        "explanation": "A concise supplication to calm the heart in emotional overwhelm.",
        "source_name": "Mafatih al-Jinan",
        "reference": "Daily Duas section",
        "auth_grade": "unknown",
        "tags": "dua,anxiety,sadness",
    },
    {
        "type": "dua",
        "title": "Dua of Prophet Yunus",
        "arabic": "لَا إِلَهَ إِلَّا أَنْتَ سُبْحَانَكَ إِنِّي كُنْتُ مِنَ الظَّالِمِينَ",
        "translation_en": "There is no god but You; glory be to You; indeed I was among the wrongdoers.",
        "explanation": "A repentance and relief dua recited in distress.",
        "source_name": "Qur'an",
        "reference": "Q21:87",
        "auth_grade": None,
        "tags": "dua,repentance,relief",
    },
    {
        "type": "dua",
        "title": "Dua for forgiveness",
        "arabic": "رَبِّ اغْفِرْ لِي وَارْحَمْنِي",
        "translation_en": "My Lord, forgive me and have mercy on me.",
        "explanation": "Simple frequent istighfar for daily mistakes.",
        "source_name": "Sahifa Sajjadiya",
        "reference": "Dua 31 (seeking forgiveness)",
        "auth_grade": "unknown",
        "tags": "dua,forgiveness,istighfar",
    },
    {
        "type": "dua",
        "title": "Dua for increase in knowledge",
        "arabic": "رَبِّ زِدْنِي عِلْمًا",
        "translation_en": "My Lord, increase me in knowledge.",
        "explanation": "A short prayer before study and learning.",
        "source_name": "Qur'an",
        "reference": "Q20:114",
        "auth_grade": None,
        "tags": "dua,study,knowledge",
    },
    {
        "type": "dua",
        "title": "Dua for good in this world and next",
        "arabic": "رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً وَفِي الْآخِرَةِ حَسَنَةً",
        "translation_en": "Our Lord, grant us good in this world and good in the Hereafter.",
        "explanation": "Balanced dua for worldly wellbeing and spiritual success.",
        "source_name": "Qur'an",
        "reference": "Q2:201",
        "auth_grade": None,
        "tags": "dua,wellbeing,akhirah",
    },
    {
        "type": "hadith",
        "title": "Patience at first strike",
        "translation_en": "Patience is at the first shock.",
        "explanation": "True sabr appears when pain first arrives.",
        "source_name": "Sahih al-Bukhari",
        "reference": "Book of Funerals, hadith 1283",
        "auth_grade": "sahih",
        "tags": "hadith,sabr,patience",
    },
    {
        "type": "hadith",
        "title": "Best among you in character",
        "translation_en": "The best of you are those best in character.",
        "explanation": "Akhlaq is central to Islamic excellence.",
        "source_name": "Sahih al-Bukhari",
        "reference": "Book of Virtues, hadith 3559",
        "auth_grade": "sahih",
        "tags": "hadith,akhlaq,character",
    },
    {
        "type": "hadith",
        "title": "Believer is mirror of believer",
        "translation_en": "A believer is the mirror of another believer.",
        "explanation": "Encourages sincere advice and gentle correction.",
        "source_name": "Al-Kafi",
        "reference": "v2, p166",
        "auth_grade": "unknown",
        "tags": "hadith,community,advice",
    },
    {
        "type": "hadith",
        "title": "Strong is one who controls anger",
        "translation_en": "The strong one is the one who controls himself when angry.",
        "explanation": "Inner discipline is a form of strength.",
        "source_name": "Sahih al-Bukhari",
        "reference": "Book of Manners, hadith 6114",
        "auth_grade": "sahih",
        "tags": "hadith,anger,self-control",
    },
    {
        "type": "hadith",
        "title": "Actions are by intentions",
        "translation_en": "Actions are only by intentions.",
        "explanation": "Intention shapes the value of deeds.",
        "source_name": "Sahih al-Bukhari",
        "reference": "Book of Revelation, hadith 1",
        "auth_grade": "sahih",
        "tags": "hadith,niyyah,intention",
    },
    {
        "type": "story",
        "title": "Prophet Yusuf and patience",
        "translation_en": "Yusuf stayed truthful through jealousy, prison, and hardship until Allah opened a way.",
        "explanation": "Kid-friendly educational summary about long-term patience and trust.",
        "source_name": "Educational summary",
        "reference": "summary",
        "auth_grade": "unknown",
        "tags": "story,yusuf,patience,kids",
    },
    {
        "type": "story",
        "title": "Prophet Musa faces fear",
        "translation_en": "Musa felt afraid but still obeyed Allah and stood for justice.",
        "explanation": "Kid-friendly educational summary about courage with faith.",
        "source_name": "Educational summary",
        "reference": "summary",
        "auth_grade": "unknown",
        "tags": "story,musa,courage,kids",
    },
    {
        "type": "story",
        "title": "Imam Ali and kindness",
        "translation_en": "Imam Ali is remembered for justice, mercy, and helping the poor quietly.",
        "explanation": "Kid-friendly educational summary focusing on service and humility.",
        "source_name": "Educational summary",
        "reference": "summary",
        "auth_grade": "unknown",
        "tags": "story,imam ali,kindness,kids",
    },
    {
        "type": "story",
        "title": "Karbala and moral courage",
        "translation_en": "Imam Husayn stood for truth and dignity despite overwhelming odds.",
        "explanation": "Kid-friendly educational summary about principles and sacrifice.",
        "source_name": "Educational summary",
        "reference": "summary",
        "auth_grade": "unknown",
        "tags": "story,karbala,husayn,courage",
    },
    {
        "type": "story",
        "title": "Prophet Nuh keeps calling to good",
        "translation_en": "Nuh continued inviting people with patience for many years.",
        "explanation": "Kid-friendly educational summary about consistency and hope.",
        "source_name": "Educational summary",
        "reference": "summary",
        "auth_grade": "unknown",
        "tags": "story,nuh,consistency,kids",
    },
    {
        "type": "fiqh_info",
        "title": "Not a fatwa notice",
        "translation_en": "This assistant provides educational information, not a binding fatwa.",
        "explanation": "For legal rulings, consult your marja and trusted scholars.",
        "source_name": "Raahib OS Safety",
        "reference": "template",
        "auth_grade": "unknown",
        "tags": "fiqh,marja,safety",
    },
    {
        "type": "emotional_guidance",
        "title": "Mental health scope notice",
        "translation_en": "Spiritual support does not replace clinical diagnosis or emergency care.",
        "explanation": "If symptoms are severe or persistent, seek qualified mental health support.",
        "source_name": "Raahib OS Safety",
        "reference": "template",
        "auth_grade": "unknown",
        "tags": "mental-health,safety,scope",
    },
    {
        "type": "quran",
        "title": "Hearts find rest in remembrance",
        "arabic": "أَلَا بِذِكْرِ اللَّهِ تَطْمَئِنُّ الْقُلُوبُ",
        "translation_en": "Surely, in the remembrance of Allah hearts find rest.",
        "explanation": "Dhikr is a source of calm and grounding.",
        "source_name": "Qur'an",
        "reference": "Q13:28",
        "auth_grade": None,
        "tags": "quran,dhikr,calm",
    },
    {
        "type": "hadith",
        "title": "Mercy to people",
        "translation_en": "Show mercy to those on earth and the One in heaven will show mercy to you.",
        "explanation": "Mercy toward creation attracts divine mercy.",
        "source_name": "Sunan al-Tirmidhi",
        "reference": "hadith 1924",
        "auth_grade": "hasan",
        "tags": "hadith,mercy,akhlaq",
    },
    {
        "type": "dua",
        "title": "Hasbunallahu wa ni'mal wakeel",
        "arabic": "حَسْبُنَا اللَّهُ وَنِعْمَ الْوَكِيلُ",
        "translation_en": "Allah is sufficient for us, and He is the best disposer of affairs.",
        "explanation": "Recited for trust during uncertainty.",
        "source_name": "Qur'an",
        "reference": "Q3:173",
        "auth_grade": None,
        "tags": "dua,tawakkul,trust",
    },
]
