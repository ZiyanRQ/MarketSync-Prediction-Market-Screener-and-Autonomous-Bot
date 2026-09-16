"""Active risk profiles + local filtering.

Supports MULTIPLE enabled profiles at once: an opportunity is surfaced if it clears
ANY enabled profile (a union). The most conservative enabled profile is the
"primary" — it drives the buffer/buffered-edge shown on each row. Emits on change so
the UI recomputes locally, never by refetching data.
"""

from __future__ import annotations

from typing import Iterable, List, Set

from PySide6.QtCore import QObject, Signal

from ..models.opportunity import Opportunity
from ..models.risk_profile import RiskProfile, default_profiles


class RiskEngine(QObject):
    profile_changed = Signal(str)      # primary profile name
    profiles_changed = Signal()        # the set of presets was edited
    enabled_changed = Signal(set)      # which profiles are enabled

    def __init__(self) -> None:
        super().__init__()
        self.profiles = default_profiles()
        self.enabled: Set[str] = {"MODERATE"}

    # -- primary / active --------------------------------------------------
    @property
    def active_name(self) -> str:
        candidates = [n for n in self.enabled if n in self.profiles]
        if not candidates:
            return "MODERATE" if "MODERATE" in self.profiles else next(iter(self.profiles))
        # Most conservative = biggest buffer, then strictest min-net.
        return max(candidates, key=lambda n: (self.profiles[n].safety_buffer,
                                              self.profiles[n].min_net_edge))

    @property
    def active(self) -> RiskProfile:
        return self.profiles[self.active_name]

    # -- enabling ----------------------------------------------------------
    def set_enabled(self, names: Iterable[str]) -> None:
        valid = {n for n in names if n in self.profiles}
        self.enabled = valid or {self.active_name}
        self.enabled_changed.emit(set(self.enabled))
        self.profile_changed.emit(self.active_name)

    def toggle(self, name: str, on: bool) -> None:
        updated = set(self.enabled)
        updated.add(name) if on else updated.discard(name)
        self.set_enabled(updated or {name})

    def set_active(self, name: str) -> None:
        """Single-select convenience (command palette)."""
        if name in self.profiles:
            self.set_enabled({name})

    # -- editing -----------------------------------------------------------
    def upsert(self, profile: RiskProfile) -> None:
        self.profiles[profile.name] = profile
        self.profiles_changed.emit()

    def delete(self, name: str) -> None:
        prof = self.profiles.get(name)
        if prof and not prof.builtin:
            del self.profiles[name]
            self.enabled.discard(name)
            if not self.enabled:
                self.enabled = {"MODERATE"}
            self.profiles_changed.emit()
            self.profile_changed.emit(self.active_name)

    def restore_defaults(self) -> None:
        self.profiles = default_profiles()
        self.enabled = {"MODERATE"}
        self.profiles_changed.emit()
        self.profile_changed.emit(self.active_name)

    # -- application -------------------------------------------------------
    def apply(self, opps: List[Opportunity]) -> None:
        """Recompute buffer-adjusted fields against the primary profile."""
        prof = self.active
        for opp in opps:
            opp.apply_buffer(prof.safety_buffer, prof.min_net_edge)

    def _passes_profile(self, opp: Opportunity, prof: RiskProfile) -> bool:
        return (opp.net_edge >= prof.min_net_edge
                and (opp.net_edge - prof.safety_buffer) >= 0
                and opp.liquidity >= prof.min_liquidity
                and opp.price_age <= prof.max_price_age
                and opp.quality.total >= prof.min_quality
                and opp.volatility <= prof.max_volatility)

    def passes(self, opp: Opportunity) -> bool:
        """True if the opportunity clears ANY enabled profile."""
        return any(self._passes_profile(opp, self.profiles[n]) for n in self.enabled
                   if n in self.profiles)
