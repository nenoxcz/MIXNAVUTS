"""정밀도로지도 (국토지리정보원 HD map): lane counts, lane guidance, traffic lights and speed bumps.

The HD map is free from 국토지리정보원 (국토정보플랫폼 → 정밀도로지도) as shapefiles:

  A2_LINK          차로 중심선 링크: ID, LaneNo, FromNodeID, ToNodeID, ITSLinkID, Length, LinkType
  C1_TRAFFICLIGHT  신호등, linked to a lane link by LinkID
  C4_SPEEDBUMP     과속방지턱, linked by LinkID

ITSLinkID is the 표준링크ID, so the HD map attaches to a network loaded from
국가표준노드링크 (`load_nodelink`) without any map matching:

  - lane count of a standard link = highest LaneNo among its lane links
  - lanes to use at a maneuver from link A to link B = lanes whose last lane
    link on A connects (through junction connectors) to a lane link on B
  - lights and bumps become alerts along the route

Coverage is limited to the roads NGII has surveyed (motorways, many national
roads, some cities); elsewhere guidance falls back to 표준노드링크 LANES and
rule-based lane hints. Field names follow the published layout: check a
download with `python -m mixnavuts hdmap-info DIR`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..graph import Edge
from ..network import RoadNetwork
from ..roadinfo import RoadFeature
from .shp import describe, field, find_layer, number, records
from .tm import epsg_of_shapefile, to_wgs84

LAYERS = {"links": "A2_LINK", "lights": "C1_TRAFFICLIGHT", "bumps": "C4_SPEEDBUMP"}


@dataclass(frozen=True)
class LaneLink:
    id: str
    from_node: str
    to_node: str
    lane_no: int
    its_link: str
    length_m: float


class LaneGraph:
    """Lane-level connectivity, used to answer "which lanes lead from link A to link B"."""

    def __init__(self, links: Iterable[LaneLink], junction_budget_m: float = 300.0) -> None:
        self.links = {link.id: link for link in links}
        self.by_its: dict[str, list[LaneLink]] = defaultdict(list)
        self.outgoing: dict[str, list[LaneLink]] = defaultdict(list)
        for link in self.links.values():
            if link.its_link:
                self.by_its[link.its_link].append(link)
            self.outgoing[link.from_node].append(link)
        self.junction_budget_m = junction_budget_m
        self._memo: dict[tuple[str, str], tuple[int, ...] | None] = {}

    def lane_count(self, its_link: str) -> int:
        return max((link.lane_no for link in self.by_its.get(its_link, ())), default=0)

    def exit_lanes(self, its_link: str) -> list[LaneLink]:
        """Lane links of a standard link that leave it (the lanes at its end)."""
        return [
            link
            for link in self.by_its.get(its_link, ())
            if not any(nxt.its_link == its_link for nxt in self.outgoing.get(link.to_node, ()))
        ]

    def recommend(self, from_its: str, to_its: str) -> tuple[int, ...] | None:
        key = (from_its, to_its)
        if key not in self._memo:
            lanes = {
                lane.lane_no for lane in self.exit_lanes(from_its) if lane.lane_no > 0 and self._reaches(lane, from_its, to_its)
            }
            self._memo[key] = tuple(sorted(lanes)) or None
        return self._memo[key]

    def _reaches(self, lane: LaneLink, from_its: str, to_its: str) -> bool:
        stack = [(lane.to_node, self.junction_budget_m)]
        seen: set[str] = set()
        while stack:
            node, budget = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for nxt in self.outgoing.get(node, ()):
                if nxt.its_link == to_its:
                    return True
                # junction connectors carry no ITSLinkID (or the approach link's own)
                if nxt.its_link in ("", from_its) and budget - nxt.length_m > 0:
                    stack.append((nxt.to_node, budget - nxt.length_m))
        return False


def lane_links(rows: Iterable[tuple[dict, list[tuple[float, float]]]]) -> list[LaneLink]:
    out = []
    for record, _points in rows:
        link_id = field(record, "ID", "LinkID")
        if not link_id:
            continue
        out.append(
            LaneLink(
                id=link_id,
                from_node=field(record, "FromNodeID", "F_NODE"),
                to_node=field(record, "ToNodeID", "T_NODE"),
                lane_no=int(number(record, "LaneNo")),
                its_link=field(record, "ITSLinkID", "ITS_LINK_ID"),
                length_m=number(record, "Length"),
            )
        )
    return out


def attach_lanes(network: RoadNetwork, graph: LaneGraph) -> int:
    """Lane counts from the HD map, and the lane graph as the network's lane resolver."""
    attached = 0
    for its_link in graph.by_its:
        edge = network.graph.edge_by_ext(its_link)
        count = graph.lane_count(its_link)
        if edge is not None and count > 0:
            network.details.lane_count[edge.id] = count
            attached += 1

    def resolve(a: Edge, b: Edge) -> tuple[int, ...] | None:
        return graph.recommend(a.ext_id, b.ext_id) if a.ext_id and b.ext_id else None

    network.details.lane_resolver = resolve
    return attached


def attach_points(
    network: RoadNetwork,
    graph: LaneGraph,
    rows: Iterable[tuple[dict, list[tuple[float, float]]]],
    kind: str,
    epsg: int,
) -> int:
    """Point-like features (lights, bumps) referenced by lane LinkID, placed along the standard link."""
    attached = 0
    for record, points in rows:
        lane = graph.links.get(field(record, "LinkID", "LINK_ID"))
        edge = network.graph.edge_by_ext(lane.its_link) if lane else None
        if edge is None or not points:
            continue
        x = sum(p[0] for p in points) / len(points)
        y = sum(p[1] for p in points) / len(points)
        lat, lon = to_wgs84(x, y, epsg)
        offset, _ = network.project(edge, *network.projection.to_xy(lat, lon))
        network.details.add_feature(edge.id, RoadFeature(kind, offset))
        attached += 1
    return attached


def load_hdmap(
    network: RoadNetwork, directory: str | Path, *, epsg: int | None = None, encoding: str = "cp949"
) -> dict[str, int]:
    """Attach a 정밀도로지도 download to a 표준노드링크 network. Returns counts per layer."""
    link_path = find_layer(directory, LAYERS["links"])
    if link_path is None:
        raise FileNotFoundError(f"no {LAYERS['links']}.shp under {directory}")
    epsg = epsg or epsg_of_shapefile(link_path)
    graph = LaneGraph(lane_links(records(link_path, encoding)))
    summary = {"lane_links": len(graph.links), "links_with_lanes": attach_lanes(network, graph)}
    for name, kind in (("lights", "traffic_light"), ("bumps", "speed_bump")):
        path = find_layer(directory, LAYERS[name])
        summary[name] = attach_points(network, graph, records(path, encoding), kind, epsg) if path else 0
    return summary


def describe_hdmap(directory: str | Path, encoding: str = "cp949") -> str:
    paths = [p for p in (find_layer(directory, token) for token in LAYERS.values()) if p]
    if not paths:
        raise FileNotFoundError(f"no 정밀도로지도 layers ({', '.join(LAYERS.values())}) under {directory}")
    return describe(paths, encoding)
