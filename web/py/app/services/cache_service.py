"""Tiny in-memory cache with hit/miss accounting.

Stands in for the caching layer a live integration would use to avoid duplicate
exchange requests. Tracks enough stats to drive the API Usage panel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass
class CacheService:
    ttl: float = 5.0
    _store: Dict[str, Tuple[float, Any]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    duplicates_avoided: int = 0

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry and (time.monotonic() - entry[0]) < self.ttl:
            self.hits += 1
            self.duplicates_avoided += 1
            return entry[1]
        self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total else 0.0
