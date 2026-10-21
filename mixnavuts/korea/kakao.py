"""카카오 로컬 API: keyword place search (목적지 검색).

  GET https://dapi.kakao.com/v2/local/search/keyword.json?query=…[&x=lon&y=lat&sort=distance]
  Authorization: KakaoAK {REST API 키}

The REST API key is issued in Kakao Developers and must stay on the server.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

from ..api import PlaceResult

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

Opener = Callable[[urllib.request.Request, float], bytes]


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
        return response.read()


class KakaoLocalSearch:
    name = "kakao"

    def __init__(self, rest_api_key: str, *, timeout: float = 5.0, opener: Opener = _urlopen) -> None:
        self.rest_api_key = rest_api_key
        self.timeout = timeout
        self.opener = opener

    def search(self, query: str, near: tuple[float, float] | None = None, size: int = 15) -> list[PlaceResult]:
        params = {"query": query, "size": str(min(15, max(1, size)))}
        if near:
            params.update({"y": f"{near[0]}", "x": f"{near[1]}", "sort": "distance"})
        request = urllib.request.Request(
            f"{KAKAO_KEYWORD_URL}?{urllib.parse.urlencode(params)}",
            headers={"Authorization": f"KakaoAK {self.rest_api_key}"},
        )
        payload = json.loads(self.opener(request, self.timeout).decode("utf-8"))
        results = []
        for doc in payload.get("documents", []):
            try:
                lat, lon = float(doc["y"]), float(doc["x"])
            except (KeyError, TypeError, ValueError):
                continue
            results.append(
                PlaceResult(
                    name=doc.get("place_name", ""),
                    lat=lat,
                    lon=lon,
                    address=doc.get("road_address_name") or doc.get("address_name", ""),
                    category=doc.get("category_name", ""),
                    source="kakao",
                )
            )
        return results
