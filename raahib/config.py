from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """Application settings for local Raahib OS behavior."""

    data_dir: Path = Path("./data")
    kb_db_path: Path = Path("./data/raahib_kb.sqlite")
    HADITH_DB_PATH: str | None = None
    DUAS_JSON_PATH: str | None = None
    MAX_PREVIEW_CHARS: int = 240
    PROVIDER_TOP_K: int = 5
    KB_STRONG_MATCH_THRESHOLD: float = 0.72
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

    def __post_init__(self) -> None:
        self.HADITH_DB_PATH = self.HADITH_DB_PATH or os.getenv("RAAHIB_HADITH_DB_PATH")
        self.DUAS_JSON_PATH = self.DUAS_JSON_PATH or os.getenv("RAAHIB_DUAS_JSON_PATH")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.kb_db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def kb_strong_match_threshold(self) -> float:
        return self.KB_STRONG_MATCH_THRESHOLD


DEFAULT_SETTINGS = Settings()
