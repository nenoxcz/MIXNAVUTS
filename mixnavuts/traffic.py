"""Time-dependent traffic models.

Every model exposes a speed that is piecewise constant in time, and travel
times are obtained by integrating distance over those pieces. Integrating
speed (instead of reading the speed once at the entry time) keeps the FIFO
property: entering an edge later never gets you out earlier. Time-dependent
Dijkstra is only exact under FIFO.

Times are seconds since midnight of day 0. Daily profiles wrap every 24 h.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .graph import Edge, RoadClass, RoadGraph

DAY_S = 86_400.0
_MAX_STEPS = 100_000


class TrafficModel(ABC):
    bucket_s: float = 900.0

    @abstractmethod
    def speed_mps(self, edge: Edge, t: float) -> float:
        """Speed on `edge` during the piece of time that contains `t`."""

    def next_change(self, edge: Edge, t: float) -> float:
        """First time after `t` at which `speed_mps(edge, ·)` may change."""
        return (math.floor(t / self.bucket_s) + 1) * self.bucket_s

    def travel_time(self, edge: Edge, t_enter: float) -> float:
        remaining = edge.length_m
        t = t_enter
        for _ in range(_MAX_STEPS):
            v = self.speed_mps(edge, t)
            boundary = self.next_change(edge, t)
            if v > 0:
                reach = v * (boundary - t)
                if reach >= remaining:
                    return t + remaining / v - t_enter
                remaining -= reach
            t = boundary
        return math.inf


class FreeFlowTraffic(TrafficModel):
    def speed_mps(self, edge: Edge, t: float) -> float:
        return edge.speed_limit_mps


class ProfileTraffic(TrafficModel):
    """Speed factor (fraction of the speed limit) per edge per time bucket.

    `profiles` maps edge id -> one factor per bucket of the day. Edges without
    their own profile fall back to `class_profiles`, then to 1.0.
    """

    def __init__(
        self,
        profiles: Mapping[int, Sequence[float]] | None = None,
        class_profiles: Mapping[RoadClass, Sequence[float]] | None = None,
        bucket_s: float = 900.0,
    ) -> None:
        self.bucket_s = bucket_s
        self.buckets_per_day = round(DAY_S / bucket_s)
        self.profiles = dict(profiles or {})
        self.class_profiles = dict(class_profiles or {})
        for profile in [*self.profiles.values(), *self.class_profiles.values()]:
            if len(profile) != self.buckets_per_day:
                raise ValueError(f"profile needs {self.buckets_per_day} buckets, got {len(profile)}")

    def factor(self, edge: Edge, t: float) -> float:
        profile = self.profiles.get(edge.id) or self.class_profiles.get(edge.road_class)
        if profile is None:
            return 1.0
        return profile[int(t // self.bucket_s) % self.buckets_per_day]

    def speed_mps(self, edge: Edge, t: float) -> float:
        return edge.speed_limit_mps * self.factor(edge, t)


class SnapshotTraffic(TrafficModel):
    """Today's speeds, frozen: what a plain "current traffic" ETA assumes."""

    def __init__(self, historical: TrafficModel, now: float, observed_mps: Mapping[int, float] | None = None) -> None:
        self.historical = historical
        self.now = now
        self.observed = dict(observed_mps or {})
        self.bucket_s = DAY_S

    def speed_mps(self, edge: Edge, t: float) -> float:
        observed = self.observed.get(edge.id)
        return observed if observed is not None else self.historical.speed_mps(edge, self.now)


@dataclass(frozen=True)
class Incident:
    """돌발상황: a speed cap on some edges for a time window.

    `speed_factor` is relative to the speed limit; 0 means closed (traffic
    queues until `end`).
    """

    edge_ids: frozenset[int]
    start: float
    end: float
    speed_factor: float


