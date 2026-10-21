"""Candidate route generation: from a few seeds to hundreds of alternatives.

Stage 1 — profile seeds: one route per cost profile (최단시간, 최단거리,
          고속도로 우선/회피, 무료도로, 간선 위주, 와인딩).
Stage 2 — penalty method: repeatedly penalise edges of routes already found
          and search again, pushing the search onto other corridors.
Stage 3 — via-node method: one forward tree from the origin and one backward
          tree to the destination give a route s→v→t through every node v
          for the price of two searches. This is where the hundreds come from.

Generation uses static edge weights, so it can be fast. Each edge is weighed
at the time the fastest route would reach it, which is close to when any
reasonable alternative reaches it too. Exact time-dependent ETAs are computed
afterwards in `evaluate`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .evaluate import Route
from .graph import Edge, RoadClass, RoadGraph
from .search import Tree, dijkstra, path_to, shortest_path, td_tree
from .traffic import TrafficModel

_HIGHWAY = {RoadClass.MOTORWAY, RoadClass.RAMP}
_MAIN = {RoadClass.MOTORWAY, RoadClass.RAMP, RoadClass.TRUNK, RoadClass.PRIMARY}


@dataclass(frozen=True)
class CandidateConfig:
    stretch: float = 0.6  # via routes up to (1 + stretch) × fastest
    max_via: int = 400
    penalty_rounds: int = 10
    penalty_factor: float = 1.35


def _profiles(w: Callable[[Edge], float]) -> dict[str, Callable[[Edge], float]]:
    return {
        "shortest": lambda e: e.length_m,
        "highway": lambda e: w(e) * (0.75 if e.road_class in _HIGHWAY else 1.0),
        "no_highway": lambda e: w(e) * (4.0 if e.road_class in _HIGHWAY else 1.0),
        "toll_free": lambda e: w(e) + (1e6 if e.toll_krw else 0.0),
        "main_roads": lambda e: w(e) * (1.0 if e.road_class in _MAIN else 1.4),
        "winding": lambda e: w(e) * (1.0 - 0.6 * e.curvature),
    }


def _is_simple(edges: list[Edge]) -> bool:
    seen = {edges[0].source} if edges else set()
    for edge in edges:
        if edge.target in seen:
            return False
        seen.add(edge.target)
    return True


class _Pool:
    def __init__(self) -> None:
        self.routes: dict[tuple[int, ...], set[str]] = {}
        self.edges: dict[tuple[int, ...], list[Edge]] = {}

    def add(self, edges: list[Edge] | None, source: str) -> bool:
        if not edges:
            return False
        key = tuple(edge.id for edge in edges)
        is_new = key not in self.routes
        if is_new:
            self.edges[key] = edges
        self.routes.setdefault(key, set()).add(source)
        return is_new

    def build(self) -> list[Route]:
        return [Route(tuple(self.edges[key]), frozenset(tags)) for key, tags in self.routes.items()]


def generate_candidates(
    graph: RoadGraph,
    source: int,
    target: int,
    traffic: TrafficModel,
    depart: float,
    config: CandidateConfig | None = None,
) -> list[Route]:
    config = config or CandidateConfig()
    forward = td_tree(graph, source, traffic, depart)
    if target not in forward.dist:
        return []

    def w(edge: Edge) -> float:
        reached = forward.dist.get(edge.source)
        return traffic.travel_time(edge, depart + reached) if reached is not None else edge.free_flow_s

    weights: dict[int, float] = {}

    def cached_w(edge: Edge) -> float:
        value = weights.get(edge.id)
        if value is None:
            value = weights[edge.id] = w(edge)
        return value

    pool = _Pool()
    pool.add(path_to(forward, target), "fastest")
    for name, weight in _profiles(cached_w).items():
        pool.add(shortest_path(graph, source, target, weight), name)

    penalty: dict[int, float] = {}

    def punish(edges: list[Edge]) -> None:
        for edge in edges:
            penalty[edge.id] = penalty.get(edge.id, 1.0) * config.penalty_factor

    for edges in list(pool.edges.values()):
        punish(edges)
    for _ in range(config.penalty_rounds):
        found = shortest_path(graph, source, target, lambda e: cached_w(e) * penalty.get(e.id, 1.0))
        if found is None:
            break
        pool.add(found, "penalty")
        punish(found)

    backward = dijkstra(graph, target, cached_w, backward=True)
    _add_via_routes(pool, forward, backward, source, target, config)
    return pool.build()


def _add_via_routes(
    pool: _Pool,
    forward: Tree,
    backward: Tree,
    source: int,
    target: int,
    config: CandidateConfig,
) -> None:
    best = forward.dist[target]
    limit = best * (1.0 + config.stretch)
    via_nodes = sorted(
        (forward.dist[v] + backward.dist[v], v) for v in forward.dist if v in backward.dist and v not in (source, target)
    )
    added = 0
    for cost, v in via_nodes:
        if cost > limit or added >= config.max_via:
            break
        head, tail = path_to(forward, v), path_to(backward, v)
        if head is None or tail is None:
            continue
        edges = head + tail
        if _is_simple(edges) and pool.add(edges, "via"):
            added += 1


def candidate_stats(routes: list[Route]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for route in routes:
        for tag in route.sources:
            stats[tag] = stats.get(tag, 0) + 1
    return dict(sorted(stats.items(), key=lambda item: (-item[1], item[0])))
