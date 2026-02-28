from __future__ import annotations

import unittest

from raahib.commands import CommandParser
from raahib.llm import CloudLLM
from raahib.modes import Mode
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


class RouterTests(unittest.TestCase):
    def test_router_chooses_command_over_llm(self) -> None:
        state = AppState()
        llm = StubLLM()
        router = Router(state=state, llm=llm)

        result = router.route("status")

        self.assertEqual(result.metadata["type"], "command")
        self.assertFalse(llm.called)

    def test_router_offline_fallback_when_llm_unavailable(self) -> None:
        state = AppState()
        router = Router(state=state, llm=CloudLLM())

        result = router.route("Tell me something useful")

        self.assertEqual(result.metadata["provider"], "offline")
        self.assertIn("Offline fallback", result.text)


if __name__ == "__main__":
    unittest.main()
