"""MarketSync — cross-exchange arbitrage scanner (Matchbook vs Betfair).

Pulls the same sport from both exchanges, matches events/markets/runners across
them (they share no IDs and spell names differently), then flags two arbs:

1. Combined-back under-round — best back price per runner taken across BOTH
   exchanges; if the combined book < 100% you can back every runner on whichever
   venue is cheapest and profit whoever wins. Extends matchbook.py's under-round.
2. Back/lay cross arb — per selection, if the best BACK on one exchange beats the
   best LAY on the other, you back there and lay here to lock in the difference.

The exchange-specific plumbing lives in matchbook.py and betfair.py; this module
only imports their clients, normalises the two very different response shapes into
one common form, and does the matching + detection on top.
"""

import time
from datetime import datetime
from difflib import SequenceMatcher

import requests

import matchbook
import betfair

# Rough exchange commissions (on net market winnings). Betfair's standard is
# higher and market-dependent; treat these as guards, not exact settlement.
COMMISSION = {"matchbook": 0.02, "betfair": 0.05}

# Extra edge (percentage points) an arb must clear ON TOP of commission before it
# counts as "safe" — a cushion for prices moving between spotting the arb and
# getting both legs matched. Raise it to be stricter, lower it to see thin edges.
SAFETY_BUFFER = 1.0

# How often the poll loop re-scans, in seconds. Mind each exchange's request cost.
POLL_SECONDS = 30

# Minimum worst-case net % for an arb to be surfaced at all. Presets tune this.
MIN_NET = 0.5

# Risk presets — how conservative the scan is. Each sets the SAFE buffer (cushion
# for slippage before "safe") and the minimum net edge required to show an arb.
# Choose one on the command line: python src/cross_exchange.py loop safe|moderate|risky
PRESETS = {
    "safe":     {"buffer": 2.0, "min_net": 2.0},    # only comfortably clear arbs
    "moderate": {"buffer": 1.0, "min_net": 0.5},    # real edges with a small cushion
    "risky":    {"buffer": 0.0, "min_net": 0.01},   # anything net-positive, no cushion
}


def apply_preset(name):
    """Set the global SAFE buffer and min-net from a named preset (falls back to
    'moderate' for an unknown name). Returns the preset name actually used."""
    global SAFETY_BUFFER, MIN_NET
    chosen = name if name in PRESETS else "moderate"
    SAFETY_BUFFER = PRESETS[chosen]["buffer"]
    MIN_NET = PRESETS[chosen]["min_net"]
    return chosen

# Fuzzy-match thresholds — how similar two normalised names must be to be "the
# same". Raise them if you see false matches, lower them if real pairs are missed.
EVENT_MATCH = 0.80
RUNNER_MATCH = 0.82

# Map each exchange's market name to a shared canonical key so "Moneyline" (some
# Matchbook sports) and "Match Odds" (Betfair) line up. Unlisted names fall back
# to their normalised text, which still matches when both venues use it verbatim.
MARKET_ALIASES = {
    "moneyline": "match_odds",
    "money line": "match_odds",
    "match odds": "match_odds",
    "match_odds": "match_odds",
}

# Minimal token fixups applied during name normalisation. Kept tiny on purpose —
# aggressive aliasing causes false matches. Fuzzy matching handles the long tail.
TOKEN_ALIASES = {"utd": "united", "&": "and"}


# --- Normalisation ---------------------------------------------------------
def _normalize(text):
    """Lowercase, drop punctuation, apply token fixups, collapse whitespace.

    The shared key both exchanges' names get reduced to before comparison.
    """
    text = (text or "").lower()
    cleaned = []
    for raw_token in text.replace("/", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw_token if ch.isalnum() or ch == "&")
        if not token or token in {"fc", "afc", "sc", "the"}:
            continue
        cleaned.append(TOKEN_ALIASES.get(token, token))
    return " ".join(cleaned)


def _canonical_market(name):
    """Reduce a market name to its shared key (see MARKET_ALIASES)."""
    key = _normalize(name)
    return MARKET_ALIASES.get(key, key.replace(" ", "_"))


