"""Turn-by-turn guidance and pace notes from a route's edges."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .graph import Edge, RoadClass, RoadGraph
from .traffic import TrafficModel

_HIGHWAY = {RoadClass.MOTORWAY, RoadClass.RAMP}
_LOCAL_NAME = "이면도로"

_TURN = {
    "left": "좌회전",
    "right": "우회전",
    "sharp_left": "급좌회전",
    "sharp_right": "급우회전",
    "slight_left": "왼쪽 방향",
    "slight_right": "오른쪽 방향",
}


@dataclass(frozen=True)
class Maneuver:
    edge_index: int  # the maneuver happens where this edge starts
    distance_m: float  # along the route, from the start
    type: str  # depart, turn, continue, ramp_on, ramp_off, fork, arrive
    modifier: str  # straight, slight_left, left, sharp_left, uturn, slight_right, right, sharp_right
    road_name: str
    instruction: str


@dataclass(frozen=True)
class Curve:
    start_m: float
    end_m: float
    direction: str  # left, right, mixed
    severity: float  # 0..1


def heading(g: RoadGraph, edge: Edge) -> float:
    a, b = g.nodes[edge.source], g.nodes[edge.target]
    return math.atan2(b.y - a.y, b.x - a.x)


def turn_angle(g: RoadGraph, a: Edge, b: Edge) -> float:
    """Signed heading change in degrees, positive = left (counter-clockwise)."""
    delta = math.degrees(heading(g, b) - heading(g, a))
    return (delta + 180.0) % 360.0 - 180.0


def modifier(angle: float) -> str:
    size = abs(angle)
    if size < 20:
        return "straight"
    if size > 170:
        return "uturn"
    side = "left" if angle > 0 else "right"
    if size < 60:
        return f"slight_{side}"
    if size > 135:
        return f"sharp_{side}"
    return side


def _with_ro(word: str) -> str:
    """Append 로/으로 the way it is read aloud ("동서대로 14" → "…14로")."""
    if not word:
        return word
    last = word[-1]
    if last.isdigit():
        return word + ("으로" if last in "036" else "로")
    code = ord(last) - 0xAC00
    if 0 <= code < 11172:
        final = code % 28
        return word + ("으로" if final not in (0, 8) else "로")  # 8 = ㄹ
    return word + "로"


def _side(mod: str) -> str:
    return "왼쪽" if "left" in mod else "오른쪽"


def maneuvers(g: RoadGraph, edges: Sequence[Edge]) -> list[Maneuver]:
    if not edges:
        return []
    out = [Maneuver(0, 0.0, "depart", "straight", edges[0].name, f"{edges[0].name} 방면으로 출발")]
    travelled = edges[0].length_m
    for i in range(1, len(edges)):
        a, b = edges[i - 1], edges[i]
        mod = modifier(turn_angle(g, a, b))
        kind = text = None
        if a.road_class not in _HIGHWAY and b.road_class == RoadClass.RAMP:
            motorway = next((e.name for e in edges[i:] if e.road_class == RoadClass.MOTORWAY), b.name)
            kind, text = "ramp_on", f"{_side(mod)} {motorway} 진입로"
        elif a.road_class == RoadClass.RAMP and b.road_class == RoadClass.MOTORWAY:
            pass  # merging is implied by the ramp_on instruction
        elif a.road_class == RoadClass.MOTORWAY and b.road_class == RoadClass.RAMP:
            kind, text = "ramp_off", f"{_side(mod)} 진출로 ({b.name})"
        elif a.road_class == RoadClass.MOTORWAY and b.road_class == RoadClass.MOTORWAY and a.name != b.name:
            kind, text = "fork", f"{b.name} 방면"
        elif mod == "uturn":
            kind, text = "turn", "유턴"
        elif mod != "straight":
            kind, text = "turn", f"{_TURN[mod]} 후 {b.name}" if "slight" not in mod else f"{_TURN[mod]} {b.name}"
        elif a.name != b.name and b.name != _LOCAL_NAME:
            kind, text = "continue", f"{_with_ro(b.name)} 계속"
        if kind:
            out.append(Maneuver(i, travelled, kind, mod, b.name, text))
        travelled += b.length_m
    out.append(Maneuver(len(edges), travelled, "arrive", "straight", edges[-1].name, "목적지 도착"))
    return out


def curves(g: RoadGraph, edges: Sequence[Edge], min_curvature: float = 0.3) -> list[Curve]:
    """Winding stretches ahead, for rally-style pace notes."""
    out: list[Curve] = []
    position = 0.0
    run: list[int] = []

    def close(end_m: float) -> None:
        if not run:
            return
        stretch = [edges[i] for i in run]
        length = sum(e.length_m for e in stretch)
        turning = sum(turn_angle(g, edges[i - 1], edges[i]) for i in run[1:])
        direction = "mixed" if abs(turning) < 15 else ("left" if turning > 0 else "right")
        severity = sum(e.curvature * e.length_m for e in stretch) / length
        out.append(Curve(end_m - length, end_m, direction, round(severity, 3)))
        run.clear()

    for i, edge in enumerate(edges):
        if edge.curvature >= min_curvature:
            run.append(i)
        else:
            close(position)
        position += edge.length_m
    close(position)
    return out


def timeline(edges: Sequence[Edge], traffic: TrafficModel, depart: float) -> list[tuple[float, float]]:
    """(offset from departure, predicted duration) for each edge."""
    out = []
    t = depart
    for edge in edges:
        duration = traffic.travel_time(edge, t)
        out.append((t - depart, duration))
        t += duration
    return out
