"""Vector tiles of the road network (Mapbox Vector Tile 2.1), for MapLibre clients.

This is the "own map" half of the API: the roads come from the network the
engine routes on (국가표준노드링크, plus 정밀도로지도 alerts), so what the app
draws is exactly what the engine knows. Pure Python, no dependencies.

Layers
  roads   lines   class, name, link_id, lanes
  alerts  points  type (speed_camera, signal_camera, section_camera, traffic_light, speed_bump), speed_limit_kmh
"""

from __future__ import annotations

import math
import struct
import threading
from collections import OrderedDict
from typing import Any

from .graph import RoadClass
from .network import RoadNetwork

EXTENT = 4096
BUFFER = 64
INDEX_ZOOM = 14
MAX_ZOOM = 14  # clients over-zoom beyond this

# Lowest zoom at which each road class appears.
MIN_ZOOM = {
    RoadClass.MOTORWAY: 5,
    RoadClass.TRUNK: 8,
    RoadClass.PRIMARY: 10,
    RoadClass.RAMP: 11,
    RoadClass.SECONDARY: 12,
    RoadClass.LOCAL: 13,
}
ALERT_MIN_ZOOM = 12


# --- tile math ----------------------------------------------------------


def world_xy(lat: float, lon: float) -> tuple[float, float]:
    """Web Mercator in [0, 1)²."""
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def tile_of(lat: float, lon: float, z: int) -> tuple[int, int]:
    x, y = world_xy(lat, lon)
    n = 1 << z
    return min(n - 1, int(x * n)), min(n - 1, int(y * n))