def _ratio(a, b):
    """Similarity of two normalised strings, 0..1 (difflib, stdlib only)."""
    return SequenceMatcher(None, a, b).ratio()


def _selection(name, back, lay):
    """One runner reduced to the common shape: raw name, match key, best prices."""
    return {"name": name, "key": _normalize(name), "back": back, "lay": lay}


def normalize_matchbook(events):
    """Turn matchbook.get_events output into a flat list of common Markets.

    Matchbook bundles prices into each runner as a list of {side, odds}; best
    back is the highest back odds, best lay the lowest lay odds.
    """
    markets = []
    for event in events:
        for market in event.get("markets", []):
            selections = []
            for runner in market.get("runners", []):
                prices = runner.get("prices", [])
                backs = [p.get("odds") for p in prices if p.get("side") == "back"]
                lays = [p.get("odds") for p in prices if p.get("side") == "lay"]
                selections.append(_selection(
                    runner.get("name"),
                    max(backs) if backs else None,
                    min(lays) if lays else None,
                ))
            markets.append(_market("matchbook", event.get("name"),
                                   market.get("name"), event.get("start"), selections))
    return markets


def _betfair_markets_from_catalogue(session, catalogue):
    """Join a Betfair catalogue to its live book and emit common Markets.

    Betfair keeps structure (names) and prices in separate calls, so this joins
    the catalogue to the market book on marketId + selectionId — the same join
    scan_sport does — then reads best back/lay from availableToBack/Lay.
    """
    if not catalogue:
        return []
    books = {b["marketId"]: b for b in
             betfair.list_market_book(session, [m["marketId"] for m in catalogue])}

    markets = []
    for market in catalogue:
        book = books.get(market["marketId"], {})
        priced = {r["selectionId"]: r for r in book.get("runners", [])}
        selections = []
        for runner in market.get("runners", []):
            ex = priced.get(runner["selectionId"], {}).get("ex", {})
            backs = ex.get("availableToBack", [])
            lays = ex.get("availableToLay", [])
            selections.append(_selection(
                runner.get("runnerName"),
                backs[0]["price"] if backs else None,
                lays[0]["price"] if lays else None,
            ))
        markets.append(_market("betfair", market.get("event", {}).get("name"),
                               market.get("marketName"),
                               market.get("marketStartTime"), selections))
    return markets


def normalize_betfair(session, event_type_id, max_markets=20):
    """Fetch a whole Betfair sport and turn it into the common Market list."""
    catalogue = betfair.list_market_catalogue(session, event_type_id, max_results=max_markets)
    return _betfair_markets_from_catalogue(session, catalogue)


def normalize_betfair_for_events(session, event_ids, max_markets=100):
    """Fetch only the given Betfair eventIds as common Markets (small, targeted)."""
    if not event_ids:
        return []
    catalogue = betfair.list_market_catalogue_for_events(session, event_ids, max_results=max_markets)
    return _betfair_markets_from_catalogue(session, catalogue)


def betfair_events(session, event_type_id):
    """Cheap list of a sport's Betfair events — id + name only, no markets/prices.

    This is the anchor for overlap matching: match these names against Matchbook's
    events, then pull prices for only the ids that appear on both.
    """
    return [{"id": e["event"]["id"], "name": e["event"]["name"],
             "key": _normalize(e["event"]["name"])}
            for e in betfair.list_events(session, event_type_id)]


def overlapping_betfair_ids(mb_markets, bf_events):
    """Betfair eventIds whose name fuzzily matches an event present on Matchbook."""
    mb_keys = {m["event_key"] for m in mb_markets}
    ids = []
    for event in bf_events:
        if any(_ratio(event["key"], mb_key) >= EVENT_MATCH for mb_key in mb_keys):
            ids.append(event["id"])
    return ids


def _market(venue, event, market, start, selections):
    """One market in the common shape, with pre-computed match keys."""
    return {
        "venue": venue,
        "event": event,
        "event_key": _normalize(event),
        "market": market,
        "market_key": _canonical_market(market),
        "start": start,
        "selections": selections,
    }


