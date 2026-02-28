from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    GENERAL = "general"
    TUTOR = "tutor"
    FOCUS = "focus"
    HEALTH = "health"
    MOOD = "mood"


MODE_HINTS: dict[Mode, dict[str, str]] = {
    Mode.GENERAL: {"tone": "neutral", "verbosity": "balanced"},
    Mode.TUTOR: {"tone": "patient and educational", "verbosity": "detailed"},
    Mode.FOCUS: {"tone": "direct and concise", "verbosity": "brief"},
    Mode.HEALTH: {"tone": "careful and non-diagnostic", "verbosity": "balanced"},
    Mode.MOOD: {"tone": "supportive and warm", "verbosity": "balanced"},
}


def parse_mode(value: str) -> Mode | None:
    try:
        return Mode(value.strip().lower())
    except ValueError:
        return None
