"""Live traffic feeds: what the engine knows right now."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from .synthetic import City, Day, observed_edges
from .traffic import Incident, observe


@dataclass(frozen=True)
class LiveSnapshot:
    """Observed speeds and incidents. Incident times are seconds since `day_start`."""

    observed_mps: dict[int, float] = field(default_factory=dict)
    incidents: list[Incident] = field(default_factory=list)
    as_of: float | None = None  # epoch seconds of the newest observation
    source: str = "none"


class LiveFeed(Protocol):
    def snapshot(self, now: float, day_start: float) -> LiveSnapshot:
        """Everything known at epoch `now`; `day_start` is local midnight of the trip."""


class NoLiveFeed:
    def snapshot(self, now: float, day_start: float) -> LiveSnapshot:
        return LiveSnapshot()


class SyntheticFeed:
    """Sensor readings and incident reports taken from a synthetic day."""

    def __init__(self, city: City, day: Day, seed: int = 1) -> None:
        self.city = city
        self.day = day
        self.seed = seed

    def snapshot(self, now: float, day_start: float) -> LiveSnapshot:
        t = now - day_start
        rng = random.Random(f"{self.seed}:{int(t // 300)}")  # stable within a 5-minute polling window
        readings = observe(self.city.graph, self.day.truth, t, observed_edges(self.city, rng))
        observed = {i: v * max(0.5, rng.gauss(1.0, 0.06)) for i, v in readings.items()}
        incidents = [
            Incident(inc.edge_ids, inc.start, t + (inc.end - t) * rng.uniform(0.6, 1.5), inc.speed_factor)
            for inc in self.day.incidents
            if inc.start <= t < inc.end
        ]
        return LiveSnapshot(observed, incidents, now, "synthetic")