# --- Matching --------------------------------------------------------------
def _match_selection(target, candidates):
    """Best fuzzy match for `target` among `candidates`, or None below threshold."""
    best, best_ratio = None, RUNNER_MATCH
    for candidate in candidates:
        ratio = _ratio(target["key"], candidate["key"])
        if ratio >= best_ratio:
            best, best_ratio = candidate, ratio
    return best


def match_markets(mb_markets, bf_markets):
    """Pair Matchbook and Betfair markets that are the same real-world market.

    A pair needs the same canonical market key AND fuzzily-matching event names.
    Each pair carries its runners already joined across venues, so downstream
    detection just reads mb/bf prices per runner.
    """
    pairs = []
    for mb in mb_markets:
        for bf in bf_markets:
            if mb["market_key"] != bf["market_key"]:
                continue
            if _ratio(mb["event_key"], bf["event_key"]) < EVENT_MATCH:
                continue

            runners = []
            for mb_sel in mb["selections"]:
                bf_sel = _match_selection(mb_sel, bf["selections"])
                if bf_sel is None:
                    continue  # unmatched runner — can't compare it across venues
                runners.append({"name": mb_sel["name"], "mb": mb_sel, "bf": bf_sel})

            if runners:
                pairs.append({"event": mb["event"], "market": mb["market"],
                              "bf_event": bf["event"], "runners": runners})
    return pairs


# --- Detection -------------------------------------------------------------
def _best_back(runner):
    """Highest back across both venues for a matched runner: (venue, price)."""
    options = [("matchbook", runner["mb"]["back"]), ("betfair", runner["bf"]["back"])]
    priced = [(v, p) for v, p in options if p]
    return max(priced, key=lambda vp: vp[1]) if priced else (None, None)


def _best_lay(runner):
    """Lowest lay across both venues for a matched runner: (venue, price)."""
    options = [("matchbook", runner["mb"]["lay"]), ("betfair", runner["bf"]["lay"])]
    priced = [(v, p) for v, p in options if p]
    return min(priced, key=lambda vp: vp[1]) if priced else (None, None)


def _rate(net_pct):
    """Safety label from a worst-case net return %: does it clear the buffer?"""
    if net_pct >= SAFETY_BUFFER:
        return "SAFE"
    if net_pct > 0:
        return "THIN"      # real edge, but inside the slippage buffer — risky
    return "SKIP"          # commission wipes it out — not an arb


def _combined_net(legs):
    """Worst-case guaranteed net return (% of total stake) after commission.

    Sizes stakes by equal-profit dutching (stake proportional to 1/odds), then for
    each possible winner works out the net position on each exchange and charges
    that venue's commission only on a net win there. The worst outcome is what you
    are actually guaranteed — that's the honest number.
    """
    book = sum(1 / leg["back"] for leg in legs)          # < 1 means under-round
    stakes = [((1 / leg["back"]) / book, leg) for leg in legs]  # fractions of £1
    gross = 1 / book - 1                                  # same profit whoever wins
    worst = None
    for _, winner in stakes:
        net_by_venue = {}
        for frac, leg in stakes:
            pnl = frac * (leg["back"] - 1) if leg is winner else -frac
            net_by_venue[leg["venue"]] = net_by_venue.get(leg["venue"], 0.0) + pnl
        commission = sum(COMMISSION[v] * net for v, net in net_by_venue.items() if net > 0)
        outcome_net = gross - commission
        worst = outcome_net if worst is None else min(worst, outcome_net)
    return gross * 100, worst * 100


