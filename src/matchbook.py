"""MarketSync — Matchbook exchange client + same-site under-round scanner.

Logs into the Matchbook API with credentials from .env, pulls live back/lay
prices for a chosen sport, and flags any market whose back prices imply a book
under 100% — a theoretical "back every runner and profit whoever wins" arb.
"""

import os
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# --- Matchbook API ---------------------------------------------------------
LOGIN_URL = "https://api.matchbook.com/bpapi/rest/security/session"
SPORTS_URL = "https://api.matchbook.com/edge/rest/lookups/sports"
EVENTS_URL = "https://api.matchbook.com/edge/rest/events"
USER_AGENT = "MarketSync/0.1"  # Matchbook rejects requests that send no User-Agent
COMMISSION = 0.02              # ~2% commission on net market winnings
WATCH_SPORT_IDS = [3, 1, 116]  # Baseball, American Football, Darts — sports to poll
POLL_SECONDS = 30              # interval between scans (mind the API request cost)


def login():
    """Authenticate with .env credentials and return a requests.Session that
    carries the session-token header on every subsequent request."""
    username = os.getenv("MATCHBOOK_USERNAME")
    password = os.getenv("MATCHBOOK_PASSWORD")
    if not username or not password:
        sys.exit("Missing MATCHBOOK_USERNAME / MATCHBOOK_PASSWORD in .env")

    response = requests.post(
        LOGIN_URL,
        json={"username": username, "password": password},
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    # A 200 isn't proof of success — read the body before trusting it.
    if response.status_code != 200:
        sys.exit(f"Login failed (HTTP {response.status_code}): {response.text}")
    token = response.json().get("session-token")
    if not token:
        sys.exit(f"Login succeeded but no session-token in body: {response.json()}")

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "session-token": token,
    })
    return session


def get_sports(session, per_page=20):
    """Return the list of active sports; each has a 'name' and an 'id'."""
    params = {"offset": 0, "per-page": per_page, "status": "active", "order": "name asc"}
    response = session.get(SPORTS_URL, params=params)
    response.raise_for_status()
    return response.json().get("sports", [])


def get_events(session, sport_id, per_page=5):
    """Return open events for a sport, with back/lay prices included."""
    params = {
        "offset": 0,
        "per-page": per_page,
        "sport-ids": sport_id,
        "states": "open",
        "exchange-type": "back-lay",
        "odds-type": "DECIMAL",
        "include-prices": "true",
        "price-depth": 3,
        "price-mode": "expanded",
    }
    response = session.get(EVENTS_URL, params=params)
    response.raise_for_status()
    return response.json().get("events", [])


# --- Analysis --------------------------------------------------------------
def best_back(runner):
    """Highest available back price for a runner, or None if unbackable."""
    backs = [p.get("odds") for p in runner.get("prices", []) if p.get("side") == "back"]
    return max(backs) if backs else None


def book_percentage(market):
    """Sum of 1/best_back across a market's runners.

    Returns (book_pct, priced, total). book_pct sums only the priced runners, so
    the caller compares priced == total to know the book is complete. A complete
    book under 100% is a theoretical back-every-runner arbitrage.
    """
    runners = market.get("runners", [])
    inv_sum = 0.0
    priced = 0
    for runner in runners:
        odds = best_back(runner)
        if odds:
            inv_sum += 1 / odds
            priced += 1
    return inv_sum, priced, len(runners)


def find_opportunities(events):
    """Return the under-round markets in a batch of events.

    Each item is a dict: {event, market, book_pct, margin, beats_commission,
    runners}. Only complete books under 100% qualify — the guaranteed
    back-every-runner case. This is the detection core the loop polls with.
    """
    opportunities = []
    for event in events:
        for market in event.get("markets", []):
            inv_sum, priced, total = book_percentage(market)
            if priced > 0 and priced == total and inv_sum < 1.0:
                margin = (1 - inv_sum) * 100
                opportunities.append({
                    "event": event.get("name"),
                    "market": market.get("name"),
                    "book_pct": inv_sum * 100,
                    "margin": margin,
                    "beats_commission": margin > COMMISSION * 100,
                    "runners": [(r.get("name"), best_back(r)) for r in market.get("runners", [])],
                })
    return opportunities


# --- Presentation ----------------------------------------------------------
def scan_events(events):
    """Print each market's book percentage, flagging under-round markets."""
    for event in events:
        print(f"\n{'=' * 60}\nEVENT: {event.get('name')}  ({event.get('start')})")
        for market in event.get("markets", []):
            inv_sum, priced, total = book_percentage(market)
            name = market.get("name")

            if priced == 0:
                print(f"  {name}: no priced runners — skipped")
            elif priced < total:
                # Incomplete book: an unbackable runner breaks the win-all guarantee.
                print(f"  {name}: partial book {inv_sum * 100:.1f}% over {priced}/{total} "
                      f"priced ({total - priced} unbackable — not a guaranteed arb)")
            elif inv_sum < 1.0:
                margin = (1 - inv_sum) * 100
                note = "" if margin > COMMISSION * 100 else (
                    f"  (margin < {COMMISSION * 100:.0f}% commission — likely not worth it)")
                print(f"  {name}: book {inv_sum * 100:.1f}%  ->  UNDER-ROUND, "
                      f"margin {margin:.2f}%{note}")
                for runner in market.get("runners", []):
                    print(f"      {(runner.get('name') or '?')[:18]:<18} back {best_back(runner)}")
            else:
                print(f"  {name}: book {inv_sum * 100:.1f}% (over-round, normal)")


def scan_loop(session, sport_ids=WATCH_SPORT_IDS, interval=POLL_SECONDS, per_page=20):
    """Poll the watched sports on a fixed interval, reporting under-round markets.

    Prints a one-line heartbeat each cycle and full detail for any opportunity.
    Re-authenticates automatically if the ~6h session token expires. Ctrl+C stops.
    """
    ids = ",".join(str(s) for s in sport_ids)
    print(f"Polling sports {ids} every {interval}s — Ctrl+C to stop.\n")
    while True:
        try:
            events = get_events(session, ids, per_page=per_page)
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 401:
                print("Session expired — re-authenticating.")
                session = login()
                continue
            raise

        stamp = datetime.now().strftime("%H:%M:%S")
        markets = sum(len(event.get("markets", [])) for event in events)
        opportunities = find_opportunities(events)

        if not opportunities:
            print(f"[{stamp}] {len(events)} events / {markets} markets — no under-round")
        else:
            print(f"[{stamp}] {len(opportunities)} UNDER-ROUND "
                  f"({len(events)} events / {markets} markets):")
            for opp in opportunities:
                flag = "" if opp["beats_commission"] else "  (below commission — likely not worth it)"
                print(f"  {opp['event']} — {opp['market']}: "
                      f"book {opp['book_pct']:.1f}%  margin {opp['margin']:.2f}%{flag}")
                for name, back in opp["runners"]:
                    print(f"      {(name or '?')[:18]:<18} back {back}")

        time.sleep(interval)


def main():
    session = login()
    print("Logged in.")
    try:
        scan_loop(session)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
