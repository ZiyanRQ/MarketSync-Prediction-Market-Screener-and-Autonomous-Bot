"""Tests for the arbitrage maths in app/utils/calculations.py.

This module is the one place where a silent error costs real money, so the
invariants it must satisfy are checked directly:

  * a full hedge pays the same whichever way the selection goes;
  * gross - commission == net;
  * commission is charged on net winnings only, per venue;
  * deeper stakes fill at worse prices, so ROI falls as capital rises.

    python tests/test_calculations.py     # standalone
    pytest tests/                         # or under pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models.exchange_price import PriceLevel  # noqa: E402
from app.utils import calculations as calc        # noqa: E402

C_BACK = 0.02
C_LAY = 0.02


def book(back_odds: float, lay_odds: float, size: float = 500.0):
    """A simple two-venue ladder: back high on one side, lay low on the other."""
    back = [PriceLevel(round(back_odds - i * 0.05, 2), size) for i in range(4)]
    lay = [PriceLevel(round(lay_odds + i * 0.05, 2), size) for i in range(4)]
    return back, lay


# --- the hedge ------------------------------------------------------------
def test_hedge_pays_the_same_either_way():
    """The point of the hedge: outcome is identical win or lose."""
    back, lay = book(3.50, 3.40)
    r = calc.simulate(back, lay, 200.0, C_BACK, C_LAY)
    assert abs(r.profit_if_win - r.profit_if_lose) < 1e-6, (
        f"hedge not level: win {r.profit_if_win} vs lose {r.profit_if_lose}")


def test_capital_is_back_stake_plus_liability():
    """Capital is defined as back stake + lay liability; the solver must honour it."""
    back, lay = book(3.50, 3.40)
    r = calc.simulate(back, lay, 500.0, C_BACK, C_LAY)
    assert abs((r.back_stake + r.lay_liability) - 500.0) < 0.5


# --- commission (the bug this file was written for) -----------------------
def test_gross_minus_commission_equals_net():
    """The three figures the inspector shows must be mutually consistent.

    Regression: commission was computed as `gross - net`, which on a hedged
    position is lay liability PLUS commission - reporting ~£79 of commission on
    a £0.39 profit.
    """
    for capital in (50.0, 200.0, 1000.0):
        r = calc.simulate(*book(3.50, 3.40), capital, C_BACK, C_LAY)
        assert abs((r.gross_profit - r.commission) - r.net_profit) < 1e-9, (
            f"at £{capital}: {r.gross_profit} - {r.commission} != {r.net_profit}")


def test_commission_is_never_negative_and_is_plausible():
    """Commission is a charge, not a credit, and cannot exceed the gross win."""
    r = calc.simulate(*book(3.50, 3.40), 200.0, C_BACK, C_LAY)
    assert r.commission >= 0
    # At 2% it should be a small fraction of the money staked, not a multiple of it.
    assert r.commission < r.back_stake, (
        f"commission {r.commission} exceeds the back stake {r.back_stake}")


def test_zero_commission_leaves_gross_equal_to_net():
    r = calc.simulate(*book(3.50, 3.40), 200.0, 0.0, 0.0)
    assert abs(r.commission) < 1e-9
    assert abs(r.gross_profit - r.net_profit) < 1e-9


def test_higher_commission_reduces_profit():
    cheap = calc.simulate(*book(3.50, 3.40), 200.0, 0.02, 0.02)
    dear = calc.simulate(*book(3.50, 3.40), 200.0, 0.05, 0.05)
    assert dear.net_profit < cheap.net_profit


# --- edges ----------------------------------------------------------------
def test_net_edge_matches_a_hand_computed_hedge():
    """net_edge is profit per £1 backed - check it against the explicit hedge."""
    back_odds, lay_odds = 3.50, 3.40
    m = calc.hedge_unit(back_odds, lay_odds, C_BACK, C_LAY)
    expected = (m * (1 - C_LAY) - 1) * 100
    assert abs(calc.net_edge(back_odds, lay_odds, C_BACK, C_LAY) - expected) < 1e-9


def test_net_edge_is_below_gross_edge():
    """Commission can only erode an edge, never improve it."""
    gross = calc.gross_edge(3.50, 3.40)
    net = calc.net_edge(3.50, 3.40, C_BACK, C_LAY)
    assert net < gross


def test_no_edge_when_lay_exceeds_back():
    """Backing below the lay price is a guaranteed loss, not an arb."""
    assert calc.net_edge(3.40, 3.50, C_BACK, C_LAY) < 0


# --- depth ----------------------------------------------------------------
def test_roi_falls_as_capital_rises():
    """Larger stakes walk down the ladder, so the edge erodes with size."""
    back, lay = book(3.50, 3.40, size=60.0)   # thin rungs, so depth bites early
    small = calc.simulate(back, lay, 50.0, C_BACK, C_LAY)
    large = calc.simulate(back, lay, 1500.0, C_BACK, C_LAY)
    assert large.net_roi < small.net_roi


def test_max_executable_is_still_profitable_and_beyond_it_is_not():
    # Depth well above the scan granularity (see the test below), so the
    # ceiling is resolved rather than rounded away.
    back, lay = book(3.50, 3.40, size=800.0)
    ceiling = calc.max_executable(back, lay, C_BACK, C_LAY)
    assert ceiling > 0
    assert calc.simulate(back, lay, ceiling, C_BACK, C_LAY).net_profit > 0
    beyond = calc.simulate(back, lay, ceiling * 4, C_BACK, C_LAY)
    assert beyond.net_profit <= 0 or not beyond.executable


def test_max_executable_is_coarse_on_thin_books():
    """KNOWN LIMITATION, pinned so a future fix is a deliberate choice.

    max_executable scans upward in steps of ceiling/200 (£250 at the default
    £50k ceiling), so its answer is quantised to £250 and any book too thin to
    absorb one step reports £0 - even when a smaller stake would be profitable.
    """
    thin_back, thin_lay = book(3.50, 3.40, size=60.0)      # £240 of depth a side
    assert calc.max_executable(thin_back, thin_lay, C_BACK, C_LAY) == 0.0
    # ...yet £150 into that same book is genuinely profitable.
    assert calc.simulate(thin_back, thin_lay, 150.0, C_BACK, C_LAY).net_profit > 0

    # A lower ceiling shrinks the step and resolves it.
    assert calc.max_executable(thin_back, thin_lay, C_BACK, C_LAY, ceiling=400.0) > 0


def test_empty_book_is_handled():
    """No prices must not raise - it should report an unusable, zero result."""
    r = calc.simulate([], [], 100.0, C_BACK, C_LAY)
    assert r.net_profit == 0 and r.back_stake == 0


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as err:
            failed.append(name)
            print(f"  FAIL  {name}\n        {err}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