def combined_back_arb(pair):
    """Combined-back under-round using the best back per runner across venues.

    Returns a dict when the book is complete and under 100%, with both the gross
    edge and the worst-case net after commission, plus a safety rating. Returns
    None if the book is incomplete or not under-round.
    """
    legs = []
    for runner in pair["runners"]:
        venue, price = _best_back(runner)
        if not price:
            return None  # incomplete book breaks the back-every-runner guarantee
        legs.append({"runner": runner["name"], "venue": venue, "back": price})

    book = sum(1 / leg["back"] for leg in legs)
    if book >= 1.0:
        return None
    gross, net = _combined_net(legs)
    return {"event": pair["event"], "market": pair["market"], "book_pct": book * 100,
            "gross": gross, "net": net, "safe": _rate(net), "legs": legs}


def _back_lay_net(back_price, back_venue, lay_price, lay_venue):
    """Guaranteed net return per £1 backed, hedged and after both commissions.

    Solves for the lay stake that equalises the win/lose outcomes, charging back
    commission on the back win and lay commission on the lay win. Positive means a
    locked profit whichever way the selection goes.
    """
    c_back = COMMISSION[back_venue]
    c_lay = COMMISSION[lay_venue]
    lay_stake = ((back_price - 1) * (1 - c_back) + 1) / (lay_price - c_lay)
    profit = lay_stake * (1 - c_lay) - 1     # identical in the win case by construction
    return profit * 100


def back_lay_arbs(pair):
    """Per-selection back/lay cross arbs: back where back-odds are highest, lay
    where lay-odds are lowest. Reports the net after commission (not just the raw
    gap) and a safety rating; only genuine edges (back > lay, cross-venue) qualify.
    """
    found = []
    for runner in pair["runners"]:
        back_venue, back_price = _best_back(runner)
        lay_venue, lay_price = _best_lay(runner)
        # Same-venue back never exceeds its own lay; a real edge is cross-venue.
        if not (back_price and lay_price and back_venue != lay_venue and back_price > lay_price):
            continue
        net = _back_lay_net(back_price, back_venue, lay_price, lay_venue)
        found.append({
            "event": pair["event"], "market": pair["market"], "runner": runner["name"],
            "back_venue": back_venue, "back": back_price,
            "lay_venue": lay_venue, "lay": lay_price,
            "gross": (back_price / lay_price - 1) * 100, "net": net, "safe": _rate(net),
        })
    return found


def find_opportunities(mb_markets, bf_markets):
    """Run both detectors over every matched market, drop the commission-negative
    ones, and sort what's left by worst-case net (best first). Returns
    (pairs, combined, back_lay)."""
    pairs = match_markets(mb_markets, bf_markets)
    combined = [arb for pair in pairs if (arb := combined_back_arb(pair)) and arb["net"] >= MIN_NET]
    back_lay = [arb for pair in pairs for arb in back_lay_arbs(pair) if arb["net"] >= MIN_NET]
    combined.sort(key=lambda a: a["net"], reverse=True)
    back_lay.sort(key=lambda a: a["net"], reverse=True)
    return pairs, combined, back_lay


# --- Presentation ----------------------------------------------------------
def _find_sport_id(sports, name, key):
    """Case-insensitive lookup of a sport id by name in an exchange's sport list.

    `key` extracts (id, name) from each entry, since the two exchanges shape their
    sport lists differently.
    """
    target = name.lower()
    for sport in sports:
        sid, sname = key(sport)
        if (sname or "").lower() == target:
            return sid
    return None


def preview(mb_markets, bf_markets):
    """Show what each exchange returned and where their events line up.

    Run this first when you get zero matches: it tells you whether the two
    batches simply share no events (pull a bigger window) or whether the names
    are just too different for EVENT_MATCH (lower the threshold / add an alias).
    """
    mb_events = {m["event"]: m["event_key"] for m in mb_markets}
    bf_events = {m["event"]: m["event_key"] for m in bf_markets}

    print(f"\nMatchbook events ({len(mb_events)}):")
    for name in sorted(mb_events):
        print(f"  {name}")
    print(f"\nBetfair events ({len(bf_events)}):")
    for name in sorted(bf_events):
        print(f"  {name}")

    print("\nEvent overlaps (MATCH = counts, near = close but below threshold):")
    any_hit = False
    for mb_name, mb_key in sorted(mb_events.items()):
        for bf_name, bf_key in bf_events.items():
            ratio = _ratio(mb_key, bf_key)
            if ratio >= EVENT_MATCH:
                any_hit = True
                print(f"  MATCH {ratio:.2f}: '{mb_name}'  <->  '{bf_name}'")
            elif ratio >= 0.5:
                print(f"  near  {ratio:.2f}: '{mb_name}'  <->  '{bf_name}'")
    if not any_hit:
        print("  (nothing at/above EVENT_MATCH — the two batches share no events.\n"
              "   Pull a bigger window, or if you see high 'near' scores lower EVENT_MATCH.)")


