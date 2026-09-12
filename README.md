# MarketSync

A prediction-market arbitrage analysis platform for betting exchanges. MarketSync
authenticates to exchange APIs, pulls live back/lay prices, and scans markets for
pricing inefficiencies — mispricings where the odds imply a guaranteed profit.

Built from scratch while learning Python, software engineering, and quantitative
finance. Every line is code I can explain.

## What it does today

- **Authenticates** to the [Matchbook](https://developers.matchbook.com/) exchange
  API and holds a reusable session (credentials stay in a gitignored `.env`).
- **Fetches live market data** — sports, events, and full back/lay price ladders —
  in a single `include-prices` call rather than one request per runner.
- **Scans for same-exchange arbitrage** ("under-round" markets): for each market it
  sums `1 / best_back_odds` across every runner. A complete book summing to **under
  100%** means you could back every outcome and profit whoever wins. The scanner
  flags these and checks the margin against exchange commission, so edges that fees
  would erase are surfaced honestly rather than sold as wins.

## How the arbitrage works

A betting **exchange** (unlike a bookmaker) has no house setting the odds — prices
are other users' back/lay offers, and the exchange takes a commission. That makes
the market efficient: a healthy book sums to *just over* 100% (the spread). MarketSync
looks for the exceptions:

- **Under-round books** (< 100%) — a transient pricing error where backing every
  runner is a guaranteed profit. Rare on a single exchange, which is why the roadmap
  targets multiple venues.
- **Cross-venue gaps** (planned) — the same event priced differently on two exchanges,
  where one venue's back price beats another's lay price. This is the structural,
  repeatable edge.

Any flagged edge must clear commission on every leg to be real — a check built into
the scanner from the start.

## Roadmap

- [x] Matchbook API client (auth, sports, events, live prices)
- [x] Same-exchange under-round scanner with commission check
- [ ] Continuous polling loop for transient opportunities
- [ ] Second venue (Betfair / Betfred) for cross-venue comparison
- [ ] Persist and alert on flagged opportunities

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your Matchbook credentials to a .env file in the project root
#    (this file is gitignored and never committed)
```

`.env`:

```
MATCHBOOK_USERNAME=your_username
MATCHBOOK_PASSWORD=your_password
```

Then run the scanner:

```bash
python src/matchbook.py
```

## Project structure

```
src/matchbook.py   API client + analysis + scanner (login, get_events, book_percentage, scan_events)
docs/              Architecture and roadmap notes
dev-log/           Daily development journal
requirements.txt   Python dependencies
```

## Tech

Python · [`requests`](https://requests.readthedocs.io/) · `python-dotenv` · the
Matchbook Exchange REST API.

## Development journal

This project is built in the open, one day at a time. The reasoning, bugs, and
lessons behind each step are logged in [`dev-log/`](dev-log/).
