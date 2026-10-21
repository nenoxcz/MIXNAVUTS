"""A routable road network tied to real-world coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geo import SYNTHETIC_ANCHOR, LocalProjection
from .graph import Edge, RoadGraph
from .roadinfo import RoadDetails
from .synthetic import City, build_city, synthetic_details
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
    details: RoadDetails = field(default_factory=RoadDetails)  # lanes, cameras, lights
    _cells: dict[tuple[int, int], list[int]] = field(default_factory=dict, repr=False)
    _cell_m: float = 500.0
    _edge_cells: dict[tuple[int, int], list[int]] | None = field(default=None, repr=False)

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

    def _edge_xy(self, edge: Edge) -> list[tuple[float, float]]:
        return [self.projection.to_xy(lat, lon) for lat, lon in self.edge_shape(edge)]

    def edges_near(self, lat: float, lon: float, radius_m: float = 25.0) -> list[tuple[Edge, float, float]]:
        """Links passing within `radius_m`: (edge, offset along it in metres, distance)."""
        if self._edge_cells is None:
            self._edge_cells = {}
            for edge in self.graph.edges:
                xy = self._edge_xy(edge)
                xs, ys = [p[0] for p in xy], [p[1] for p in xy]
                for i in range(math.floor(min(xs) / self._cell_m), math.floor(max(xs) / self._cell_m) + 1):
                    for j in range(math.floor(min(ys) / self._cell_m), math.floor(max(ys) / self._cell_m) + 1):
                        self._edge_cells.setdefault((i, j), []).append(edge.id)
        px, py = self.projection.to_xy(lat, lon)
        cx, cy = self._cell(px, py)
        seen: set[int] = set()
        out = []
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for edge_id in self._edge_cells.get((i, j), ()):
                    if edge_id in seen:
                        continue
                    seen.add(edge_id)
                    edge = self.graph.edges[edge_id]
                    offset, distance = self.project(edge, px, py)
                    if distance <= radius_m:
                        out.append((edge, offset, distance))
        return sorted(out, key=lambda item: item[2])

    def project(self, edge: Edge, px: float, py: float) -> tuple[float, float]:
        """Closest point of the link to planar (px, py): (offset along the link in metres, distance)."""
        xy = self._edge_xy(edge)
        best = (0.0, math.inf)
        walked = 0.0
        for (ax, ay), (bx, by) in zip(xy, xy[1:], strict=False):
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (length * length)))
            distance = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if distance < best[1]:
                best = (walked + t * length, distance)
            walked += length
        scale = edge.length_m / walked if walked else 0.0
        return best[0] * scale, best[1]


def synthetic_network(seed: int = 7, city: City | None = None) -> RoadNetwork:
    city = city or build_city(seed=seed)
    snap = sorted(set(city.intersections) | set(city.graph.places().values()))
    details = synthetic_details(city, seed)
    return RoadNetwork("synthetic", city.graph, SYNTHETIC_ANCHOR, city.historical, snap, synthetic=True, details=details)
