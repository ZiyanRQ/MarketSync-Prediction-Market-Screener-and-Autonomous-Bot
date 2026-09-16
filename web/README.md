# MarketSync — web preview

A browser preview of the desktop terminal, so the project can be looked at from a
link instead of cloned and installed.

**The detection engine here is the project's real Python**, not a JavaScript
imitation. `MockProvider` generates the markets, `ArbitrageEngine` derives the
opportunities and accumulates their lifetime history, and `calculations.py` does
the depth-aware hedge maths — all running as CPython compiled to WebAssembly via
[Pyodide](https://pyodide.org/). Only the UI is rewritten, because PySide6 draws
native OS windows and cannot run in a browser.

```
browser
  ├── index.html / styles.css / app.js     the UI (draws only)
  └── Pyodide (CPython → WebAssembly)
        ├── app/models, app/providers, app/utils, app/services   ← copied from app/
        └── webapp.py                                            ← glue, written for the web
```

## Build and run locally

```bash
python web/build.py
python -m http.server 8765 --directory web
```

Then open <http://localhost:8765>. It must be served over http — opening
`index.html` from disk will not work, because Pyodide and the module loader both
use `fetch`.

## How `web/py/` gets there

`web/build.py` copies the Qt-free half of `app/` into `web/py/`. It never
modifies `app/`. Re-run it after changing any of those modules:

```bash
python web/build.py
```

`web/py/` is **generated but committed**, because GitHub Pages serves committed
files. Treat it as build output: edit `app/`, then rebuild.

The build refuses to run if `tests/test_no_qt_imports.py` fails. That test is
what makes this safe — a `PySide6` import added to `models/`, `providers/`,
`utils/` or one of the four pure services would break the browser build, so the
boundary is enforced rather than left to discipline.

## What this preview does and does not have

**Has:** the screener with live sorting and filtering, multi-select risk presets
(the union behaviour of the desktop `RiskEngine`), the opportunity inspector with
quality breakdown and edge-history sparkline, the depth-aware stake simulator,
and the dual-venue order-book ladder.

**Does not have:** the paper-trading bot dashboard, analytics, alerts, API-usage
panel, command palette, dock rearranging and window detaching, and persistence.
`QSettings` and SQLite have no browser equivalent here, so nothing is saved
between visits.

## One piece of duplicated logic

`WebTerminal._passes` in `webapp.py` mirrors `RiskEngine._passes_profile`. It is
the only logic copied rather than imported, because `RiskEngine` is a `QObject`
and cannot load under Pyodide.

The clean fix is to move that predicate onto `RiskProfile` in `app/models/`, so
the desktop engine and this module call the same code. That is a change to
`app/`, so it is flagged here rather than made silently.

## Deploying to GitHub Pages

Pages' *deploy from a branch* option only offers `/` or `/docs`, and this site
lives in `/web` — so it is published by
[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) instead.

One-time setup: **Settings → Pages → Source → GitHub Actions**. After that, any
push to `main` touching `web/`, `app/` or `tests/` redeploys automatically.

The workflow runs the Qt-boundary test, rebuilds `web/py/`, and fails if the
committed copy is stale — so `app/` and the published bundle cannot quietly drift
apart.
