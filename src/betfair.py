"""MarketSync — Betfair Exchange client + event/price grabber.

Logs into the Betfair API with credentials from .env, then pulls sports, events,
markets and live back/lay prices via the JSON-RPC Betting API.

Betfair's docs are language-neutral ("universal grabber") because every call is
the same shape: an HTTP POST of a JSON-RPC envelope to one endpoint, changing
only the `method`. Unlike Matchbook, prices are NOT bundled into the events
call — you fetch market/runner structure with listMarketCatalogue, then live
prices separately with listMarketBook keyed by marketId.
"""

import os
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# --- Betfair API -----------------------------------------------------------
# Interactive (non-certificate) login. If your account requires certificate
# login you'd POST to identitysso-cert.betfair.com with a client cert instead.
LOGIN_URL = "https://identitysso.betfair.com/api/login"
# Every Betting API operation is a POST to this one JSON-RPC endpoint.
BETTING_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
API_PREFIX = "SportsAPING/v1.0/"  # prepended to every method name

POLL_SECONDS = 30  # interval between scans (mind the API request cost)


def login():
    """Authenticate with .env credentials and return a requests.Session that
    carries the app key + session token headers on every subsequent request."""
    username = os.getenv("BETFAIR_USERNAME")
    password = os.getenv("BETFAIR_PASSWORD")
    app_key = os.getenv("BETFAIR_APP_KEY")
    if not username or not password or not app_key:
        sys.exit("Missing BETFAIR_USERNAME / BETFAIR_PASSWORD / BETFAIR_APP_KEY in .env")

    response = requests.post(
        LOGIN_URL,
        # Interactive login is form-encoded, NOT JSON.
        data={"username": username, "password": password},
        headers={
            "X-Application": app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    if response.status_code != 200:
        sys.exit(f"Login failed (HTTP {response.status_code}): {response.text}")

    body = response.json()
    # A 200 isn't proof of success — Betfair puts the real result in "status".
    if body.get("status") != "SUCCESS":
        sys.exit(f"Login rejected: {body.get('status')} / {body.get('error')}")
    token = body.get("token")

    session = requests.Session()
    session.headers.update({
        "X-Application": app_key,
        "X-Authentication": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return session


def rpc(session, method, params=None):
    """Fire one JSON-RPC call and return its `result`.

    This is the whole "universal grabber": build the envelope, POST it, unwrap.
    Every listing operation below is just this with a different method + params.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": API_PREFIX + method,
        "params": params or {},
        "id": 1,
    }
    response = session.post(BETTING_URL, json=payload)
    response.raise_for_status()
    body = response.json()
    # JSON-RPC reports API-level failures in an "error" object, not the HTTP code.
    if "error" in body:
        raise RuntimeError(f"{method} failed: {body['error']}")
    return body["result"]


# --- Grabbers (each is one rpc call) ---------------------------------------
def list_event_types(session):
    """Return active sports, each as {'eventType': {'id', 'name'}, 'marketCount'}.
    Betfair's equivalent of Matchbook's get_sports. Soccer=1, Tennis=2, Horse
    Racing=7 are the common ids."""
    return rpc(session, "listEventTypes", {"filter": {}})


def list_events(session, event_type_id):
    """Return upcoming events for a sport, each {'event': {...}, 'marketCount'}."""
    return rpc(session, "listEvents", {
        "filter": {"eventTypeIds": [str(event_type_id)]},
    })


def list_market_catalogue(session, event_type_id, max_results=10):
    """Return markets with their runners for a sport (structure, no prices).

    marketProjection asks for the extra detail — RUNNER_DESCRIPTION gives you the
    runner names, EVENT gives the event each market belongs to.
    """
    return rpc(session, "listMarketCatalogue", {
        "filter": {"eventTypeIds": [str(event_type_id)]},
        "marketProjection": ["EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
        "sort": "FIRST_TO_START",
        "maxResults": max_results,
    })


def list_market_catalogue_for_events(session, event_ids, max_results=100):
    """Markets (with runners) for specific eventIds, not a whole sport.

    Same as list_market_catalogue but filtered to given events — used to pull only
    the events that also exist on another exchange, keeping the price fetch small.
    """
    return rpc(session, "listMarketCatalogue", {
        "filter": {"eventIds": [str(e) for e in event_ids]},
        "marketProjection": ["EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
        "sort": "FIRST_TO_START",
        "maxResults": max_results,
    })


# Betfair caps how much price data one listMarketBook call may return; asking for
# too many markets at once raises TOO_MUCH_DATA. Batch marketIds under this size.
BOOK_CHUNK = 25


def list_market_book(session, market_ids):
    """Return LIVE prices for the given marketIds.

    priceProjection EX_BEST_OFFERS gives best available back/lay per runner —
    this is the call that carries the odds. market_ids: a list of marketId strings.
    Requests are batched in chunks of BOOK_CHUNK to stay under Betfair's per-call
    data limit, then concatenated back into one flat list.
    """
    books = []
    for start in range(0, len(market_ids), BOOK_CHUNK):
        books.extend(rpc(session, "listMarketBook", {
            "marketIds": market_ids[start:start + BOOK_CHUNK],
            "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
        }))
    return books


# --- Presentation ----------------------------------------------------------
def best_back(runner):
    """Highest available back price for a runner in a market book, or None.

    Betfair nests it under availableToBack (a list of {price, size}, best first)."""
    backs = runner.get("ex", {}).get("availableToBack", [])
    return backs[0]["price"] if backs else None


def scan_sport(session, event_type_id, max_markets=5):
    """Grab markets for a sport and print each runner's best back price.

    Demonstrates the full chain: catalogue for structure (names) + book for prices,
    joined on marketId. This is where you'd plug in the under-round check from
    matchbook.py once you're happy the data is flowing.
    """
    catalogue = list_market_catalogue(session, event_type_id, max_results=max_markets)
    if not catalogue:
        print("No markets returned.")
        return

    # Map marketId -> live book so we can join names (catalogue) to prices (book).
    market_ids = [m["marketId"] for m in catalogue]
    books = {b["marketId"]: b for b in list_market_book(session, market_ids)}

    for market in catalogue:
        book = books.get(market["marketId"], {})
        event_name = market.get("event", {}).get("name", "?")
        print(f"\n{'=' * 60}\n{event_name}  —  {market.get('marketName')}  "
              f"({market.get('marketStartTime')})")

        # Catalogue and book both list runners; join them on selectionId.
        prices = {r["selectionId"]: r for r in book.get("runners", [])}
        for runner in market.get("runners", []):
            priced = prices.get(runner["selectionId"], {})
            print(f"  {runner.get('runnerName', '?')[:24]:<24} back {best_back(priced)}")


def main():
    session = login()
    print("Logged in.")

    sports = list_event_types(session)
    print(f"\n{len(sports)} sports available. First few:")
    for s in sports[:8]:
        et = s["eventType"]
        print(f"  {et['id']:>4}  {et['name']}  ({s['marketCount']} markets)")

    # Soccer (event type 1) as a demo — swap for whatever id you want.
    print("\nGrabbing Soccer markets + live prices:")
    scan_sport(session, event_type_id=1)


if __name__ == "__main__":
    main()
