from __future__ import annotations

from dataclasses import dataclass

from raahib.modes import Mode


CRISIS_KEYWORDS = {
    "suicide",
    "kill myself",
    "end my life",
    "self-harm",
    "hurt myself",
}

DISALLOWED_REQUEST_KEYWORDS = {
    "build a bomb",
    "make explosives",
    "bypass law enforcement",
}

HEALTH_DIAGNOSIS_TERMS = {"diagnose", "diagnosis", "what disease", "medical certainty"}


@dataclass(slots=True)
class SafetyResult:
    allowed: bool
    message: str = ""
    metadata: dict[str, str] | None = None


class SafetyGate:
    def evaluate(self, text: str, mode: Mode) -> SafetyResult:
        lowered = text.lower()

        if any(keyword in lowered for keyword in DISALLOWED_REQUEST_KEYWORDS):
            return SafetyResult(
                allowed=False,
                message="I can't help with dangerous or illegal requests.",
                metadata={"type": "safety", "reason": "disallowed_domain"},
            )

        if mode is Mode.MOOD and any(keyword in lowered for keyword in CRISIS_KEYWORDS):
            return SafetyResult(
                allowed=False,
                message=(
                    "I care about your safety. If you're in immediate danger, call local emergency services now. "
                    "You can also contact a crisis hotline in your country right away."
                ),
                metadata={"type": "safety", "reason": "crisis_guidance"},
            )

        if mode is Mode.HEALTH and any(term in lowered for term in HEALTH_DIAGNOSIS_TERMS):
            return SafetyResult(
                allowed=True,
                message="I can share general health information, but this is not a diagnosis.",
                metadata={"type": "safety", "reason": "health_disclaimer"},
            )

        return SafetyResult(allowed=True)
