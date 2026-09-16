# Roadmap

Where MarketSync is, what comes next, and what is knowingly unfinished.
Architecture and design reasoning live in [`architecture.md`](architecture.md).

## Done

- Matchbook client — session auth, sports, events, live back/lay ladders in one
  `include-prices` call.
- Same-exchange under-round scanner with a commission check.
- Continuous polling loops with automatic re-authentication on session expiry.
- Betfair client — interactive login, generic `rpc()` helper, catalogue + market
  book joined on `marketId`/`selectionId`, price calls chunked at 25 markets.
- Cross-exchange matching across venues with no shared IDs (normalisation,
  canonical market keys, fuzzy event/runner matching) plus a `preview` mode for
  diagnosing zero-match runs.
- Two detectors: combined-back under-round and per-selection back/lay cross arb.
- Worst-case net-of-commission sizing with per-venue commission attribution,
  safety buffer, and SAFE/THIN/SKIP rating via three risk presets.
- Poll loop that reports arbs as **transitions** (opened / closed), not as a
  per-cycle dump.
- Desktop terminal on simulated data: screener, inspector, order-book ladder,
  depth-aware simulator, analytics, alerts, paper-trading bot, local persistence.
- Browser preview (`web/`) running the real detection engine under Pyodide, with
  the Qt boundary enforced by `tests/test_no_qt_imports.py`.

---

## Next

### 1. Persist and alert on flagged opportunities

Today the scanner prints and forgets. Nothing survives a restart, so there is no
way to answer the question the whole project is really asking: **do real edges
actually occur, how often, how large, and for how long?**

- Write every opened/closed arb to SQLite with venues, prices, net edge and
  timestamps — the terminal already has a working SQLite pattern to copy.
- Record the *close* as well as the open, so arb **lifetime** is measurable.
- Alert (desktop notification, or a file/webhook) when a SAFE arb opens.

This is the highest-value next step: it converts the scanner from a live toy into
a dataset, and every decision below gets easier once that data exists.

### 2. Make the edge executable, not just true

The scanner reasons about best price and ignores the size available at it. A 4%
edge that is only good for £8 is not an opportunity.

- Read ladder depth on both venues (the data is already fetched).
- Report **max executable stake** alongside the edge.
- Port the depth-aware fill/hedge maths from `app/utils/calculations.py` — it
  already walks ladders correctly; it just lives on the wrong side of the project.
- Apply each venue's minimum stake as a hard filter.

### 3. Share the maths between the halves

The net-edge equation is currently written out twice — once as
`_back_lay_net()`, once as `calculations.net_edge()`. Same formula, two copies, so
a correction has to be made in both.

- Extract the hedge/net-edge maths into one module both halves import.
- **Keep the commission rates separate.** They differ on purpose — the scanner
  errs high against live venues, the terminal errs realistic so the demo surfaces
  edges, and the rate has to stay adjustable to evaluate whether a paid third
  venue pays for itself. See *Commission is intentionally per-context* in the
  architecture doc.
- Decide whether the terminal should gain an under-round detector, or whether that
  stays a scanner-only concept.

### 4. Wire the live providers into the terminal

`BetfairProvider` and `MatchbookProvider` are deliberate `NotImplementedError`
stubs. The seam is already right — `MarketDataService` is the only fetcher, so
nothing in the UI changes.

Prerequisites, in order: (2) for real stake sizing, then rate limiting below.
Should ship behind an explicit opt-in with the DEMO/LIVE status strip driven by
the provider's own `mode`, so there is never doubt about what is on screen.

---

## Known issues and debt

| Issue | Where | Notes |
|---|---|---|
| Net-edge formula written twice | `cross_exchange.py`, `app/utils/calculations.py` | Same equation, two copies. The differing commission *rates* are deliberate — only the formula should be shared |
| Partial test coverage | `tests/` | The arbitrage maths and the Qt boundary are covered. The scanner in `src/` - matching, both detectors - is not |
| No rate limiting or backoff | both poll loops | A fixed `time.sleep(interval)` with no awareness of quota; an HTTP 429 is unhandled |
| Best-price only, depth ignored | `cross_exchange.py` | Covered by *Next* item 2 |
| `MATCHBOOK_MFA_CODE` unused | `.env` | Present but read by nothing — finish the MFA path or drop the key |
| `max_executable` is quantised to £250 | `app/utils/calculations.py` | Scans in steps of ceiling/200, so thin books report £0 and every answer rounds to £250. Pinned by `test_max_executable_is_coarse_on_thin_books` |
| Matching is O(events × events) | `cross_exchange.py` | Fine at current scale; will not stay fine |
| Commission rates are approximations | `COMMISSION` dicts | Both venues have tiered/market-dependent rates; these are deliberate guards, not settlement figures |
| `RiskEngine._passes_profile` copied into `web/webapp.py` | `app/services/`, `web/` | Six lines duplicated because the original lives in a `QObject`. Fix: move the predicate onto `RiskProfile` |

### The one that matters most

**Betfair's free app key serves delayed prices (roughly 1–3 minutes).** Every
cross-exchange arb the scanner reports is therefore computed against at least one
stale leg, and a genuine arbitrage rarely survives that long. This does not
invalidate the work — detection, matching and the net-edge maths are all
exercised properly on delayed data — but no number the scanner currently prints
should be treated as executable.

Two honest consequences:

- **Validate the machinery on delayed data; do not trade on it.** The right use of
  the delayed key is to prove the detection logic is correct and to measure how
  often and how large edges appear.
- **The live key is the gate to anything executable.** Worth buying only once the
  persisted dataset from *Next* item 1 shows edges that would clear commission,
  the safety buffer *and* a realistic stake.

---

## Further out

- **Third venue.** The client shape is deliberately repeatable. Smarkets (£150
  one-off, refundable, plus an application) and Betdaq (£250 one-off) are the
  candidates; neither is free, so this only makes sense once two venues have
  proven real edges. Each venue added grows the cross-venue pair count
  quadratically, which is the point.
- **Move detection off best-price-at-an-instant** toward modelling how long an
  edge persists, using the lifetime data from *Next* item 1.
- **Sport-specific tuning.** Match thresholds and market aliases are currently
  global; horse racing and football have very different naming conventions.
- **Backtesting.** Once opportunities are persisted, replay them to test whether a
  given preset would have been profitable — with slippage, which the terminal's
  bot already models.

## Explicitly not planned

- **Placing real bets.** MarketSync is an analysis tool. The terminal's trading is
  paper only, and automated real-money execution is out of scope.
- **Cloud-hosted trading or credential storage.** The scanner is local by design —
  credentials stay in a gitignored `.env`, data in a local SQLite file, and nothing
  authenticated ever runs on a server. A *public demo of the terminal on simulated
  data* is a separate matter and is planned.
