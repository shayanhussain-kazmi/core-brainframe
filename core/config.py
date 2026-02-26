from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """Application settings for local core behavior."""

    data_dir: Path = Path(".core_data")
    kb_strong_match_threshold: float = 0.8
    max_short_term_memory: int = 20
    allowed_modes: tuple[str, ...] = (
        "general",
        "tutor",
        "focus",
        "health",
        "mood",
    )
    capabilities: dict[str, bool] = field(
        default_factory=lambda: {
            "commands": True,
            "safety": True,
            "knowledge": True,
            "cloud_llm": True,
        }
    )


DEFAULT_SETTINGS = Settings()
