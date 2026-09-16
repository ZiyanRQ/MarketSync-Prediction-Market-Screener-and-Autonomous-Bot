# Architecture

How MarketSync is put together and why. The README covers *what* it does; this
covers the structure and the trade-offs behind it.

## Two halves, one idea

```
src/   live scanner        terminal, real exchange APIs, real credentials
app/   desktop terminal    PySide6 workstation, simulated data, no credentials
```

They are deliberately separate programs. The scanner's job is to be correct about
prices and edges against live venues; the terminal's job is to make opportunities
*legible* — depth, lifetime, quality, what a stake would actually return. Keeping
them apart means the UI can be explored freely without burning API quota or
risking a request to a live exchange, and the scanner stays a small dependency-light
script.

They share no code today. They do share a model of the world (venues, back/lay,
net edge after commission, SAFE/THIN/SKIP), and `app/providers/base_provider.py` is
the seam where they are intended to meet.

---

## `src/` — the live scanner

### Layering

```
cross_exchange.py     matching + detection + rating + reporting + poll loop
   ├── matchbook.py   Matchbook client (+ its own same-exchange scanner)
   └── betfair.py     Betfair client
```

Each exchange module owns exactly one thing: turning credentials into a session,
and turning a session into raw exchange data. Neither knows the other exists.
`cross_exchange.py` imports both, normalises their very different responses into
one shape, and does all the analysis on top.

The rule that keeps this clean: **exchange modules never analyse, and the
analysis module never speaks HTTP.**

### The client shape

Both clients follow the same skeleton, so a third venue is a known quantity:

```
login()      -> requests.Session with auth headers baked in
get/list...  -> one function per endpoint, returning parsed JSON
best_back()  -> the venue-specific "where are the odds" accessor
```

`login()` returning a pre-authenticated `Session` (rather than a token the caller
must remember to attach) means no call site can forget the auth header.

### Why the two clients look different

| | Matchbook | Betfair |
|---|---|---|
| Transport | REST, one URL per resource | JSON-RPC, **one** URL, method in the body |
| Prices | bundled into the events call (`include-prices`) | a **separate** `listMarketBook` call |
| Joining | none needed | catalogue + book joined on `marketId` + `selectionId` |
| Batching | `per-page` | manual chunks of 25 (`BOOK_CHUNK`) to dodge `TOO_MUCH_DATA` |

Betfair's uniform envelope is why `betfair.py` has a single `rpc()` helper that
every operation routes through — new endpoints are a one-line function. Matchbook
needs no such helper because each endpoint differs.

The price-fetching difference is the more consequential one: on Betfair, structure
and prices arrive separately and must be rejoined, and the price call is the
expensive, rate-limited one. That shapes the whole scan strategy below.

### Normalisation boundary

Every venue response is reduced to one common form before any analysis happens:

```python
market    = {venue, event, event_key, market, market_key, start, selections}
selection = {name, key, back, lay}
```

`*_key` fields are the normalised match keys, computed once at the boundary rather
than recomputed in every comparison. Past this line, no code knows or cares which
exchange a price came from — which is what makes adding a venue cheap.

### Matching: the actual hard problem

The exchanges share no identifiers and spell things differently, so markets are
reconciled by name in three widening steps:

1. **Normalise** — lowercase, strip punctuation, drop noise tokens (`fc`, `afc`,
   `sc`, `the`), apply a tiny token alias map (`utd`→`united`).
2. **Canonicalise market names** — an explicit alias table maps Matchbook's
   *Moneyline* and Betfair's *Match Odds* to one key.
3. **Fuzzy match** — `difflib.SequenceMatcher` with separate thresholds for
   events (`EVENT_MATCH` 0.80) and runners (`RUNNER_MATCH` 0.82).

Two deliberate choices here:

- **The alias tables are kept tiny.** Aggressive aliasing causes *false* matches,
  and a false match invents an arbitrage that does not exist — the worst possible
  failure for this program. Fuzzy matching handles the long tail; the tables only
  handle cases fuzzy matching provably cannot (*Moneyline* vs *Match Odds* share
  almost no characters).
- **`difflib` over a similarity library.** Standard library, no dependency, and
  good enough at this scale. If matching becomes the bottleneck it can be replaced
  behind `_ratio()` without touching anything else.

Because a mis-match is so costly, `preview` mode exists as a first-class feature:
it prints both venues' events and every near-miss similarity score, so "zero
arbs" can be diagnosed as *no shared events* versus *threshold too high* before
any number is trusted.

