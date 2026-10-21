"""Directed road network model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class RoadClass(StrEnum):
    MOTORWAY = "motorway"  # 고속도로
    RAMP = "ramp"  # IC·JC 연결로
    TRUNK = "trunk"  # 국도·자동차전용도로
    PRIMARY = "primary"  # 간선도로
    SECONDARY = "secondary"  # 보조간선
    LOCAL = "local"  # 이면도로


@dataclass(frozen=True)
class Node:
    id: int
    x: float  # planar metres
    y: float
    name: str = ""


@dataclass(frozen=True)
class Edge:
    id: int
    source: int
    target: int
    length_m: float
    road_class: RoadClass
    speed_limit_kmh: float
    toll_krw: int = 0
    curvature: float = 0.0  # 0 = straight, 1 = very winding
    name: str = ""
    ext_id: str = ""  # id in the source data, e.g. 표준링크ID

    @property
    def speed_limit_mps(self) -> float:
        return self.speed_limit_kmh / 3.6

    @property
    def free_flow_s(self) -> float:
        return self.length_m / self.speed_limit_mps


class RoadGraph:
    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}
        self.edges: list[Edge] = []
        self._out: dict[int, list[Edge]] = {}
        self._in: dict[int, list[Edge]] = {}
        self._by_name: dict[str, int] = {}
        self._by_ext: dict[str, Edge] = {}

    def add_node(self, x: float, y: float, name: str = "") -> int:
        node_id = len(self.nodes)
        self.nodes[node_id] = Node(node_id, x, y, name)
        self._out[node_id] = []
        self._in[node_id] = []
        if name:
            self._by_name[name] = node_id
        return node_id

    def add_edge(
        self,
        source: int,
        target: int,
        road_class: RoadClass,
        speed_limit_kmh: float,
        *,
        length_m: float | None = None,
        toll_krw: int = 0,
        curvature: float = 0.0,
        name: str = "",
        ext_id: str = "",
    ) -> Edge:
        if length_m is None:
            length_m = self.euclidean_m(source, target)
        edge = Edge(
            id=len(self.edges),
            source=source,
            target=target,
            length_m=length_m,
            road_class=road_class,
            speed_limit_kmh=speed_limit_kmh,
            toll_krw=toll_krw,
            curvature=curvature,
            name=name,
            ext_id=ext_id,
        )
        self.edges.append(edge)
        if ext_id:
            self._by_ext[ext_id] = edge
        self._out[source].append(edge)
        self._in[target].append(edge)
        return edge

    def add_road(self, a: int, b: int, road_class: RoadClass, speed_limit_kmh: float, **kwargs) -> tuple[Edge, Edge]:
        """Add a two-way road as a pair of directed edges."""
        return (
            self.add_edge(a, b, road_class, speed_limit_kmh, **kwargs),
            self.add_edge(b, a, road_class, speed_limit_kmh, **kwargs),
        )

    def out_edges(self, node_id: int) -> list[Edge]:
        return self._out[node_id]

    def in_edges(self, node_id: int) -> list[Edge]:
        return self._in[node_id]

    def euclidean_m(self, a: int, b: int) -> float:
        na, nb = self.nodes[a], self.nodes[b]
        return math.hypot(na.x - nb.x, na.y - nb.y)

    def resolve(self, ref: str | int) -> int:
        """Look a node up by name or numeric id."""
        if isinstance(ref, int):
            node_id = ref
        elif ref in self._by_name:
            return self._by_name[ref]
        elif ref.isdigit():
            node_id = int(ref)
        else:
            raise KeyError(f"unknown place: {ref!r}")
        if node_id not in self.nodes:
            raise KeyError(f"unknown node id: {node_id}")
        return node_id

    def edge_by_ext(self, ext_id: str) -> Edge | None:
        return self._by_ext.get(ext_id)

    def places(self) -> dict[str, int]:
        return dict(self._by_name)