def report(mb_markets, bf_markets):
    """Print matched markets and any cross-exchange opportunities, each rated for
    safety: gross edge, worst-case net after commission, and a SAFE/THIN flag
    against the SAFETY_BUFFER cushion. Only commission-positive arbs are shown,
    best net first."""
    pairs, combined, back_lay = find_opportunities(mb_markets, bf_markets)
    print(f"Matched {len(pairs)} markets across both exchanges "
          f"({len(mb_markets)} Matchbook / {len(bf_markets)} Betfair markets seen).")
    print(f"Commissions {COMMISSION}, safety buffer {SAFETY_BUFFER:.1f}%  "
          f"(net = worst-case guaranteed return after commission).")

    if combined:
        print(f"\n=== {len(combined)} COMBINED-BACK UNDER-ROUND ===")
        for arb in combined:
            print(f"\n[{arb['safe']}] {arb['event']} — {arb['market']}: "
                  f"book {arb['book_pct']:.1f}%  gross {arb['gross']:.2f}%  "
                  f"net {arb['net']:.2f}%")
            for leg in arb["legs"]:
                print(f"    {(leg['runner'] or '?')[:22]:<22} back {leg['back']} @ {leg['venue']}")

    if back_lay:
        print(f"\n=== {len(back_lay)} BACK/LAY CROSS ARBS ===")
        for arb in back_lay:
            print(f"  [{arb['safe']}] {arb['event']} — {arb['runner']}: "
                  f"back {arb['back']} @ {arb['back_venue']}  /  "
                  f"lay {arb['lay']} @ {arb['lay_venue']}  "
                  f"gross {arb['gross']:.2f}%  net {arb['net']:.2f}%")

    if not combined and not back_lay:
        print("No commission-positive cross-exchange opportunities in this batch.")


def _resolve_sports(mb, bf, sport):
    """Look up `sport`'s id on each exchange by name; exit if either is missing."""
    mb_sport = _find_sport_id(matchbook.get_sports(mb, per_page=100),
                              sport, lambda s: (s.get("id"), s.get("name")))
    bf_sport = _find_sport_id(betfair.list_event_types(bf), sport,
                              lambda s: (s["eventType"]["id"], s["eventType"]["name"]))
    if mb_sport is None or bf_sport is None:
        raise SystemExit(f"Couldn't find '{sport}' on both "
                         f"(Matchbook={mb_sport}, Betfair={bf_sport}).")
    return mb_sport, bf_sport


def scan_cycle(mb, bf, mb_sport, bf_sport, per_page):
    """One pass: pull both exchanges (anchored on Matchbook) and normalise them.

    Returns (mb_markets, bf_markets, betfair_event_count, shared_event_count). The
    price fetch is scoped to events present on Matchbook, keeping it small.
    """
    mb_markets = normalize_matchbook(matchbook.get_events(mb, mb_sport, per_page=per_page))
    bf_all = betfair_events(bf, bf_sport)
    shared_ids = overlapping_betfair_ids(mb_markets, bf_all)
    bf_markets = normalize_betfair_for_events(bf, shared_ids)
    return mb_markets, bf_markets, len(bf_all), len(shared_ids)


def _arb_key(arb):
    """Stable identity for an arb across cycles, so the loop knows if it's new.

    Keyed on the market/selection and venues, NOT the price — a still-open arb whose
    net drifts a little is the same arb, not a new one.
    """
    if "runner" in arb:  # back/lay arb
        return ("bl", arb["event"], arb["runner"], arb["back_venue"], arb["lay_venue"])
    return ("cb", arb["event"], arb["market"])  # combined-back arb


