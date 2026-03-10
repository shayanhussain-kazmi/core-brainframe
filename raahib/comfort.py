from __future__ import annotations

EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sadness": ("sad", "sadness", "down", "low"),
    "grief": ("grief", "grieving", "mourning", "loss"),
    "anxiety": ("anxious", "anxiety", "worry", "worried", "panic", "nervous"),
    "hopelessness": ("hopeless", "hopelessness", "empty", "numb", "lost"),
    "fear": ("scared", "afraid", "fear", "frightened"),
    "guilt": ("guilty", "ashamed", "regret"),
}


def detect_emotion_category(text: str) -> str | None:
    lowered = text.lower()
    for category, keywords in EMOTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return None


def comfort_intro_for(category: str) -> str:
    intros = {
        "sadness": "I'm sorry you're feeling this way.\nTake a breath—let's hold onto a short supplication.",
        "grief": "That sounds heavy.\nIn times of loss, a sincere supplication can steady the heart.",
        "anxiety": "I'm sorry this feels overwhelming.\nA brief supplication may help bring calm, insha'Allah.",
        "hopelessness": "I'm sorry you're carrying this weight.\nWhen the heart feels empty, a supplication can restore direction.",
        "fear": "That sounds difficult.\nWhen fear rises, a grounded supplication can bring steadiness.",
        "guilt": "I'm glad you asked.\nA sincere supplication for forgiveness is a strong place to begin.",
    }
    return intros.get(category, "I'm sorry you're feeling this way.")


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
    }
    return offers.get(
        category,
        "I'm here with you. Would you like to tell me what is weighing on your heart? I can also share a dua, a Qur'an verse, or a short hadith for comfort.",
    )


def supportive_talk_response() -> str:
    return "I'm here with you. You can tell me as much or as little as you want."