### Scan strategy: anchored on Matchbook

```
Matchbook events (with prices, one call)
  └─> fuzzy-match against Betfair's cheap event list (ids + names only)
        └─> fetch Betfair prices for the overlap ONLY
```

Betfair's price call is the expensive one, so it is never made for events that
cannot possibly match. Matchbook anchors because its prices arrive bundled — one
call gives both the event universe and its odds.

### Detection

Two detectors run over each matched pair:

- **`combined_back_arb`** — best back per runner across *both* venues; a complete
  book under 100% is a back-every-runner arb. Requires every runner priced, since
  one unbackable runner breaks the guarantee.
- **`back_lay_arbs`** — per selection, back where back-odds are highest, lay where
  lay-odds are lowest. Only cross-venue pairs qualify; within one venue back never
  exceeds lay.

### Being honest about the number

This is the part of the codebase most worth understanding. A naive scanner reports
the raw gap and looks brilliant. `_combined_net()` instead reports the
**worst-case guaranteed net**:

1. Size stakes by equal-profit dutching (proportional to `1/odds`).
2. For **each possible winner**, compute the net position *per exchange*.
3. Charge each venue's commission **only where that venue actually nets a win** —
   commission is on net market winnings, so a losing venue is not charged.
4. Report the **minimum** across all outcomes.

Steps 2–3 are why the per-venue split matters: charging commission on the gross
position, or on a blended rate, gives a materially wrong answer whenever the legs
are spread across venues at different rates.

`_back_lay_net()` does the equivalent for the hedged case, solving for the lay
stake that equalises both outcomes and charging each side's commission.

On top of that sits `SAFETY_BUFFER` — a cushion for prices moving between spotting
an arb and getting both legs matched — producing `SAFE` / `THIN` / `SKIP`.

### The poll loop reports transitions, not state

`scan_loop` prints each arb **once when it opens** and again **when it closes**.
`_arb_key()` deliberately excludes price, so an arb whose net drifts is still the
same arb. Printing every cycle would bury a genuinely new opportunity in repeats
of ones already seen.

Both loops recover from session expiry in place — Matchbook on HTTP 401, Betfair
on a `SESSION`-flavoured JSON-RPC error — because a scanner that dies after six
hours is not a scanner.

---

## `app/` — the desktop terminal

### Layering

```
ui/  ──> services/ ──> providers/BaseProvider
                            └── MockProvider        (active)
                            └── Betfair/Matchbook   (stubs)
models/   dataclasses + enums
utils/    pure maths, zero Qt
storage/  QSettings + SQLite
```

### The one rule

**Only `MarketDataService` fetches.** It owns the provider and the refresh timer;
on each tick it advances the provider, pulls a snapshot, rebuilds opportunities
and emits `updated`. Panels connect to that signal.

Everything the user does locally — changing risk profile, filtering, sorting,
running the simulator, adding to the watchlist — recomputes from the snapshot
already in memory and **never triggers a fetch**. With a metered, rate-limited API
on the other side, a UI where dragging a slider costs quota is unusable. Enforcing
this now means the live provider can be dropped in without re-auditing every
widget.

### Services

| Service | Responsibility |
|---|---|
| `MarketDataService` | the only fetcher; owns provider + clock |
| `ArbitrageEngine` | `Market` → `Opportunity`, **stateful** across ticks |
| `RiskEngine` | active profiles, buffer application, local filtering |
| `SimulationEngine` | manual paper trades + bankroll |
| `AutoTrader` | autonomous paper-trading bot, its own ledger |
| `CacheService` | TTL cache with hit/miss accounting |
| `ApiUsageTracker` | call records, budget, usage state |

`ArbitrageEngine` being **stateful** is the notable one: it holds one `Opportunity`
per market and updates it in place, so peak/low/average edge, price-change counts
and volatility accumulate over time. An edge that has held steady for two minutes
is a different proposition from one that just appeared, and only a stateful engine
can tell you which you are looking at.

### Risk profiles are a union

Multiple profiles can be enabled at once. An opportunity surfaces if it clears
**any** enabled profile, while the **most conservative** enabled profile drives the
buffer shown on each row. So you can watch SAFE and RISKY together without the
displayed cushion quietly becoming the loosest one.

### Depth-aware maths

`utils/calculations.py` is pure — no Qt, no I/O, unit-testable. Its model is a
per-selection cross-exchange hedge where **stakes walk the ladder**: larger stakes
fill at progressively worse prices, so ROI falls as capital rises. That is what
makes `max_executable()` and the profit-vs-investment curve meaningful rather than
decorative — a 4% edge on £20 of available liquidity is not a 4% edge on £2,000.

