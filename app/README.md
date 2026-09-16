# MarketSync Terminal

A desktop arbitrage workstation for Betfair ↔ Matchbook analysis, built with
**PySide6 + pyqtgraph**. Runs on **simulated (DEMO) data** — no exchange
credentials required.

## Run

```bash
pip install -r app/requirements.txt
python app/main.py
```

The status strip and toolbar make the data source explicit: **BETFAIR: DEMO ·
MATCHBOOK: DEMO · DATA SOURCE: SIMULATED**. Nothing here connects to a live
exchange.

## Architecture

```
UI (ui/)  →  Services (services/)  →  Provider interface (providers/base_provider)
                                          └── MockProvider (now)
                                          └── Betfair / Matchbook (stubs, future)
```

- **UI never fetches.** Only `MarketDataService` calls a provider, on a timer.
  Changing risk, filters, the simulator or the watchlist recomputes locally.
- **models/** dataclasses + enums · **utils/** pure maths & formatting ·
  **storage/** QSettings + SQLite persistence.

## Key features

- Dense `QAbstractTableModel` screener with sortable/filterable columns, risk
  colouring, context menus and saved layout.
- **Multi-select** risk presets (SAFE / MODERATE / RISKY, editable) — toggle any
  combination; the screener shows the union, and the most conservative enabled
  preset drives the buffer. All local, no refetch.
- **Fully rearrangeable panels** — drag any dock (Inspector, Watchlist, Events,
  Simulations, Analytics, API Usage, Alerts) to any edge, float it, or tab it.
  The `PANELS` toolbar group and `View` menu show/hide them; `Workspace → Reset
  layout` restores the default.
- Depth-aware investment simulator (stakes walk the ladder), profit-vs-investment
  chart, quality score, lifetime sparkline and dual-exchange order-book ladder.
- **Bot Terminal** — a first-class dashboard for the autonomous paper-trading bot,
  usable **docked or popped out into its own window** (IDE-style detach/re-dock).
  - **Money model:** you set a **Deposit** (allocated capital); the bot trades a
    **min–max stake** band per trade, sized as fixed £, % of liquidity, or % of the
    deposit. **Balance = deposit + P&L**. Its ledger is separate from the manual
    simulator — no "bankroll vs capital" confusion.
  - **Saved presets:** Scalp, High-liquidity, Football low-risk, Conservative,
    Aggressive — apply one and tweak, or save your own.
  - **Tracking:** 12 metric tiles, a **drawdown gauge**, and charts for equity
    curve, per-trade P&L and edge taken; plus a live activity feed.
  - **Execution slippage:** a configurable slippage % makes some fills miss the
    theoretical edge (more in volatile markets), so a fraction of trades lose —
    giving the win-rate, drawdown gauge and per-trade chart realistic variation.
  - **Stops:** profit target, loss limit, staking budget, hard trade cap, and
    auto-halt when the deposit can't cover the minimum stake. Paper only.
  - **Access:** the **BOT TERMINAL** toolbar button, **Ctrl+B**, or the command
    palette — and it's the panel shown by default on the right.
- Paper trading with a persisted bankroll + trade history (SQLite), what-if
  strategy runs, preset comparison, local alerts, terminal event log, mock API
  usage dashboard + call inspector.

## Keyboard

`↑/↓` move selection · `Enter` open · `S` simulate trade · `W` watchlist ·
`Ctrl+K` command palette. Shortcuts are suppressed while typing in an input.

## Going live later

Implement `BetfairProvider` / `MatchbookProvider` against `BaseProvider` using the
request logic already in `src/betfair.py` and `src/matchbook.py`. No UI changes
needed — swap the provider passed to `MarketDataService`.
