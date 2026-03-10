from __future__ import annotations

EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sadness": ("sad", "sadness", "down", "low"),
    "grief": ("grief", "grieving", "mourning", "loss"),
    "anxiety": ("anxious", "anxiety", "worry", "worried", "panic", "nervous"),
    "hopelessness": ("hopeless", "hopelessness", "empty", "numb", "lost"),
    "fear": ("scared", "afraid", "fear", "frightened"),
    "guilt": ("guilty", "ashamed", "regret"),
    "happiness": ("happy", "joyful", "glad"),
    "gratitude": ("grateful", "thankful", "thankful to allah", "alhamdulillah"),
    "relief": ("relieved", "lighter", "better", "calm now"),
    "peace": ("peaceful", "at peace", "content"),
}


def detect_emotion_category(text: str) -> str | None:
    lowered = text.lower()
    for category, keywords in EMOTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return None


def comfort_intro_for(category: str, source_type: str) -> str:
    lead_ins = {
        "sadness": "I'm sorry you're feeling this way.",
        "grief": "That sounds heavy.",
        "anxiety": "I'm sorry this feels overwhelming.",
        "hopelessness": "I'm sorry you're carrying this weight.",
        "fear": "That sounds difficult.",
        "guilt": "I'm glad you asked.",
        "happiness": "Alhamdulillah, I'm glad to hear that.",
        "gratitude": "That is a blessing—may Allah increase it.",
        "relief": "It's good to hear your heart feels lighter.",
        "peace": "Alhamdulillah, may this peace remain with you.",
    }
    source_intros = {
        "dua_short": "Let’s hold onto a short supplication for some calm.",
        "dua": "Let’s hold onto a supplication for some calm.",
        "hadith_short": "Here is a short hadith that may steady the heart.",
        "hadith": "Here is a hadith that may steady the heart.",
        "verse_short": "Here is a short verse that may bring comfort and perspective.",
        "verse": "Here is a verse that may bring comfort and perspective.",
    }
    lead_in = lead_ins.get(category, "I'm sorry you're feeling this way.")
    source_intro = source_intros.get(source_type, source_intros["dua"])
    return f"{lead_in}\n{source_intro}"


def comfort_miss_intro() -> str:
    return "I'm sorry you're feeling this way. I don't yet have a saved source specifically for that."


def comfort_offer_for(category: str) -> str:
    offers = {
        "sadness": (
            "I'm sorry you're feeling this sadness. I'm here with you.\n"
            "Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort."
        ),
        "grief": (
            "That sounds really heavy. You don't have to carry it alone.\n"
            "Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort."
        ),
        "anxiety": (
            "I'm sorry this feels overwhelming right now. I'm with you.\n"
            "Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort."
        ),
        "hopelessness": (
            "I'm really sorry you're feeling this low. I'm here, and we can take it one step at a time.\n"
            "Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort."
        ),
        "fear": (
            "That sounds frightening, and I'm glad you shared it. I'm here with you.\n"
            "Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort."
        ),
        "guilt": (
            "Thank you for being honest about this. That takes courage.\n"
            "Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort."
        ),
        "happiness": (
            "Alhamdulillah, I'm glad to hear that.\n"
            "Would you like a short dua of gratitude, a verse, or a hadith to hold onto this moment?"
        ),
        "gratitude": (
            "That is a blessing—may Allah increase it.\n"
            "Would you like a short dua of gratitude, a verse, or a hadith to hold onto this moment?"
        ),
        "relief": (
            "It's good to hear your heart feels lighter.\n"
            "Would you like a short dua of gratitude, a verse, or a hadith to hold onto this moment?"
        ),
        "peace": (
            "Alhamdulillah, may this peace remain with you.\n"
            "Would you like a short dua of gratitude, a verse, or a hadith to hold onto this moment?"
        ),
    }
    return offers.get(
        category,
        "I'm here with you. Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort.",
    )


def supportive_talk_response() -> str:
    return "I'm here with you. You can tell me as much or as little as you want."
