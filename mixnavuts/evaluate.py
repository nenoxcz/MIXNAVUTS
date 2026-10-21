"""Drive a route through a traffic model to get its ETA and attributes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .graph import Edge, RoadClass
from .traffic import TrafficModel

_HIGHWAY = {RoadClass.MOTORWAY, RoadClass.RAMP}


@dataclass(frozen=True)
class Route:
    edges: tuple[Edge, ...]
    sources: frozenset[str]  # which generators produced it

    @property
    def key(self) -> tuple[int, ...]:
        return tuple(edge.id for edge in self.edges)

    @property
    def length_m(self) -> float:
        return sum(edge.length_m for edge in self.edges)


@dataclass(frozen=True)
class RouteEvaluation:
    route: Route
    depart: float
    arrival: float
    distance_m: float
    toll_krw: int
    free_flow_s: float
    highway_share: float  # fraction of distance on 고속도로·연결로
    winding: float  # distance-weighted curvature, 0..1

    @property
    def duration_s(self) -> float:
        return self.arrival - self.depart

    @property
    def delay_s(self) -> float:
        return self.duration_s - self.free_flow_s


def evaluate(route: Route, traffic: TrafficModel, depart: float) -> RouteEvaluation:
    t = depart
    toll = 0
    free_flow = highway_m = winding_m = 0.0
    for edge in route.edges:
        t += traffic.travel_time(edge, t)
        toll += edge.toll_krw
        free_flow += edge.free_flow_s
        if edge.road_class in _HIGHWAY:
            highway_m += edge.length_m
        winding_m += edge.curvature * edge.length_m
    distance = route.length_m
    return RouteEvaluation(
        route=route,
        depart=depart,
        arrival=t,
        distance_m=distance,
        toll_krw=toll,
        free_flow_s=free_flow,
        highway_share=highway_m / distance if distance else 0.0,
        winding=winding_m / distance if distance else 0.0,
    )


def overlap(a: Sequence[Edge], b: Sequence[Edge]) -> float:
    """Shared distance as a fraction of the shorter route."""
    a_ids = {edge.id for edge in a}
    shared = sum(edge.length_m for edge in b if edge.id in a_ids)
    shorter = min(sum(e.length_m for e in a), sum(e.length_m for e in b))
    return shared / shorter if shorter else 1.0
