"""도로명주소 API (행정안전부 business.juso.go.kr): address search and coordinates.

  검색   GET https://business.juso.go.kr/addrlink/addrLinkApi.do?confmKey=…&keyword=…&resultType=json
  좌표   GET https://business.juso.go.kr/addrlink/addrCoordApi.do?confmKey=…&admCd=…&rnMgtSn=…&udrtYn=…&buldMnnm=…&buldSlno=…

The two APIs are issued separate keys. Coordinates come back in UTM-K
(EPSG:5179) and are converted here. This is the authoritative national address
database: use it for "주소로 찾기", and 브이월드 or another POI source for places.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

from ..api import PlaceResult
from .tm import to_wgs84

SEARCH_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
COORD_URL = "https://business.juso.go.kr/addrlink/addrCoordApi.do"

Opener = Callable[[str, float], bytes]


def _urlopen(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
        return response.read()


class JusoSearch:
    name = "juso"

    def __init__(self, search_key: str, coord_key: str, *, timeout: float = 5.0, opener: Opener = _urlopen) -> None:
        self.search_key = search_key
        self.coord_key = coord_key
        self.timeout = timeout
        self.opener = opener

    def _get(self, url: str, params: dict[str, str]) -> list[dict]:
        payload = json.loads(self.opener(f"{url}?{urllib.parse.urlencode(params)}", self.timeout).decode("utf-8"))
        results = payload.get("results", {})
        common = results.get("common", {})
        if str(common.get("errorCode", "0")) != "0":
            raise RuntimeError(f"도로명주소 API 오류 {common.get('errorCode')}: {common.get('errorMessage', '')}")
        return results.get("juso") or []

    def search(self, query: str, near: tuple[float, float] | None = None, size: int = 5) -> list[PlaceResult]:
        found = self._get(
            SEARCH_URL,
            {"confmKey": self.search_key, "currentPage": "1", "countPerPage": str(size), "keyword": query, "resultType": "json"},
        )
        results = []
        for item in found[:size]:
            keys = {k: str(item.get(k, "")) for k in ("admCd", "rnMgtSn", "udrtYn", "buldMnnm", "buldSlno")}
            coords = self._get(COORD_URL, {"confmKey": self.coord_key, "resultType": "json", **keys})
            if not coords:
                continue
            try:
                lat, lon = to_wgs84(float(coords[0]["entX"]), float(coords[0]["entY"]), 5179)
            except (KeyError, TypeError, ValueError):
                continue
            results.append(
                PlaceResult(
                    name=item.get("bdNm") or item.get("roadAddr", ""),
                    lat=lat,
                    lon=lon,
                    address=item.get("roadAddr", ""),
                    category="주소",
                    source="juso",
                )
            )
        return results