# --- protobuf -----------------------------------------------------------


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _bytes(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def _packed(field: int, values: list[int]) -> bytes:
    return _bytes(field, b"".join(_varint(v) for v in values))


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _value(value: Any) -> bytes:
    if isinstance(value, bool):
        return _tag(7, 0) + _varint(int(value))
    if isinstance(value, int):
        return _tag(6, 0) + _varint(_zigzag(value)) if value < 0 else _tag(5, 0) + _varint(value)
    if isinstance(value, float):
        return _tag(3, 1) + struct.pack("<d", value)
    return _bytes(1, str(value).encode("utf-8"))


class Layer:
    POINT, LINESTRING = 1, 2

    def __init__(self, name: str) -> None:
        self.name = name
        self.features: list[bytes] = []
        self.keys: dict[str, int] = {}
        self.values: dict[tuple[type, Any], int] = {}

    def add(self, geom_type: int, geometry: list[int], properties: dict[str, Any], fid: int | None = None) -> None:
        if not geometry:
            return
        tags = []
        for key, value in properties.items():
            if value is None:
                continue
            tags.append(self.keys.setdefault(key, len(self.keys)))
            tags.append(self.values.setdefault((type(value), value), len(self.values)))
        body = b""
        if fid is not None:
            body += _tag(1, 0) + _varint(fid)
        body += _packed(2, tags) + _tag(3, 0) + _varint(geom_type) + _packed(4, geometry)
        self.features.append(body)

    def encode(self) -> bytes:
        body = _tag(15, 0) + _varint(2) + _bytes(1, self.name.encode("utf-8"))
        body += b"".join(_bytes(2, f) for f in self.features)
        body += b"".join(_bytes(3, k.encode("utf-8")) for k in self.keys)
        body += b"".join(_bytes(4, _value(v)) for (_t, v) in self.values)
        body += _tag(5, 0) + _varint(EXTENT)
        return _bytes(3, body)


def _command(cmd: int, count: int) -> int:
    return (count << 3) | cmd


def line_geometry(parts: list[list[tuple[int, int]]]) -> list[int]:
    out: list[int] = []
    cx = cy = 0
    for part in parts:
        points = [p for i, p in enumerate(part) if i == 0 or p != part[i - 1]]
        if len(points) < 2:
            continue
        x, y = points[0]
        out += [_command(1, 1), _zigzag(x - cx), _zigzag(y - cy)]
        cx, cy = x, y
        out.append(_command(2, len(points) - 1))
        for x, y in points[1:]:
            out += [_zigzag(x - cx), _zigzag(y - cy)]
            cx, cy = x, y
    return out


def point_geometry(points: list[tuple[int, int]]) -> list[int]:
    out = [_command(1, len(points))]
    cx = cy = 0
    for x, y in points:
        out += [_zigzag(x - cx), _zigzag(y - cy)]
        cx, cy = x, y
    return out


# --- clipping -----------------------------------------------------------


def _code(x: float, y: float, lo: float, hi: float) -> int:
    return (x < lo) | ((x > hi) << 1) | ((y < lo) << 2) | ((y > hi) << 3)


def _clip_segment(x1, y1, x2, y2, lo, hi):
    """Cohen–Sutherland; returns the visible part of the segment or None."""
    c1, c2 = _code(x1, y1, lo, hi), _code(x2, y2, lo, hi)
    while True:
        if not (c1 | c2):
            return x1, y1, x2, y2
        if c1 & c2:
            return None
        c = c1 or c2
        if c & 8:
            x, y = x1 + (x2 - x1) * (hi - y1) / (y2 - y1), hi
        elif c & 4:
            x, y = x1 + (x2 - x1) * (lo - y1) / (y2 - y1), lo
        elif c & 2:
            x, y = hi, y1 + (y2 - y1) * (hi - x1) / (x2 - x1)
        else:
            x, y = lo, y1 + (y2 - y1) * (lo - x1) / (x2 - x1)
        if c == c1:
            x1, y1, c1 = x, y, _code(x, y, lo, hi)
        else:
            x2, y2, c2 = x, y, _code(x, y, lo, hi)


def clip_line(points: list[tuple[float, float]], lo: float = -BUFFER, hi: float = EXTENT + BUFFER) -> list[list[tuple[int, int]]]:
    parts: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
        seg = _clip_segment(x1, y1, x2, y2, lo, hi)
        if seg is None:
            if current:
                parts.append(current)
                current = []
            continue
        a = (round(seg[0]), round(seg[1]))
        b = (round(seg[2]), round(seg[3]))
        if current and current[-1] != a:
            parts.append(current)
            current = []
        if not current:
            current.append(a)
        current.append(b)
        if (seg[2], seg[3]) != (x2, y2):  # left the box
            parts.append(current)
            current = []
    if current:
        parts.append(current)
    return parts


# --- tiles --------------------------------------------------------------


class TileRenderer:
    def __init__(self, network: RoadNetwork, cache_size: int = 512) -> None:
        self.network = network
        self._lock = threading.Lock()
        self._world: dict[int, list[tuple[float, float]]] | None = None
        self._index: dict[tuple[int, int], list[int]] = {}
        self._reverse: set[int] = set()
        self._cache: OrderedDict[tuple[int, int, int], bytes] = OrderedDict()
        self._cache_size = cache_size

    def _build(self) -> None:
        world: dict[int, list[tuple[float, float]]] = {}
        drawn: set[tuple[int, int, str]] = set()
        n = 1 << INDEX_ZOOM
        for edge in self.network.graph.edges:
            road = (min(edge.source, edge.target), max(edge.source, edge.target), edge.name)
            if road in drawn:
                self._reverse.add(edge.id)  # the other direction of a two-way road: alerts only, no second line
            drawn.add(road)
            points = [world_xy(lat, lon) for lat, lon in self.network.edge_shape(edge)]
            world[edge.id] = points
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            for i in range(int(min(xs) * n), int(max(xs) * n) + 1):
                for j in range(int(min(ys) * n), int(max(ys) * n) + 1):
                    self._index.setdefault((i, j), []).append(edge.id)
        self._world = world

    def _candidates(self, z: int, x: int, y: int) -> set[int]:
        if z >= INDEX_ZOOM:
            shift = z - INDEX_ZOOM
            return set(self._index.get((x >> shift, y >> shift), ()))
        shift = INDEX_ZOOM - z
        out: set[int] = set()
        for (i, j), edges in self._index.items():
            if i >> shift == x and j >> shift == y:
                out.update(edges)
        return out

    def tile(self, z: int, x: int, y: int) -> bytes:
        if not (0 <= z <= 22 and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
            raise ValueError("tile out of range")
        key = (z, x, y)
        with self._lock:
            if self._world is None:
                self._build()
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        data = self._render(z, x, y)
        with self._lock:
            self._cache[key] = data
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return data

    def _render(self, z: int, x: int, y: int) -> bytes:
        n = 1 << z
        world = self._world or {}
        graph, details = self.network.graph, self.network.details
        roads, alerts = Layer("roads"), Layer("alerts")

        def pixel(p: tuple[float, float]) -> tuple[float, float]:
            return (p[0] * n - x) * EXTENT, (p[1] * n - y) * EXTENT

        for edge_id in sorted(self._candidates(z, x, y)):
            edge = graph.edges[edge_id]
            points = world.get(edge_id)
            if points is None:
                continue
            if z >= MIN_ZOOM[edge.road_class] and edge_id not in self._reverse:
                parts = clip_line([pixel(p) for p in points])
                properties = {
                    "class": edge.road_class.value,
                    "name": edge.name,
                    "link_id": edge.ext_id or None,
                    "lanes": details.lane_count.get(edge.id),
                }
                roads.add(Layer.LINESTRING, line_geometry(parts), properties, fid=edge.id)
            if z >= ALERT_MIN_ZOOM:
                for feature in details.features.get(edge.id, ()):
                    px, py = pixel(_along(points, edge.length_m, feature.offset_m))
                    if 0 <= px < EXTENT and 0 <= py < EXTENT:
                        alerts.add(
                            Layer.POINT,
                            point_geometry([(round(px), round(py))]),
                            {"type": feature.kind, "speed_limit_kmh": feature.speed_limit_kmh},
                        )
        return b"".join(layer.encode() for layer in (roads, alerts) if layer.features)


def _along(points: list[tuple[float, float]], length_m: float, offset_m: float) -> tuple[float, float]:
    """Point at `offset_m` along a polyline whose real length is `length_m`."""
    pieces = [math.dist(a, b) for a, b in zip(points, points[1:], strict=False)]
    total = sum(pieces)
    if total == 0 or length_m <= 0:
        return points[0]
    target = max(0.0, min(1.0, offset_m / length_m)) * total
    for (a, b), piece in zip(zip(points, points[1:], strict=False), pieces, strict=True):
        if target <= piece and piece > 0:
            t = target / piece
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        target -= piece
    return points[-1]
