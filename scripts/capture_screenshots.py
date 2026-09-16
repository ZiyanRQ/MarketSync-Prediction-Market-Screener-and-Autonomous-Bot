"""Capture screenshots of the real PySide6 terminal into assets/.

Runs the actual desktop app - same MainWindow, same widgets, same simulated
provider - lets it tick until the panels have data, then grabs each dock.

    python scripts/capture_screenshots.py

Isolation: the app is given a throwaway LocalStore pointing at a temp INI and a
temp SQLite file, so a capture run never reads or writes your real layout,
bankroll, watchlist, bot config or trade history. The window is also never
close()d, because MainWindow.closeEvent persists all of that on the way out.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings, Qt                      # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from app.storage import local_store                           # noqa: E402
from app.ui import style                                      # noqa: E402

OUT = ROOT / "assets"
SIZE = (1680, 1120)


class CaptureStore(local_store.LocalStore):
    """LocalStore backed by throwaway files instead of the user's real ones."""

    def __init__(self, scratch: Path) -> None:
        self.settings = QSettings(str(scratch / "capture.ini"),
                                  QSettings.Format.IniFormat)
        self.db_path = str(scratch / "capture.db")
        self._init_db()


def pump(app: QApplication, seconds: float) -> None:
    """Run the event loop for `seconds` so timers fire and widgets repaint."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def frame(window, bottom: int, right: int) -> None:
    """Size the docks so the panel being captured gets the room, not the log."""
    window.resizeDocks([window.log_dock], [bottom], Qt.Orientation.Vertical)
    window.resizeDocks([window.inspector_dock], [right], Qt.Orientation.Horizontal)


def grab(window, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{name}.png"
    window.grab().save(str(path))
    print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    app = QApplication(sys.argv)
    app.setApplicationName("MarketSync Terminal")
    app.setStyleSheet(style.QSS)

    scratch = Path(tempfile.mkdtemp(prefix="marketsync-capture-"))
    print(f"scratch store: {scratch}")

    from app.ui.main_window import MainWindow
    window = MainWindow(CaptureStore(scratch))
    window.resize(*SIZE)
    window.show()
    pump(app, 1.0)

    # Let the screener fill with opportunities.
    print("\nfilling screener...")
    pump(app, 6.0)

    # Select the top row so the inspector, ladder and charts have a subject.
    table = window.screener.table
    if table.model().rowCount():
        table.selectRow(0)
        table.setFocus()
        pump(app, 1.5)

    print("capturing:")
    window.inspector_dock.raise_()
    window.log_dock.raise_()
    frame(window, bottom=210, right=560)
    pump(app, 1.2)
    grab(window, "terminal-screener")

    # Bot terminal: shorten the cooldowns so a run's worth of paper trades
    # accumulates in seconds rather than minutes, then let it trade.
    print("\nrunning the paper bot...")
    window.bot.config.cooldown_s = 0.05
    window.bot.config.retrade_cooldown_s = 0.4
    window.bot.set_enabled(True)
    window.bot_dock.raise_()
    frame(window, bottom=210, right=700)   # the bot dashboard is the widest panel
    pump(app, 22.0)
    window.bot.set_enabled(False)
    pump(app, 0.5)
    grab(window, "terminal-bot")

    # Book a handful of paper trades and run a what-if, so the Simulations panel
    # has a trade history and an equity curve instead of empty placeholders.
    # These go to the throwaway store, never the real trade history.
    print("\nbooking paper trades...")
    booked = 0
    for opp in sorted(window.market_data.snapshot(),
                      key=lambda o: o.net_edge, reverse=True)[:6]:
        if opp.net_edge <= 0:
            continue
        window._paper_trade(opp, 250.0 + booked * 100)
        booked += 1
        pump(app, 0.25)
    window.simulator._run_whatif()
    print(f"  booked {booked} trades + ran what-if")
    pump(app, 1.0)

    # These three live in the bottom dock, so it becomes the subject. Each gets
    # the height its content actually needs - the analytics table is short, the
    # simulator and usage dashboards are not.
    window.inspector_dock.raise_()
    for dock, name, height in [
        (window.sim_dock, "terminal-simulator", 600),
        (window.analytics_dock, "terminal-analytics", 330),
        (window.api_dock, "terminal-api-usage", 560),
    ]:
        dock.raise_()
        frame(window, bottom=height, right=560)
        pump(app, 1.8)
        grab(window, name)

    # Quit WITHOUT close() - closeEvent would persist state to the store.
    print("\ndone (window not closed, so nothing was persisted)")
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
