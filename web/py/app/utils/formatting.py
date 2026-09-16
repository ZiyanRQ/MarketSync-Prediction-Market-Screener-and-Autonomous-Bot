"""Display formatting helpers — money, percentages, odds, clocks.

Kept in one place so every panel renders numbers identically (tabular, signed
where it carries meaning). No Qt imports here — pure strings.
"""

from __future__ import annotations

from datetime import datetime


def money(value: float) -> str:
    return f"£{value:,.2f}"


def signed_money(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}£{abs(value):,.2f}"


def pct(value: float, dp: int = 2) -> str:
    return f"{value:.{dp}f}%"


def signed_pct(value: float, dp: int = 2) -> str:
    return f"{value:+.{dp}f}%"


def odds(value: float | None) -> str:
    return f"{value:.2f}" if value else "—"


def money_short(value: float) -> str:
    """Compact £ for dense ladders: £1.2k, £940."""
    if abs(value) >= 1000:
        return f"£{value / 1000:.1f}k"
    return f"£{value:.0f}"


def clock(ts: datetime, with_millis: bool = False) -> str:
    return ts.strftime("%H:%M:%S.%f")[:-3] if with_millis else ts.strftime("%H:%M:%S")


def age(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"
