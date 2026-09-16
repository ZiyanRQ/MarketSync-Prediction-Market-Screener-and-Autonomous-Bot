"""Autonomous paper-trading bot + performance tracking.

Money model (kept deliberately simple):
  • DEPOSIT   — a fixed amount you allocate to the bot.
  • BALANCE   — deposit + the bot's running P&L.
  • MIN/MAX STAKE — the £ range for any single trade.
The bot sizes each trade (fixed £, % of liquidity, or % of the deposit), clamps it to
[min_stake, max_stake] and to the balance, and places SIMULATED trades that clear its
strategy. It has its OWN ledger — it never touches the manual simulator's bankroll and
never sends real orders. Stops on any limit (profit target, loss limit, staking budget,
trade cap) or when the balance can no longer cover the minimum stake.
"""

from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from typing import Dict, List

from PySide6.QtCore import QObject, Signal

from ..models.opportunity import Opportunity
from ..services.risk_engine import RiskEngine
from ..services.simulation_engine import SimulationEngine


@dataclass
class BotConfig:
    enabled: bool = False
    profile: str = "MODERATE"       # risk profile gating candidates ("ACTIVE" = follow screener)
    sport: str = "ALL"
    min_edge: float = 1.0           # %
    min_quality: float = 60.0
    min_liquidity: float = 500.0    # £
    # money
    deposit: float = 1000.0         # allocated capital
    stake_mode: str = "fixed"       # fixed | pct_liquidity | pct_deposit
    fixed_stake: float = 50.0       # £
    pct_liquidity: float = 10.0     # %
    pct_deposit: float = 5.0        # %
    min_stake: float = 10.0         # £ per trade
    max_stake: float = 100.0        # £ per trade
    # limits & stops
    slippage_pct: float = 1.5       # max execution slippage as % of stake (0 = perfect fills)
    cooldown_s: float = 3.0
    retrade_cooldown_s: float = 25.0
    max_trades: int = 50
    target_profit: float = 0.0      # £; 0 = off
    loss_limit: float = 0.0         # £; 0 = off
    max_total_staked: float = 0.0   # £; 0 = off

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "BotConfig":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def default_bot_presets() -> Dict[str, dict]:
    """Ready-made strategies the user can pick and then tweak."""
    def cfg(**kw) -> dict:
        base = BotConfig()
        for k, v in kw.items():
            setattr(base, k, v)
        base.enabled = False
        return base.to_dict()

    return {
        "Scalp": cfg(profile="RISKY", min_edge=0.3, min_quality=0, min_liquidity=100,
                     stake_mode="fixed", fixed_stake=25, min_stake=10, max_stake=50,
                     cooldown_s=1, deposit=1000),
        "High-liquidity": cfg(profile="MODERATE", min_liquidity=2000, stake_mode="pct_liquidity",
                              pct_liquidity=5, min_stake=25, max_stake=250, cooldown_s=3, deposit=2000),
        "Football low-risk": cfg(profile="SAFE", sport="Football", min_edge=1.5, min_quality=70,
                                 stake_mode="fixed", fixed_stake=50, min_stake=20, max_stake=100,
                                 cooldown_s=5, deposit=1500),
        "Conservative": cfg(profile="SAFE", min_edge=2.0, stake_mode="pct_deposit", pct_deposit=2,
                            min_stake=10, max_stake=100, cooldown_s=5, deposit=1000, loss_limit=100),
        "Aggressive": cfg(profile="RISKY", min_edge=0.2, stake_mode="pct_deposit", pct_deposit=10,
                          min_stake=25, max_stake=500, cooldown_s=1, deposit=2000),
    }


