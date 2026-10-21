"""Personal preferences and the final pick of 3–5 routes to show."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .evaluate import RouteEvaluation, overlap


@dataclass(frozen=True)
class Preferences:
    """Generalised cost: everything is converted into seconds of driving."""

    name: str = "balanced"
    value_of_time_krw_per_h: float = 30_000.0  # 통행료 1만 원 ≈ 20분
    distance_s_per_km: float = 0.0  # fuel and wear
    highway_bias_s_per_km: float = 0.0  # < 0 prefers 고속도로
    winding_bonus_s_per_km: float = 0.0  # > 0 prefers 와인딩
    familiar_edges: frozenset[int] = field(default_factory=frozenset)
    familiar_discount: float = 0.0  # cost discount on a fully familiar route

    def cost(self, ev: RouteEvaluation) -> float:
        km = ev.distance_m / 1000.0
        cost = ev.duration_s
        cost += ev.toll_krw / self.value_of_time_krw_per_h * 3600.0
        cost += self.distance_s_per_km * km
        cost += self.highway_bias_s_per_km * km * ev.highway_share
        cost -= self.winding_bonus_s_per_km * km * ev.winding
        if self.familiar_edges and self.familiar_discount:
            cost *= 1.0 - self.familiar_discount * familiar_share(ev, self.familiar_edges)
        return cost


def familiar_share(ev: RouteEvaluation, familiar_edges: frozenset[int]) -> float:
    known = sum(edge.length_m for edge in ev.route.edges if edge.id in familiar_edges)
    return known / ev.distance_m if ev.distance_m else 0.0


MODES: dict[str, Preferences] = {
    "fastest": Preferences("fastest", value_of_time_krw_per_h=math.inf),
    "balanced": Preferences("balanced"),
    "economy": Preferences("economy", value_of_time_krw_per_h=6_000.0, distance_s_per_km=6.0),
    "highway": Preferences("highway", highway_bias_s_per_km=-30.0),
    "scenic": Preferences("scenic", winding_bonus_s_per_km=90.0, highway_bias_s_per_km=20.0),
}


@dataclass(frozen=True)
class Suggestion:
    evaluation: RouteEvaluation
    cost: float
    labels: tuple[str, ...]


def select_routes(
    evaluations: Sequence[RouteEvaluation],
    prefs: Preferences = MODES["balanced"],
    *,
    k: int = 4,
    max_overlap: float = 0.7,
    max_duration_ratio: float = 1.5,
) -> list[Suggestion]:
    """Pick up to `k` routes that are good and different from each other.

    The preferred route and the earliest arrival are always shown. Then the
    shortest and the toll-free route get a chance, then everything else by
    cost. A route is skipped if it shares more than `max_overlap` of its
    distance with one already picked, or takes more than
    `max_duration_ratio` × the fastest.
    """
    if not evaluations:
        return []
    fastest = min(evaluations, key=lambda ev: ev.arrival)
    viable = [ev for ev in evaluations if ev.duration_s <= fastest.duration_s * max_duration_ratio]
    ranked = sorted(viable, key=prefs.cost)
    best = ranked[0]
    shortest = min(viable, key=lambda ev: (ev.distance_m, ev.arrival))
    tolled = any(ev.toll_krw for ev in viable)
    toll_free = [ev for ev in ranked if ev.toll_krw == 0] if tolled else []

    picks: list[RouteEvaluation] = []
    for ev in [best, fastest]:
        if all(ev is not p for p in picks) and len(picks) < k:
            picks.append(ev)
    for ev in [shortest, *toll_free[:1], *ranked]:
        if len(picks) >= k:
            break
        if any(ev is p for p in picks):
            continue
        if all(overlap(ev.route.edges, p.route.edges) <= max_overlap for p in picks):
            picks.append(ev)

    def labels(ev: RouteEvaluation) -> tuple[str, ...]:
        tags = []
        if ev is best:
            tags.append("추천")
        if ev.arrival == fastest.arrival:
            tags.append("최단시간")
        if ev.distance_m == shortest.distance_m:
            tags.append("최단거리")
        if tolled and ev.toll_krw == 0:
            tags.append("무료도로")
        if ev.highway_share >= 0.4:
            tags.append("고속도로")
        if ev.winding >= 0.3:
            tags.append("와인딩")
        if prefs.familiar_edges and familiar_share(ev, prefs.familiar_edges) >= 0.6:
            tags.append("익숙한 길")
        return tuple(tags) or ("대안",)

    picks.sort(key=prefs.cost)
    return [Suggestion(ev, prefs.cost(ev), labels(ev)) for ev in picks]