class PredictiveTraffic(TrafficModel):
    """Live observations blended into the historical profile.

    At `now`, an observed edge runs at `observed / historical` times its usual
    speed. That deviation decays towards the historical profile with time
    constant `tau_s`: congestion that exists now tells you a lot about the
    next ten minutes and little about the next two hours.

    Known incidents override the blend inside their window; once an incident
    is expected to clear, its edges return to the historical profile.
    """

    MAX_FACTOR = 1.2

    def __init__(
        self,
        historical: ProfileTraffic,
        now: float,
        observed_mps: Mapping[int, float] | None = None,
        tau_s: float = 2_400.0,
        incidents: Sequence[Incident] = (),
        bucket_s: float = 300.0,
    ) -> None:
        if historical.bucket_s % bucket_s:
            raise ValueError("bucket_s must divide the historical bucket size")
        self.historical = historical
        self.now = now
        self.tau_s = tau_s
        self.bucket_s = bucket_s
        self.incidents = list(incidents)
        self._incidents_by_edge: dict[int, list[Incident]] = {}
        for incident in self.incidents:
            for edge_id in incident.edge_ids:
                self._incidents_by_edge.setdefault(edge_id, []).append(incident)
        self._ratio: dict[int, float] = {}
        self._observed = dict(observed_mps or {})

    def _deviation(self, edge: Edge) -> float:
        ratio = self._ratio.get(edge.id)
        if ratio is None:
            observed = self._observed.get(edge.id)
            if observed is None:
                ratio = 1.0
            else:
                usual = self.historical.speed_mps(edge, self.now)
                ratio = observed / usual if usual > 0 else 1.0
            self._ratio[edge.id] = ratio
        return ratio

    def speed_mps(self, edge: Edge, t: float) -> float:
        incidents = self._incidents_by_edge.get(edge.id)
        if incidents:
            for incident in incidents:
                if incident.start <= t < incident.end:
                    return edge.speed_limit_mps * incident.speed_factor
            if any(t >= incident.end > self.now for incident in incidents):
                # The live slowdown was the incident; it is gone now.
                return self.historical.speed_mps(edge, t)
        base = self.historical.speed_mps(edge, t)
        ratio = self._deviation(edge)
        if ratio != 1.0:
            piece_start = math.floor(t / self.bucket_s) * self.bucket_s
            ahead = max(0.0, piece_start - self.now)
            base *= 1.0 + (ratio - 1.0) * math.exp(-ahead / self.tau_s)
        return min(base, edge.speed_limit_mps * self.MAX_FACTOR)

    def next_change(self, edge: Edge, t: float) -> float:
        boundary = super().next_change(edge, t)
        for incident in self._incidents_by_edge.get(edge.id, ()):
            for moment in (incident.start, incident.end):
                if t < moment < boundary:
                    boundary = moment
        return boundary


def observe(graph: RoadGraph, traffic: TrafficModel, t: float, edge_ids: Sequence[int] | None = None) -> dict[int, float]:
    """Read speeds from a model, e.g. a ground-truth day, as a sensor would."""
    ids = range(len(graph.edges)) if edge_ids is None else edge_ids
    return {i: traffic.speed_mps(graph.edges[i], t) for i in ids}


def typical_class_profiles(bucket_s: float = 900.0) -> dict[RoadClass, list[float]]:
    """Generic weekday rush-hour shape per road class.

    A stand-in until profiles learned from archived speeds exist for a link.
    """
    depth = {  # (morning, evening) share of speed lost at the peak
        RoadClass.MOTORWAY: (0.45, 0.45),
        RoadClass.RAMP: (0.40, 0.40),
        RoadClass.TRUNK: (0.35, 0.35),
        RoadClass.PRIMARY: (0.40, 0.40),
        RoadClass.SECONDARY: (0.30, 0.30),
        RoadClass.LOCAL: (0.15, 0.15),
    }
    buckets = round(DAY_S / bucket_s)
    out = {}
    for road_class, (am, pm) in depth.items():
        row = []
        for b in range(buckets):
            h = (b + 0.5) * bucket_s / 3600.0
            loss = am * math.exp(-0.5 * ((h - 8.25) / 0.75) ** 2) + pm * math.exp(-0.5 * ((h - 18.5) / 1.0) ** 2)
            loss += 0.06 * math.exp(-0.5 * ((h - 13.0) / 2.0) ** 2)
            row.append(max(0.15, 1.0 - loss))
        out[road_class] = row
    return out
