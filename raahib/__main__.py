from __future__ import annotations

import json

from raahib.router import Router
from raahib.state import AppState


def main() -> None:
    state = AppState()
    router = Router(state)
    hadith_on = "on" if router.hadith_provider.configured else "off"
    dua_on = "on" if router.dua_provider.configured else "off"
    tags_on = "on" if getattr(router.dua_provider, "tags_configured", False) else "off"
    print("Raahib OS REPL. Type 'quit' to exit.")
    print(f"providers: hadith={hadith_on}, dua={dua_on}, tags={tags_on}")
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
