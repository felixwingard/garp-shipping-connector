#!/usr/bin/env python3
"""Öppna endast Bring Bulk-fönstret (som från appen).

Testar om terminaler laddas i det faktiska UI:t.
Kör på samma sätt som appen: python scripts/test_app_bring_window.py

På Windows: python scripts\\test_app_bring_window.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    from src.utils.config import load_config
    from src.tray.bring_bulk_window import BringBulkWindow

    config = load_config()
    if not config.get("bring"):
        print("Bring saknas i config.yaml. Avslutar.")
        return 1

    root = __import__("tkinter").Tk()
    root.withdraw()
    root.title("Test: Bring Bulk")

    win = BringBulkWindow(root, config, on_bulk_id_reserved=None)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
