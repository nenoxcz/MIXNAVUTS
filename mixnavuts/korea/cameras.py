"""경찰청 무인교통단속카메라 (공공데이터포털 "전국무인교통단속카메라표준데이터", CSV).

Each camera is attached to the links passing within `radius_m` of it. The
file does not say which carriageway a camera watches, so both directions of
a two-way road get the alert; 도로노선방향 could narrow this down once its
coding is confirmed against real rows.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ..network import RoadNetwork
from ..roadinfo import RoadFeature

# 단속구분 is published as codes in some releases and as text in others.
_KIND_BY_CODE = {
    "1": "speed_camera",
    "01": "speed_camera",
    "2": "signal_camera",
    "02": "signal_camera",
    "3": "speed_camera",
    "03": "speed_camera",
}


def camera_kind(value: str, section: str = "") -> str | None:
    text = value.strip()
    if section.strip():
        return "section_camera"
    if text in _KIND_BY_CODE:
        return _KIND_BY_CODE[text]
    if "주정차" in text or "주차" in text:
        return None  # parking enforcement: not a driving alert
    if "구간" in text:
        return "section_camera"
    if "신호" in text and "과속" not in text:
        return "signal_camera"
    return "speed_camera"


def read_rows(path: str | Path) -> list[dict[str, str]]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(encoding))))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: neither UTF-8 nor CP949")


def load_cameras(network: RoadNetwork, path: str | Path, radius_m: float = 25.0) -> int:
    attached = 0
    for row in read_rows(path):
        try:
            lat, lon = float(row["위도"]), float(row["경도"])
        except (KeyError, ValueError):
            continue
        kind = camera_kind(row.get("단속구분", ""), row.get("단속구간위치구분", ""))
        if kind is None:
            continue
        try:
            limit = int(float(row.get("제한속도") or 0)) or None
        except ValueError:
            limit = None
        near = network.edges_near(lat, lon, radius_m)
        if not near:
            continue
        closest = near[0][2]
        for edge, offset, distance in near:
            if distance <= closest + 5.0:  # the road the camera stands on, not the cross street
                network.details.add_feature(edge.id, RoadFeature(kind, offset, limit, row.get("설치장소", "").strip()))
                attached += 1
    return attached