class AutoTrader(QObject):
    traded = Signal(object)       # SimResult
    logline = Signal(str)
    stats_changed = Signal()

    def __init__(self, sim: SimulationEngine, risk: RiskEngine, config: BotConfig) -> None:
        super().__init__()
        self.sim = sim
        self.risk = risk
        self.config = config
        self.count = 0
        self.wins = 0
        self.staked = 0.0
        self.profit = 0.0
        self.equity: List[float] = [0.0]
        self.trade_profits: List[float] = []
        self.trade_edges: List[float] = []
        self._last_ts = 0.0
        self._key_ts: Dict[str, float] = {}

    # -- balance -----------------------------------------------------------
    @property
    def balance(self) -> float:
        return self.config.deposit + self.profit

    # -- control -----------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        self.config.enabled = on
        self.logline.emit("BOT ENABLED" if on else "BOT DISABLED")
        self.stats_changed.emit()

    def reset_stats(self) -> None:
        self.count = self.wins = 0
        self.staked = self.profit = 0.0
        self.equity = [0.0]
        self.trade_profits = []
        self.trade_edges = []
        self._key_ts = {}
        self.logline.emit("BOT STATS RESET")
        self.stats_changed.emit()

    # -- derived metrics ---------------------------------------------------
    @property
    def win_rate(self) -> float:
        return (self.wins / self.count * 100) if self.count else 0.0

    @property
    def avg_profit(self) -> float:
        return (self.profit / self.count) if self.count else 0.0

    @property
    def roi(self) -> float:
        return (self.profit / self.config.deposit * 100) if self.config.deposit else 0.0

    @property
    def best_trade(self) -> float:
        return max(self.trade_profits, default=0.0)

    @property
    def worst_trade(self) -> float:
        return min(self.trade_profits, default=0.0)

    @property
    def max_drawdown(self) -> float:
        peak, dd = self.equity[0], 0.0
        for value in self.equity:
            peak = max(peak, value)
            dd = min(dd, value - peak)
        return dd  # <= 0

    # -- evaluation --------------------------------------------------------
    def _profile(self):
        if self.config.profile == "ACTIVE":
            return self.risk.active
        return self.risk.profiles.get(self.config.profile, self.risk.active)

    def _qualifies(self, opp: Opportunity, prof) -> bool:
        if self.config.sport != "ALL" and opp.market.sport.value != self.config.sport:
            return False
        return (self.risk._passes_profile(opp, prof)
                and opp.net_edge >= self.config.min_edge
                and opp.quality.total >= self.config.min_quality
                and opp.liquidity >= self.config.min_liquidity)

    def _size(self, opp: Opportunity) -> float:
        cfg = self.config
        if cfg.stake_mode == "pct_liquidity":
            stake = opp.liquidity * cfg.pct_liquidity / 100.0
        elif cfg.stake_mode == "pct_deposit":
            stake = cfg.deposit * cfg.pct_deposit / 100.0
        else:
            stake = cfg.fixed_stake
        stake = max(cfg.min_stake, min(stake, cfg.max_stake))     # clamp to the stake band
        stake = min(stake, self.balance, self.sim.max_executable(opp))
        return max(0.0, stake)

    def _stop_reason(self) -> str | None:
        cfg = self.config
        if self.count >= cfg.max_trades:
            return f"reached {cfg.max_trades}-trade cap"
        if self.balance < cfg.min_stake:
            return "deposit depleted"
        if cfg.target_profit > 0 and self.profit >= cfg.target_profit:
            return f"hit profit target £{cfg.target_profit:.0f}"
        if cfg.loss_limit > 0 and self.profit <= -cfg.loss_limit:
            return f"hit loss limit £{cfg.loss_limit:.0f}"
        if cfg.max_total_staked > 0 and self.staked >= cfg.max_total_staked:
            return f"reached staking budget £{cfg.max_total_staked:.0f}"
        return None

    def evaluate(self, opps: List[Opportunity]) -> None:
        """Consider placing ONE trade this tick — the best new qualifying arb."""
        cfg = self.config
        if not cfg.enabled:
            return
        now = time.monotonic()
        if now - self._last_ts < cfg.cooldown_s:
            return
        stop = self._stop_reason()
        if stop:
            self.set_enabled(False)
            self.logline.emit(f"BOT STOPPED — {stop}")
            return

        prof = self._profile()
        for opp in sorted(opps, key=lambda o: o.net_edge, reverse=True):
            if not self._qualifies(opp, prof):
                continue
            if now - self._key_ts.get(opp.key, 0.0) < cfg.retrade_cooldown_s:
                continue
            stake = self._size(opp)
            if stake < cfg.min_stake:
                continue  # can't meet the minimum on this opp — try the next
            res = self.sim.simulate(opp, stake)
            realized = self._settle(res.net_profit, stake, opp)  # apply execution slippage
            roi = (realized / stake * 100) if stake else 0.0
            self.count += 1
            self.wins += 1 if realized > 0 else 0
            self.staked += stake
            self.profit += realized
            self.equity.append(self.profit)
            self.trade_profits.append(realized)
            self.trade_edges.append(opp.net_edge)
            self._last_ts = now
            self._key_ts[opp.key] = now
            self.traded.emit(res)
            flag = "" if realized >= 0 else "  [SLIPPED]"
            self.logline.emit(
                f"BOT TRADE  {opp.market.event} — {opp.market.selection}  "
                f"£{stake:.0f} → {realized:+.2f} ({roi:.2f}%){flag}")
            self.stats_changed.emit()
            return  # one trade per tick keeps the stream watchable

    def _settle(self, expected: float, stake: float, opp: Opportunity) -> float:
        """Apply execution slippage: real fills sometimes miss the theoretical edge.

        More volatile markets slip more often; a bad enough slip turns the trade into
        a loss — which is what gives the drawdown gauge and win-rate real variation.
        """
        if self.config.slippage_pct <= 0:
            return expected
        chance = min(0.6, 0.2 + opp.volatility / 50.0)
        if random.random() >= chance:
            return expected
        return expected - stake * random.uniform(0.0, self.config.slippage_pct / 100.0)