`simulate()` iterates to convergence because back stake and lay liability are
mutually dependent (the lay stake depends on filled odds, which depend on stakes).

### Persistence

`QSettings` for preferences, window/dock layout, and JSON blobs (risk presets,
watchlist, alert rules, bot config). **SQLite** for structured trade history. Every
read degrades gracefully — a missing or corrupt value falls back to a default
rather than failing to start.

---

## `web/` — the browser preview

A third surface, and the one that proves the layering was worth keeping honest.

PySide6 cannot run in a browser — Qt draws native OS windows, and a tab has none.
But **only the UI layer is Qt-bound**. All of `models/`, all of `providers/`
(including `MockProvider`), `utils/calculations.py` and four of the seven
services import no Qt at all. So the browser build runs that half as *real
Python*, under [Pyodide](https://pyodide.org/) (CPython compiled to WebAssembly),
and rewrites only the UI in HTML/JS:

```
browser
  ├── index.html / app.js          draws only
  └── Pyodide (CPython → wasm)
        ├── app/models, providers, utils, services   copied verbatim from app/
        └── webapp.py                               glue written for the web
```

`web/build.py` copies those modules into `web/py/`; it never writes to `app/`.
The maths, the detection and the lifetime tracking are therefore **not
reimplemented** — the page is running the same `net_edge` and the same stateful
`ArbitrageEngine` the desktop app imports.

Two consequences worth stating plainly:

- **The Qt boundary is now load-bearing in a third way.** It already made
  `utils/` unit-testable and let live providers slot in without touching the UI;
  now a stray `PySide6` import in a pure module would also break the browser
  build. `tests/test_no_qt_imports.py` enforces it, and both `web/build.py` and
  the Pages workflow refuse to ship if it fails.
- **`webapp.py` duplicates one predicate.** `RiskEngine._passes_profile` is six
  lines of filtering inside a `QObject`, so it cannot be imported. Moving it onto
  `RiskProfile` in `app/models/` would remove the copy; that is a change to
  `app/` and is left as a deliberate follow-up.

The preview carries the screener, inspector, stake simulator and order-book
ladder. The bot dashboard, analytics, alerts and persistence stay desktop-only.

## Commission is intentionally per-context

The two halves use different commission rates, and this is a design decision
rather than drift:

| | Betfair | Matchbook | Purpose |
|---|---|---|---|
| `src/cross_exchange.py` | **5%** | 2% | Conservative guard against live venues |
| `app/utils/calculations.py` | **2%** | 2% | Achievable rate, so the demo surfaces edges |

**The scanner errs high.** It is pointed at real exchanges, so it assumes
Betfair's headline 5% and only surfaces an edge that survives it. An arb that
clears a pessimistic rate clears the real one.

**The terminal errs realistic.** At 5% on both legs, almost nothing in a simulated
book qualifies and the screener sits empty — which makes the inspector, simulator,
bot and analytics impossible to demonstrate or develop against. 2% reflects what
arb-focused Betfair accounts commonly actually pay, and is overridable in Settings
to model the 5% base rate.

Both rates are also deliberately *adjustable* because commission is the variable
that decides whether a third venue is worth its API fee. Smarkets and Betdaq
charge for access, so the question "does this venue pay for itself at its
commission rate?" has to be answerable by changing a number, not by rewriting the
maths. Hard-coding one global rate would remove exactly the knob that decision
needs.

The commission **dicts are per-module** for the same reason — each context sets its
own rate. The net-edge formula underneath them *is* shared in substance:
`_back_lay_net()` and `calculations.net_edge()` are the same equation.

## Other differences between the halves

1. **The terminal has no under-round detector.** Its `Market` is *one selection*
   priced on both venues, so there is no notion of summing a book across a
   market's runners. It only does per-selection back/lay.
2. **Only the terminal is depth-aware.** The scanner reasons about best price and
   ignores the size available at it, so a flagged edge may be real but only good
   for a few pounds.

---

## Conventions

- Credentials come from a gitignored `.env` via `python-dotenv`, never literals,
  never in a URL.
- A `200 OK` is not treated as success — Matchbook, Betfair and JSON-RPC all report
  real failures inside the body, so every client checks the body too.
- Docstrings explain **why**, not what. The code says what it does.
- Money is never moved. Nothing places a real bet; the terminal's trading is paper
  only.
