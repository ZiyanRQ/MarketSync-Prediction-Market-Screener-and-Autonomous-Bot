"""MarketSync desktop arbitrage terminal — entry point.

Run from the repository root:   python app/main.py
Uses simulated (DEMO) market data only — no exchange credentials required.
"""

from __future__ import annotations

import os
import sys

# Allow `python app/main.py` from the repo root by making the package importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.storage.local_store import LocalStore  # noqa: E402
from app.ui import style  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MarketSync Terminal")
    app.setStyleSheet(style.QSS)

    store = LocalStore()
    window = MainWindow(store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