def _format_arb(arb):
    """One-line description of an arb for the loop output."""
    if "runner" in arb:
        return (f"[{arb['safe']}] {arb['event']} — {arb['runner']}: "
                f"back {arb['back']}@{arb['back_venue']} / lay {arb['lay']}@{arb['lay_venue']}  "
                f"net {arb['net']:.2f}%")
    return (f"[{arb['safe']}] {arb['event']} — {arb['market']}: "
            f"gross {arb['gross']:.2f}%  net {arb['net']:.2f}%")


def main(sport="Soccer", per_page=100, preview_only=False, preset="moderate"):
    """One-shot scan: pull `sport` from both exchanges and preview or report arbs.

    per_page defaults high because the two exchanges return different event windows
    — you need a wide enough pull on both for the SAME events to appear in each.
    Run with preview_only=True (or `python src/cross_exchange.py preview`) first to
    confirm there's actual event overlap before trusting the arb output.
    """
    apply_preset(preset)
    mb = matchbook.login()
    bf = betfair.login()
    print("Logged into both exchanges.")
    mb_sport, bf_sport = _resolve_sports(mb, bf, sport)

    mb_markets, bf_markets, bf_count, shared = scan_cycle(mb, bf, mb_sport, bf_sport, per_page)
    print(f"Matchbook events: {len({m['event'] for m in mb_markets})}  |  "
          f"Betfair events: {bf_count}  |  shared: {shared}")

    if preview_only:
        preview(mb_markets, bf_markets)
    else:
        report(mb_markets, bf_markets)


def scan_loop(sport="Soccer", interval=POLL_SECONDS, per_page=100, preset="moderate"):
    """Poll both exchanges on a fixed interval, printing each arb ONCE when it first
    appears and again when it closes — not every cycle. Re-authenticates when either
    session token expires; a one-line heartbeat shows it's alive. Ctrl+C stops.
    """
    chosen = apply_preset(preset)
    mb = matchbook.login()
    bf = betfair.login()
    print("Logged into both exchanges.")
    mb_sport, bf_sport = _resolve_sports(mb, bf, sport)
    print(f"Polling {sport} every {interval}s — preset '{chosen}' "
          f"(buffer {SAFETY_BUFFER:.1f}%, min net {MIN_NET:.2f}%, commissions {COMMISSION}). "
          f"Ctrl+C to stop.\n")

    seen = {}  # arb key -> arb, carried across cycles to detect new vs closed
    while True:
        try:
            mb_markets, bf_markets, _, shared = scan_cycle(mb, bf, mb_sport, bf_sport, per_page)
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 401:
                print("Matchbook session expired — re-authenticating.")
                mb = matchbook.login()
                continue
            raise
        except RuntimeError as error:
            # betfair.rpc raises this; a session lapse carries a SESSION error code.
            if "SESSION" in str(error).upper():
                print("Betfair session expired — re-authenticating.")
                bf = betfair.login()
                continue
            raise

        pairs, combined, back_lay = find_opportunities(mb_markets, bf_markets)
        current = {_arb_key(arb): arb for arb in combined + back_lay}
        new_keys = [key for key in current if key not in seen]
        closed_keys = [key for key in seen if key not in current]

        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}] shared {shared} / matched {len(pairs)} / open {len(current)} — "
              f"{len(new_keys)} new, {len(closed_keys)} closed")
        for key in new_keys:
            print(f"    NEW    {_format_arb(current[key])}")
        for key in closed_keys:
            print(f"    closed {_format_arb(seen[key])}")

        seen = current
        time.sleep(interval)


if __name__ == "__main__":
    import sys
    preset = next((arg for arg in sys.argv[1:] if arg in PRESETS), "moderate")
    if "loop" in sys.argv:
        try:
            scan_loop(preset=preset)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        main(preview_only="preview" in sys.argv, preset=preset)
