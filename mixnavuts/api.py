"""MIXNAVUTS Engine HTTP API.

Endpoints (JSON, UTF-8):
  GET  /v1/health
  GET  /v1/places
  GET  /v1/search?q=…[&lat=…&lon=…]
  POST /v1/routes

See docs/API.md for the request and response formats. Keys for external
services stay on this server; the apps only ever talk to it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from .candidates import candidate_stats, generate_candidates
from .evaluate import evaluate
from .geo import haversine_m
from .graph import Edge
from .guidance import curves, maneuvers, timeline
from .live import LiveFeed, NoLiveFeed
from .network import RoadNetwork
from .ranking import MODES, Suggestion, select_routes
from .traffic import DAY_S, PredictiveTraffic, TrafficModel

API_VERSION = 1
KST_OFFSET_S = 9 * 3600


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class PlaceResult:
    name: str
    lat: float
    lon: float
    address: str = ""
    category: str = ""
    source: str = "network"

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "address": self.address,
            "category": self.category,
            "source": self.source,
        }


class PlaceSearch(Protocol):
    name: str

    def search(self, query: str, near: tuple[float, float] | None = None, size: int = 15) -> list[PlaceResult]: ...


class NetworkPlaceSearch:
    """Substring search over named nodes of the road network."""

    name = "network"

    def __init__(self, network: RoadNetwork) -> None:
        self.network = network

    def search(self, query: str, near: tuple[float, float] | None = None, size: int = 15) -> list[PlaceResult]:
        hits = []
        for place, node_id in self.network.places().items():
            if query in place:
                lat, lon = self.network.latlon(node_id)
                hits.append(PlaceResult(place, lat, lon))
        return hits[:size]


def local_day_start(epoch: float, offset_s: float = KST_OFFSET_S) -> float:
    """Epoch of local midnight on the day containing `epoch`."""
    return (epoch + offset_s) // DAY_S * DAY_S - offset_s


class Engine:
    def __init__(
        self,
        network: RoadNetwork,
        feed: LiveFeed | None = None,
        search: PlaceSearch | None = None,
        utc_offset_s: float = KST_OFFSET_S,
        clock=time.time,
    ) -> None:
        self.network = network
        self.feed = feed or NoLiveFeed()
        self.search_provider = search or NetworkPlaceSearch(network)
        self.utc_offset_s = utc_offset_s
        self.clock = clock

    # --- endpoints -------------------------------------------------------

    def health(self) -> dict[str, Any]:
        now = self.clock()
        snap = self.feed.snapshot(now, local_day_start(now, self.utc_offset_s))
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "network": self.network.name,
            "synthetic": self.network.synthetic,
            "nodes": len(self.network.graph.nodes),
            "edges": len(self.network.graph.edges),
            "live": {"source": snap.source, "as_of": snap.as_of, "observed_links": len(snap.observed_mps)},
            "search": self.search_provider.name,
        }

    def places(self) -> dict[str, Any]:
        places = []
        for name, node_id in sorted(self.network.places().items(), key=lambda item: item[1])[:500]:
            lat, lon = self.network.latlon(node_id)
            places.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6)})
        return {"synthetic": self.network.synthetic, "places": places}

    def search(self, query: str, near: tuple[float, float] | None = None) -> dict[str, Any]:
        if not query.strip():
            raise ApiError(HTTPStatus.BAD_REQUEST, "q is required")
        results = self.search_provider.search(query.strip(), near)
        return {"provider": self.search_provider.name, "results": [r.to_json() for r in results]}

    def plan(self, body: dict[str, Any]) -> dict[str, Any]:
        source = self._resolve(body.get("origin"), "origin")
        target = self._resolve(body.get("destination"), "destination")
        if source == target:
            raise ApiError(HTTPStatus.BAD_REQUEST, "origin and destination are the same place")
        mode = body.get("mode", "balanced")
        if mode not in MODES:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"mode must be one of {sorted(MODES)}")
        k = int(body.get("k", 4))
        if not 1 <= k <= 5:
            raise ApiError(HTTPStatus.BAD_REQUEST, "k must be between 1 and 5")
        depart_epoch = float(body.get("depart") or self.clock())
        day_start = local_day_start(depart_epoch, self.utc_offset_s)
        depart = depart_epoch - day_start

        snap = self.feed.snapshot(min(depart_epoch, self.clock()), day_start)
        model = PredictiveTraffic(self.network.historical, depart, snap.observed_mps, incidents=snap.incidents)
        graph = self.network.graph
        routes = generate_candidates(graph, source, target, model, depart)
        if not routes:
            raise ApiError(HTTPStatus.NOT_FOUND, "no route between origin and destination")
        evaluations = [evaluate(route, model, depart) for route in routes]
        suggestions = select_routes(evaluations, MODES[mode], k=k)
        return {
            "synthetic": self.network.synthetic,
            "network": self.network.name,
            "mode": mode,
            "depart": depart_epoch,
            "candidates": len(routes),
            "candidate_sources": candidate_stats(routes),
            "live": {"source": snap.source, "as_of": snap.as_of, "incidents": len(snap.incidents)},
            "routes": [self._route_json(s, model, depart, depart_epoch) for s in suggestions],
        }

    # --- helpers -------------------------------------------------------

    def _resolve(self, spec: Any, field_name: str) -> int:
        if not isinstance(spec, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be an object with 'place' or 'lat'/'lon'")
        if "place" in spec:
            node_id = self.network.places().get(str(spec["place"]))
            if node_id is None:
                raise ApiError(HTTPStatus.NOT_FOUND, f"unknown place: {spec['place']}")
            return node_id
        try:
            lat, lon = float(spec["lat"]), float(spec["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{field_name} needs numeric lat and lon") from exc
        node_id = self.network.nearest(lat, lon)
        if node_id is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"{field_name} is not near any road in the '{self.network.name}' network")
        return node_id

    def _route_json(self, suggestion: Suggestion, model: TrafficModel, depart: float, depart_epoch: float) -> dict[str, Any]:
        ev = suggestion.evaluation
        edges = ev.route.edges
        graph = self.network.graph

        geometry: list[list[float]] = []
        segments = []
        travelled = 0.0
        for edge, (offset, duration) in zip(edges, timeline(edges, model, depart), strict=True):
            shape = self.network.edge_shape(edge)
            start_index = max(0, len(geometry) - 1)
            pieces = [0.0]
            for (lat1, lon1), (lat2, lon2) in zip(shape, shape[1:], strict=False):
                pieces.append(pieces[-1] + haversine_m(lat1, lon1, lat2, lon2))
            scale = edge.length_m / pieces[-1] if pieces[-1] else 0.0
            for idx, (lat, lon) in enumerate(shape):
                if geometry and idx == 0:
                    continue  # shared with the previous edge's last point
                geometry.append([round(lat, 6), round(lon, 6), round(travelled + pieces[idx] * scale, 1)])
            travelled += edge.length_m
            segments.append(
                {
                    "start_index": start_index,
                    "end_index": len(geometry) - 1,
                    "length_m": round(edge.length_m, 1),
                    "speed_limit_kmh": round(edge.speed_limit_kmh),
                    "road_name": edge.name,
                    "road_class": edge.road_class.value,
                    "curvature": round(edge.curvature, 3),
                    "toll_krw": edge.toll_krw,
                    "offset_s": round(offset, 1),
                    "duration_s": round(duration, 1),
                    "link_id": edge.ext_id or None,
                }
            )
        point_of_edge = [segment["start_index"] for segment in segments] + [len(geometry) - 1]
        key = ",".join(str(edge.id) for edge in edges)
        return {
            "id": hashlib.sha1(key.encode()).hexdigest()[:12],
            "labels": list(suggestion.labels),
            "depart": depart_epoch,
            "arrival": depart_epoch + ev.duration_s,
            "duration_s": round(ev.duration_s, 1),
            "distance_m": round(ev.distance_m, 1),
            "toll_krw": ev.toll_krw,
            "highway_share": round(ev.highway_share, 3),
            "winding": round(ev.winding, 3),
            "summary": road_summary(edges),
            "geometry": geometry,
            "segments": segments,
            "maneuvers": [
                {
                    "point_index": point_of_edge[m.edge_index],
                    "distance_m": round(m.distance_m, 1),
                    "type": m.type,
                    "modifier": m.modifier,
                    "road_name": m.road_name,
                    "instruction": m.instruction,
                }
                for m in maneuvers(graph, edges)
            ],
            "curves": [
                {"start_m": round(c.start_m, 1), "end_m": round(c.end_m, 1), "direction": c.direction, "severity": c.severity}
                for c in curves(graph, edges)
            ],
        }


def road_summary(edges: Sequence[Edge], min_m: float = 800.0, limit: int = 5) -> str:
    groups: list[list] = []  # [name, metres]
    for edge in edges:
        if groups and groups[-1][0] == edge.name:
            groups[-1][1] += edge.length_m
        else:
            groups.append([edge.name, edge.length_m])
    names = [name for name, metres in groups if metres >= min_m and name and name != "이면도로" and not name.endswith(" IC")]
    names = [name for i, name in enumerate(names) if i == 0 or names[i - 1] != name]
    if len(names) > limit:
        names = names[: limit - 1] + ["…", names[-1]]
    return " → ".join(names) or "이면도로"


# --- HTTP ---------------------------------------------------------------


def make_handler(engine: Engine) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MIXNAVUTS/0.1"

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/v1/health":
                self._run(engine.health)
            elif url.path == "/v1/places":
                self._run(engine.places)
            elif url.path == "/v1/search":
                near = None
                if "lat" in query and "lon" in query:
                    near = (float(query["lat"]), float(query["lon"]))
                self._run(lambda: engine.search(query.get("q", ""), near))
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/v1/routes":
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "body must be JSON"})
                return
            self._run(lambda: engine.plan(body))

        def _run(self, fn) -> None:
            try:
                self._send(HTTPStatus.OK, fn())
            except ApiError as exc:
                self._send(exc.status, {"error": exc.message})
            except (ValueError, TypeError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            print(f"{self.address_string()} {format % args}")

    return Handler


def serve(engine: Engine, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(engine))
