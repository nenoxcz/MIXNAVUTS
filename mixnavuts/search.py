"""Shortest-path searches on a RoadGraph."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass

from .graph import Edge, RoadGraph
from .traffic import TrafficModel

WeightFn = Callable[[Edge], float]


@dataclass(frozen=True)
class Tree:
    """Result of a one-to-all search.

    Forward trees store, per node, the edge used to reach it from the root.
    Backward trees store the edge used to leave it towards the root.
    """

    root: int
    dist: dict[int, float]
    via_edge: dict[int, Edge]
    backward: bool


def dijkstra(
    graph: RoadGraph,
    root: int,
    weight: WeightFn,
    *,
    backward: bool = False,
    target: int | None = None,
) -> Tree:
    dist = {root: 0.0}
    via_edge: dict[int, Edge] = {}
    heap = [(0.0, root)]
    done: set[int] = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u == target:
            break
        for edge in graph.in_edges(u) if backward else graph.out_edges(u):
            v = edge.source if backward else edge.target
            nd = d + weight(edge)
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                via_edge[v] = edge
                heapq.heappush(heap, (nd, v))
    return Tree(root, dist, via_edge, backward)


def path_to(tree: Tree, node: int) -> list[Edge] | None:
    """Edges between the tree root and `node`, in driving order."""
    if node not in tree.dist:
        return None
    edges: list[Edge] = []
    while node != tree.root:
        edge = tree.via_edge[node]
        edges.append(edge)
        node = edge.target if tree.backward else edge.source
    if not tree.backward:
        edges.reverse()
    return edges


def shortest_path(graph: RoadGraph, source: int, target: int, weight: WeightFn) -> list[Edge] | None:
    return path_to(dijkstra(graph, source, weight, target=target), target)


def td_tree(
    graph: RoadGraph,
    source: int,
    traffic: TrafficModel,
    depart: float,
    *,
    target: int | None = None,
) -> Tree:
    """Earliest-arrival search for a departure time. Exact for FIFO models.

    `dist` holds the travel time from `depart`, not the clock time.
    """
    dist = {source: 0.0}
    via_edge: dict[int, Edge] = {}
    heap = [(0.0, source)]
    done: set[int] = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u == target:
            break
        t = depart + d
        for edge in graph.out_edges(u):
            nd = d + traffic.travel_time(edge, t)
            if nd < dist.get(edge.target, math.inf):
                dist[edge.target] = nd
                via_edge[edge.target] = edge
                heapq.heappush(heap, (nd, edge.target))
    return Tree(source, dist, via_edge, backward=False)


def td_fastest_path(
    graph: RoadGraph,
    source: int,
    target: int,
    traffic: TrafficModel,
    depart: float,
) -> tuple[list[Edge], float] | None:
    """Earliest-arrival path and its arrival time."""
    tree = td_tree(graph, source, traffic, depart, target=target)
    edges = path_to(tree, target)
    if edges is None:
        return None
    return edges, depart + tree.dist[target]
