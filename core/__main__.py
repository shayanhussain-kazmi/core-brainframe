from __future__ import annotations

import json

from core.router import Router
from core.state import AppState


def main() -> None:
    state = AppState()
    router = Router(state)
    print("core-brainframe REPL. Type 'quit' to exit.")
    while True:
        try:
            user_text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_text.lower() in {"quit", "exit"}:
            print("Goodbye.")
            break
        if not user_text:
            continue

        result = router.route(user_text)
        print(f"response: {result.text}")
        print("metadata:", json.dumps(result.metadata, sort_keys=True))


if __name__ == "__main__":
    main()
