"""A routable road network tied to real-world coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geo import SYNTHETIC_ANCHOR, LocalProjection
from .graph import Edge, RoadGraph
from .synthetic import City, build_city
from .traffic import TrafficModel


@dataclass
class RoadNetwork:
    name: str
    graph: RoadGraph
    projection: LocalProjection
    historical: TrafficModel
    snap_nodes: list[int]  # where an origin or destination may snap to
    synthetic: bool = False
    shapes: dict[int, list[tuple[float, float]]] = field(default_factory=dict)  # edge id → (lat, lon) polyline
    _cells: dict[tuple[int, int], list[int]] = field(default_factory=dict, repr=False)
    _cell_m: float = 500.0

    def __post_init__(self) -> None:
        for node_id in self.snap_nodes:
            node = self.graph.nodes[node_id]
            self._cells.setdefault(self._cell(node.x, node.y), []).append(node_id)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return math.floor(x / self._cell_m), math.floor(y / self._cell_m)

    def latlon(self, node_id: int) -> tuple[float, float]:
        node = self.graph.nodes[node_id]
        return self.projection.to_latlon(node.x, node.y)

    def nearest(self, lat: float, lon: float, max_m: float = 5_000.0) -> int | None:
        x, y = self.projection.to_xy(lat, lon)
        cx, cy = self._cell(x, y)
        reach = math.ceil(max_m / self._cell_m)
        best, best_d = None, max_m
        for ring in range(reach + 1):
            for i in range(cx - ring, cx + ring + 1):
                for j in range(cy - ring, cy + ring + 1):
                    if max(abs(i - cx), abs(j - cy)) != ring:
                        continue
                    for node_id in self._cells.get((i, j), ()):
                        node = self.graph.nodes[node_id]
                        d = math.hypot(node.x - x, node.y - y)
                        if d < best_d:
                            best, best_d = node_id, d
            if best is not None and best_d <= ring * self._cell_m:
                break
        return best

    def edge_shape(self, edge: Edge) -> list[tuple[float, float]]:
        """The edge as a (lat, lon) polyline, endpoints included."""
        shape = self.shapes.get(edge.id)
        return shape if shape else [self.latlon(edge.source), self.latlon(edge.target)]

    def places(self) -> dict[str, int]:
        return self.graph.places()


def synthetic_network(seed: int = 7, city: City | None = None) -> RoadNetwork:
    city = city or build_city(seed=seed)
    snap = sorted(set(city.intersections) | set(city.graph.places().values()))
    return RoadNetwork("synthetic", city.graph, SYNTHETIC_ANCHOR, city.historical, snap, synthetic=True)
