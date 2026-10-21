"""브이월드 (국토교통부 공간정보 오픈플랫폼): national base map tiles and place/address search.

  WMTS  https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.{png|jpeg}
        layers: Base, white, midnight, Hybrid (png), Satellite (jpeg)
  검색  https://api.vworld.kr/req/search?service=search&request=search&version=2.0&type=place|address …

The key is issued at vworld.kr for a registered service URL; pass that URL as
`domain` when the key is bound to one. Tiles are proxied (and kept in a small
memory cache) so the key never reaches the apps. Check the 브이월드 terms for
caching and service limits before production use.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable

from ..api import PlaceResult
from ..geo import haversine_m

WMTS_URL = "https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.{ext}"
SEARCH_URL = "https://api.vworld.kr/req/search"
LAYER_EXT = {"Base": "png", "white": "png", "midnight": "png", "Hybrid": "png", "Satellite": "jpeg"}

Opener = Callable[[urllib.request.Request, float], bytes]


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
        return response.read()


class VWorldTiles:
    def __init__(
        self,
        api_key: str,
        layer: str = "Base",
        *,
        domain: str | None = None,
        cache_size: int = 2_048,
        timeout: float = 10.0,
        opener: Opener = _urlopen,
    ) -> None:
        if layer not in LAYER_EXT:
            raise ValueError(f"layer must be one of {sorted(LAYER_EXT)}")
        self.api_key = api_key
        self.layer = layer
        self.domain = domain
        self.timeout = timeout
        self.opener = opener
        self.content_type = "image/png" if LAYER_EXT[layer] == "png" else "image/jpeg"
        self._cache: OrderedDict[tuple[int, int, int], bytes] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def tile(self, z: int, x: int, y: int) -> bytes:
        if not (6 <= z <= 19):
            raise ValueError("브이월드 tiles exist for zoom 6–19")
        key = (z, x, y)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        url = WMTS_URL.format(key=self.api_key, layer=self.layer, z=z, y=y, x=x, ext=LAYER_EXT[self.layer])
        headers = {"Referer": self.domain} if self.domain else {}
        data = self.opener(urllib.request.Request(url, headers=headers), self.timeout)
        with self._lock:
            self._cache[key] = data
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return data


class VWorldSearch:
    """Place search first, then road-address search when no place matches."""

    name = "vworld"

    def __init__(self, api_key: str, *, domain: str | None = None, timeout: float = 5.0, opener: Opener = _urlopen) -> None:
        self.api_key = api_key
        self.domain = domain
        self.timeout = timeout
        self.opener = opener

    def _query(self, query: str, kind: str, size: int) -> list[PlaceResult]:
        params = {
            "service": "search",
            "request": "search",
            "version": "2.0",
            "crs": "EPSG:4326",
            "size": str(size),
            "page": "1",
            "query": query,
            "type": kind,
            "format": "json",
            "errorformat": "json",
            "key": self.api_key,
        }
        if kind == "address":
            params["category"] = "road"
        if self.domain:
            params["domain"] = self.domain
        request = urllib.request.Request(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
        payload = json.loads(self.opener(request, self.timeout).decode("utf-8")).get("response", {})
        status = payload.get("status")
        if status == "ERROR":
            raise RuntimeError(f"브이월드 검색 오류: {payload.get('error', {}).get('text', '')}")
        if status != "OK":  # NOT_FOUND
            return []
        results = []
        for item in payload.get("result", {}).get("items", []):
            point = item.get("point", {})
            address = item.get("address", {})
            try:
                lon, lat = float(point["x"]), float(point["y"])
            except (KeyError, TypeError, ValueError):
                continue
            road = address.get("road") or address.get("parcel") or ""
            results.append(
                PlaceResult(
                    name=item.get("title") or road,
                    lat=lat,
                    lon=lon,
                    address=road,
                    category=item.get("category", ""),
                    source="vworld",
                )
            )
        return results

    def search(self, query: str, near: tuple[float, float] | None = None, size: int = 15) -> list[PlaceResult]:
        results = self._query(query, "place", size) or self._query(query, "address", size)
        if near:
            results.sort(key=lambda r: haversine_m(near[0], near[1], r.lat, r.lon))
        return results
