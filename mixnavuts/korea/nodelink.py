"""Load 국가표준노드링크 (ITS standard node-link) shapefiles as a RoadNetwork.

The standard node-link set is the road network ITS 교통소통정보 refers to:
its LINK_ID is the key of every live speed, so a network built from it needs
no map matching to use ITS data.

Download it from the ITS 국가교통정보센터 site (표준노드링크). It ships as
MOCT_NODE.shp / MOCT_LINK.shp in a Korean TM projection, with CP949 text.
Reading shapefiles needs the optional `pyshp` package
(`pip install "mixnavuts[korea]"`).

Field names follow the published layout; check them against the release you
download (`python -m mixnavuts nodelink-info DIR` prints what is there).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..geo import LocalProjection, haversine_m
from ..graph import RoadClass, RoadGraph
from ..network import RoadNetwork
from ..roadinfo import RoadDetails
from ..traffic import ProfileTraffic, TrafficModel, typical_class_profiles
from .shp import describe, field, find_layer, number, records
from .tm import epsg_of_shapefile, to_wgs84

# ROAD_RANK codes
ROAD_RANK_CLASS = {
    "101": RoadClass.MOTORWAY,  # 고속국도
    "102": RoadClass.TRUNK,  # 도시고속국도
    "103": RoadClass.TRUNK,  # 일반국도
    "104": RoadClass.PRIMARY,  # 특별·광역시도
    "105": RoadClass.SECONDARY,  # 국가지원지방도
    "106": RoadClass.SECONDARY,  # 지방도
    "107": RoadClass.LOCAL,  # 시·군도
    "108": RoadClass.LOCAL,  # 기타
}
DEFAULT_SPEED_KMH = {
    RoadClass.MOTORWAY: 100,
    RoadClass.RAMP: 50,
    RoadClass.TRUNK: 80,
    RoadClass.PRIMARY: 60,
    RoadClass.SECONDARY: 60,
    RoadClass.LOCAL: 40,
}
# 고속도로 통행료 근사: 폐쇄식 요금은 진입·진출 영업소 쌍으로 정해지므로 실제
# 요금은 한국도로공사 영업소 간 요금표로 계산해야 한다. 여기서는 승용차
# 주행요금(원/km)만 링크 길이에 비례해 붙인다.
MOTORWAY_TOLL_KRW_PER_KM = 44.3
_NOT_RAMP = {"", "0", "000", "None"}


def _winding(points: list[tuple[float, float]], length_m: float) -> float:
    """Total heading change per km, scaled so a hairpin mountain road is ~1."""
    if len(points) < 3 or length_m <= 0:
        return 0.0
    turning = 0.0
    for (x1, y1), (x2, y2), (x3, y3) in zip(points, points[1:], points[2:], strict=False):
        h1, h2 = math.atan2(y2 - y1, x2 - x1), math.atan2(y3 - y2, x3 - x2)
        turning += abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
    return min(1.0, turning / (length_m / 1000) / 8.0)


def build_network(
    nodes: Iterable[tuple[Mapping[str, Any], tuple[float, float]]],
    links: Iterable[tuple[Mapping[str, Any], list[tuple[float, float]]]],
    *,
    epsg: int = 5186,
    bbox: tuple[float, float, float, float] | None = None,
    historical: TrafficModel | None = None,
    name: str = "nodelink",
) -> RoadNetwork:
    """Build from (record, TM point) nodes and (record, TM polyline) links.

    `bbox` is (min_lon, min_lat, max_lon, max_lat); links are kept when both
    end nodes fall inside it.
    """
    node_ll: dict[str, tuple[float, float]] = {}
    node_name: dict[str, str] = {}
    for record, (x, y) in nodes:
        node_id = field(record, "NODE_ID")
        lat, lon = to_wgs84(x, y, epsg)
        if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        node_ll[node_id] = (lat, lon)
        node_name[node_id] = field(record, "NODE_NAME")
    if not node_ll:
        raise ValueError("no nodes inside the bounding box")

    lats = [p[0] for p in node_ll.values()]
    lons = [p[1] for p in node_ll.values()]
    projection = LocalProjection((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    graph = RoadGraph()
    index: dict[str, int] = {}
    for node_id, (lat, lon) in node_ll.items():
        x, y = projection.to_xy(lat, lon)
        label = node_name[node_id]
        index[node_id] = graph.add_node(x, y, label if label and label not in graph.places() else "")

    shapes: dict[int, list[tuple[float, float]]] = {}
    details = RoadDetails()
    for record, points in links:
        f_node, t_node = field(record, "F_NODE"), field(record, "T_NODE")
        if f_node not in index or t_node not in index:
            continue
        road_class = ROAD_RANK_CLASS.get(field(record, "ROAD_RANK"), RoadClass.LOCAL)
        if field(record, "CONNECT") not in _NOT_RAMP:
            road_class = RoadClass.RAMP
        shape = [to_wgs84(x, y, epsg) for x, y in points] if points else []
        length = number(record, "LENGTH")
        if length <= 0:
            length = sum(haversine_m(*a, *b) for a, b in zip(shape, shape[1:], strict=False)) or graph.euclidean_m(
                index[f_node], index[t_node]
            )
        speed = number(record, "MAX_SPD") or DEFAULT_SPEED_KMH[road_class]
        road_name = field(record, "ROAD_NAME") or (f"{field(record, 'ROAD_NO')}번 도로" if field(record, "ROAD_NO") else "")
        planar = [projection.to_xy(lat, lon) for lat, lon in shape]
        edge = graph.add_edge(
            index[f_node],
            index[t_node],
            road_class,
            speed,
            length_m=length,
            toll_krw=round(MOTORWAY_TOLL_KRW_PER_KM * length / 1000) if road_class == RoadClass.MOTORWAY else 0,
            curvature=_winding(planar, length),
            name=road_name or "이면도로",
            ext_id=field(record, "LINK_ID"),
        )
        if len(shape) > 2:
            shapes[edge.id] = shape
        lanes = int(number(record, "LANES"))
        if lanes > 0:
            details.lane_count[edge.id] = lanes

    historical = historical or ProfileTraffic(class_profiles=typical_class_profiles())
    snap = [node for node in graph.nodes if graph.out_edges(node) and graph.in_edges(node)]
    return RoadNetwork(name, graph, projection, historical, snap, synthetic=False, shapes=shapes, details=details)


def find_shapefiles(directory: str | Path) -> tuple[Path, Path]:
    node, link = find_layer(directory, "NODE"), find_layer(directory, "LINK")
    if node is None or link is None:
        raise FileNotFoundError(f"expected *NODE*.shp and *LINK*.shp in {directory}")
    return node, link


def load_nodelink(
    directory: str | Path,
    *,
    epsg: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    encoding: str = "cp949",
    historical: TrafficModel | None = None,
) -> RoadNetwork:
    """`epsg=None` reads the coordinate system from the .prj (5186 if it cannot tell)."""
    node_path, link_path = find_shapefiles(directory)
    epsg = epsg or epsg_of_shapefile(link_path)
    nodes = ((record, points[0]) for record, points in records(node_path, encoding) if points)
    return build_network(nodes, records(link_path, encoding), epsg=epsg, bbox=bbox, historical=historical)


def describe_nodelink(directory: str | Path, encoding: str = "cp949") -> str:
    return describe(list(find_shapefiles(directory)), encoding)
