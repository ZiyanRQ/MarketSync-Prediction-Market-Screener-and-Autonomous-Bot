# Resources

Reference material for the exchanges MarketSync talks to: how to get access, what
it costs, and which endpoints the code actually uses.

## Exchange API landscape

The driving constraint on this project is that most betting exchanges charge for
API access, usually as a one-off fee. Source selection is therefore an
architectural decision, not a detail.

| Exchange | Cost of access | Status here |
|---|---|---|
| **Matchbook** | Free | **In use** — the base client, `src/matchbook.py` |
| **Betfair** | Delayed key **free**; live key a one-off charge (~£499) | **In use** — `src/betfair.py`, on the delayed key |
| **Smarkets** | ~£150 one-off (refundable within 60 days) + application form | Not integrated |
| **Betdaq** | ~£250 one-off | Not integrated |

Fees change — confirm current terms with each exchange before relying on these.

**The free live-data setup is Matchbook + a Betfair delayed key.** A paid third
venue is only worth it once detection has proven real edges exist; see
[`roadmap.md`](roadmap.md).

### The delayed-key caveat

Betfair's free application key serves prices delayed by roughly 1–3 minutes. It
runs this codebase completely unchanged, which makes it genuinely useful for
building and validating detection — but every cross-exchange arb computed from it
has at least one stale leg. Good for proving the machinery works and for measuring
how often edges appear; not a basis for treating any printed number as executable.

## Documentation

- **Matchbook** — <https://developers.matchbook.com/>
- **Betfair** — <https://developer.betfair.com/>

Betfair's documentation is written language-neutrally, which reads oddly at first
but makes sense once the shape of the API is clear: every Betting API call is the
same HTTP POST of a JSON-RPC envelope to one endpoint, with only `method` and
`params` changing. That uniformity is exactly why `src/betfair.py` routes
everything through a single `rpc()` helper.

## Endpoints in use

### Matchbook (REST)

| Purpose | Endpoint |
|---|---|
| Login → session token | `POST /bpapi/rest/security/session` |
| Active sports | `GET /edge/rest/lookups/sports` |
| Events **with prices** | `GET /edge/rest/events` |

Base: `https://api.matchbook.com`

The events call carries `include-prices=true`, `price-depth`, `price-mode=expanded`
and `exchange-type=back-lay`, so one request returns the event universe *and* its
full back/lay ladders — no per-runner follow-up.

Matchbook rejects requests that send no `User-Agent`, which is why the client sets
one explicitly.

### Betfair (JSON-RPC)

| Purpose | Method |
|---|---|
| Login | `POST https://identitysso.betfair.com/api/login` |
| Sports | `listEventTypes` |
| Events | `listEvents` |
| Markets + runner names | `listMarketCatalogue` |
| **Live prices** | `listMarketBook` |

Betting API base: `https://api.betfair.com/exchange/betting/json-rpc/v1`, with
every method prefixed `SportsAPING/v1.0/`.

Notes that cost real time to work out:

- Login is **form-encoded, not JSON** — unlike every other call.
- Login wants the account **username, not the email address**.
- A `.com` host is correct for a UK account.
- Prices are a **separate call** from structure. `listMarketCatalogue` gives runner
  names, `listMarketBook` gives odds; they join on `marketId` + `selectionId`.
- `listMarketBook` caps how much data one call may return — too many markets raises
  `TOO_MUCH_DATA`, so requests are chunked (`BOOK_CHUNK = 25`).
- If an account requires certificate login, the host is
  `identitysso-cert.betfair.com` with a client certificate instead.

## Credentials

All credentials live in a gitignored `.env` at the project root, read via
`python-dotenv`. Never literals, never in a URL.

```
MATCHBOOK_USERNAME=
MATCHBOOK_PASSWORD=

BETFAIR_USERNAME=          # account username, NOT email
BETFAIR_PASSWORD=
BETFAIR_APP_KEY=           # the delayed key works unchanged
```

**Watch for trailing whitespace.** A trailing space on `BETFAIR_APP_KEY` caused a
long and thoroughly misleading login failure — the value looks correct in an
editor and fails at the API.

`.env` currently also holds `MATCHBOOK_MFA_CODE`, which no code reads; see the
debt table in [`roadmap.md`](roadmap.md).

## Rate limits as a design input

Both exchanges meter requests, which shapes the scan strategy rather than sitting
in a footnote:

- Scans are **anchored on Matchbook** — its events call returns prices in one
  request, and Betfair's expensive `listMarketBook` is then called only for events
  that actually overlap.
- The desktop terminal enforces that **only `MarketDataService` fetches**, so UI
  interaction never costs quota.
- Poll intervals are configurable and default to 30s.

This lesson was learned the hard way on a practice API before MarketSync began: a
free tier capped at ~25 requests/day is unusable for anything that polls, which is
precisely why Matchbook and Betfair were chosen over cheaper-to-start options.

## Concepts worth knowing

- **Back / lay** — backing is betting *for* an outcome; laying is betting *against*
  it (acting as the bookmaker). An exchange matches the two.
- **Over-round / under-round** — sum `1/odds` across every runner. Over 100% is
  normal (the spread). Under 100% on a complete book means backing every outcome
  profits whoever wins.
- **Commission** — exchanges charge on **net market winnings**, not stake or
  turnover. This is why the scanner charges commission per venue and only where
  that venue nets a win; a blended or gross rate gives a materially wrong answer.
- **Liability** — for a lay bet, what you owe if the selection wins:
  `stake × (odds − 1)`.
- **Dutching** — splitting stakes across outcomes so profit is equal regardless of
  which wins. How the combined-back detector sizes its legs.
