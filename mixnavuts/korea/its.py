"""국가교통정보센터(ITS) Open API: live link speeds and incidents.

  교통소통정보  GET {base}/trafficInfo?apiKey=…&type=all&minX=…&maxX=…&minY=…&maxY=…&getType=json
  돌발상황정보  GET {base}/eventInfo?apiKey=…&type=all&eventType=all&minX=…&…&getType=json

Speeds are keyed by 표준링크ID (LINK_ID), so they attach directly to a network
loaded from 국가표준노드링크. The API key comes from the ITS open-data portal.
Response field names follow the published spec; the parser accepts a few
spellings and skips records it cannot read instead of failing the whole feed.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..live import LiveSnapshot
from ..network import RoadNetwork
from ..traffic import Incident

ITS_BASE_URL = "https://openapi.its.go.kr:9443"
KST = timezone(timedelta(hours=9))

# How much of the speed limit is left while an event is active.
EVENT_SPEED_FACTOR = {
    "통제": 0.0,
    "사고": 0.3,
    "고장": 0.5,
    "공사": 0.5,
    "기상": 0.7,
    "행사": 0.6,
    "재난": 0.2,
}
DEFAULT_EVENT_FACTOR = 0.6
DEFAULT_EVENT_DURATION_S = 3_600.0

Opener = Callable[[str, float], bytes]


def _urlopen(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
        return response.read()


def parse_kst(value: Any) -> float | None:
    """'20261021083000' (KST) → epoch seconds."""
    text = str(value or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST).timestamp()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class LinkSpeed:
    link_id: str
    speed_kmh: float
    travel_time_s: float | None
    observed_at: float | None


@dataclass(frozen=True)
class ItsEvent:
    link_id: str
    event_type: str
    detail: str
    start: float | None
    end: float | None
    lat: float | None
    lon: float | None
    message: str
    lanes_blocked: str


def _items(payload: Any) -> list[dict[str, Any]]:
    body = payload.get("body", payload) if isinstance(payload, dict) else payload
    items = body.get("items", []) if isinstance(body, dict) else body
    if isinstance(items, dict):  # some XML→JSON bridges wrap a single item
        items = items.get("item", [items])
    if isinstance(items, dict):
        items = [items]
    return [item for item in items or [] if isinstance(item, dict)]


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ItsClient:
    def __init__(
        self,
        api_key: str,
        bbox: tuple[float, float, float, float],
        *,
        road_type: str = "all",
        base_url: str = ITS_BASE_URL,
        timeout: float = 10.0,
        opener: Opener = _urlopen,
    ) -> None:
        self.api_key = api_key
        self.bbox = bbox  # (min_lon, min_lat, max_lon, max_lat)
        self.road_type = road_type
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = opener

    def _get(self, path: str, extra: dict[str, str]) -> Any:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        params = {
            "apiKey": self.api_key,
            "type": self.road_type,
            "minX": f"{min_lon}",
            "maxX": f"{max_lon}",
            "minY": f"{min_lat}",
            "maxY": f"{max_lat}",
            "getType": "json",
            **extra,
        }
        raw = self.opener(f"{self.base_url}/{path}?{urllib.parse.urlencode(params)}", self.timeout)
        payload = json.loads(raw.decode("utf-8"))
        header = payload.get("header", {}) if isinstance(payload, dict) else {}
        code = str(header.get("resultCode", "0"))
        if code not in ("0", "00", "200"):
            raise RuntimeError(f"ITS {path} error {code}: {header.get('resultMsg', '')}")
        return payload

    def traffic(self) -> list[LinkSpeed]:
        out = []
        for item in _items(self._get("trafficInfo", {})):
            link_id = str(item.get("linkId") or item.get("link_id") or "").strip()
            speed = _float(item.get("speed"))
            if link_id and speed is not None and speed > 0:
                out.append(LinkSpeed(link_id, speed, _float(item.get("travelTime")), parse_kst(item.get("createdDate"))))
        return out

    def events(self) -> list[ItsEvent]:
        out = []
        for item in _items(self._get("eventInfo", {"eventType": "all"})):
            out.append(
                ItsEvent(
                    link_id=str(item.get("linkId") or "").strip(),
                    event_type=str(item.get("eventType") or ""),
                    detail=str(item.get("eventDetailType") or ""),
                    start=parse_kst(item.get("startDate")),
                    end=parse_kst(item.get("endDate")),
                    lat=_float(item.get("coordY")),
                    lon=_float(item.get("coordX")),
                    message=str(item.get("message") or ""),
                    lanes_blocked=str(item.get("lanesBlocked") or ""),
                )
            )
        return out


def event_speed_factor(event: ItsEvent) -> float:
    text = f"{event.event_type} {event.detail} {event.message}"
    for keyword, factor in EVENT_SPEED_FACTOR.items():
        if keyword in text:
            return factor
    return DEFAULT_EVENT_FACTOR


class ItsFeed:
    """Caches ITS data and refreshes it at most every `refresh_s` (ITS updates ~5 min)."""

    def __init__(self, client: ItsClient, network: RoadNetwork, refresh_s: float = 300.0, clock=time.time) -> None:
        self.client = client
        self.network = network
        self.refresh_s = refresh_s
        self.clock = clock
        self._lock = threading.Lock()
        self._fetched_at = -float("inf")
        self._speeds: list[LinkSpeed] = []
        self._events: list[ItsEvent] = []
        self.last_error: str | None = None

    def _refresh(self) -> None:
        with self._lock:
            if self.clock() - self._fetched_at < self.refresh_s:
                return
            try:
                self._speeds = self.client.traffic()
                self._events = self.client.events()
                self.last_error = None
            except Exception as exc:  # keep serving the last good data
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._fetched_at = self.clock()

    def snapshot(self, now: float, day_start: float) -> LiveSnapshot:
        self._refresh()
        graph = self.network.graph
        observed: dict[int, float] = {}
        newest = None
        for reading in self._speeds:
            edge = graph.edge_by_ext(reading.link_id)
            if edge is None:
                continue
            observed[edge.id] = reading.speed_kmh / 3.6
            if reading.observed_at and (newest is None or reading.observed_at > newest):
                newest = reading.observed_at
        incidents = []
        for event in self._events:
            edge = graph.edge_by_ext(event.link_id)
            if edge is None:
                continue
            start = event.start if event.start is not None else now
            end = event.end if event.end and event.end > now else max(start + DEFAULT_EVENT_DURATION_S, now + 900.0)
            incidents.append(Incident(frozenset([edge.id]), start - day_start, end - day_start, event_speed_factor(event)))
        return LiveSnapshot(observed, incidents, newest, "its")
