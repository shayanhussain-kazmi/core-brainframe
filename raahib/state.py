from __future__ import annotations

from dataclasses import dataclass, field

from raahib.config import DEFAULT_SETTINGS, Settings
from raahib.modes import Mode


@dataclass(slots=True)
class AppState:
    mode: Mode = Mode.GENERAL
    short_term_history: list[str] = field(default_factory=list)
    capabilities: dict[str, bool] = field(
        default_factory=lambda: DEFAULT_SETTINGS.capabilities.copy()
    )
    settings: Settings = field(default_factory=lambda: DEFAULT_SETTINGS)

    def remember(self, message: str) -> None:
        self.short_term_history.append(message)
        overflow = len(self.short_term_history) - self.settings.max_short_term_memory
        if overflow > 0:
            del self.short_term_history[:overflow]
