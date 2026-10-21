"""Lane counts, lane guidance and point features (cameras, lights, bumps) per road link.

Filled from 정밀도로지도 and 무인교통단속카메라 data for real networks
(`korea/hdmap.py`, `korea/cameras.py`) or generated for the synthetic city.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .graph import Edge

LANE_GUIDED = {"turn", "ramp_on", "ramp_off", "fork"}


@dataclass(frozen=True)
class LaneHint:
    count: int
    recommended: tuple[int, ...]  # 1 = 1차로 (leftmost)

    def to_json(self) -> dict:
        return {"count": self.count, "recommended": list(self.recommended)}


@dataclass(frozen=True)
class RoadFeature:
    kind: str  # speed_camera, signal_camera, traffic_light, speed_bump
    offset_m: float  # along the link from its start
    speed_limit_kmh: int | None = None
    label: str = ""


FEATURE_LABELS = {
    "speed_camera": "과속 단속",
    "signal_camera": "신호 단속",
    "section_camera": "구간 단속",
    "traffic_light": "신호등",
    "speed_bump": "과속방지턱",
}


def rule_lanes(count: int, maneuver_type: str, modifier: str) -> tuple[int, ...]:
    """Usual lanes for a maneuver when there is no lane-level map: keep left to turn left, and so on."""
    left, right = "left" in modifier or modifier == "uturn", "right" in modifier
    if maneuver_type in ("ramp_off", "fork") or modifier.startswith("slight"):
        half = max(1, count // 2)
        return tuple(range(1, half + 1)) if left else tuple(range(count - half + 1, count + 1))
    if left:
        return (1,)
    if right:
        return (count,)
    return tuple(range(2, count)) if count >= 3 else tuple(range(1, count + 1))


@dataclass
class RoadDetails:
    lane_count: dict[int, int] = field(default_factory=dict)  # edge id → lanes
    features: dict[int, list[RoadFeature]] = field(default_factory=dict)  # edge id → features
    # Lane-level answer for (from edge, to edge), e.g. from the 정밀도로지도 lane graph.
    lane_resolver: Callable[[Edge, Edge], tuple[int, ...] | None] | None = None
    rule_fallback: bool = True

    def add_feature(self, edge_id: int, feature: RoadFeature) -> None:
        self.features.setdefault(edge_id, []).append(feature)

    def lane_hint(self, a: Edge, b: Edge, maneuver_type: str, modifier: str) -> LaneHint | None:
        if maneuver_type not in LANE_GUIDED:
            return None
        count = self.lane_count.get(a.id, 0)
        if count < 2:
            return None
        lanes = self.lane_resolver(a, b) if self.lane_resolver else None
        if not lanes and self.rule_fallback:
            lanes = rule_lanes(count, maneuver_type, modifier)
        if not lanes or len(lanes) == count:
            return None  # every lane works: nothing to say
        return LaneHint(count, tuple(sorted(lanes)))
