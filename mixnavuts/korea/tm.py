"""Transverse Mercator on GRS80 for the Korean coordinate systems.

국가표준노드링크 and many Korean datasets ship in TM coordinates. Formulas
follow Snyder, "Map Projections — A Working Manual" (USGS PP 1395), §8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_A = 6_378_137.0
_F = 1 / 298.257222101  # GRS80
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)


@dataclass(frozen=True)
class TransverseMercator:
    lat0: float
    lon0: float
    k0: float
    false_easting: float
    false_northing: float

    def _m(self, phi: float) -> float:
        e2, e4, e6 = _E2, _E2**2, _E2**3
        return _A * (
            (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
            - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
            + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
            - (35 * e6 / 3072) * math.sin(6 * phi)
        )

    def forward(self, lat: float, lon: float) -> tuple[float, float]:
        phi, lam = math.radians(lat), math.radians(lon)
        n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
        t = math.tan(phi) ** 2
        c = _EP2 * math.cos(phi) ** 2
        a = (lam - math.radians(self.lon0)) * math.cos(phi)
        m, m0 = self._m(phi), self._m(math.radians(self.lat0))
        x = self.k0 * n * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * _EP2) * a**5 / 120)
        y = self.k0 * (
            m
            - m0
            + n
            * math.tan(phi)
            * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a**4 / 24 + (61 - 58 * t + t * t + 600 * c - 330 * _EP2) * a**6 / 720)
        )
        return x + self.false_easting, y + self.false_northing

    def inverse(self, x: float, y: float) -> tuple[float, float]:
        e2, e4, e6 = _E2, _E2**2, _E2**3
        m = self._m(math.radians(self.lat0)) + (y - self.false_northing) / self.k0
        mu = m / (_A * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
        e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
        phi1 = (
            mu
            + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu)
            + (1097 * e1**4 / 512) * math.sin(8 * mu)
        )
        sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
        c1 = _EP2 * cos1**2
        t1 = tan1**2
        n1 = _A / math.sqrt(1 - e2 * sin1**2)
        r1 = _A * (1 - e2) / (1 - e2 * sin1**2) ** 1.5
        d = (x - self.false_easting) / (n1 * self.k0)
        phi = phi1 - (n1 * tan1 / r1) * (
            d * d / 2
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * _EP2) * d**4 / 24
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * _EP2 - 3 * c1 * c1) * d**6 / 720
        )
        lam = (
            d - (1 + 2 * t1 + c1) * d**3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * _EP2 + 24 * t1 * t1) * d**5 / 120
        ) / cos1
        return math.degrees(phi), self.lon0 + math.degrees(lam)


KOREAN_CRS: dict[int, TransverseMercator] = {
    5179: TransverseMercator(38.0, 127.5, 0.9996, 1_000_000.0, 2_000_000.0),  # UTM-K
    5181: TransverseMercator(38.0, 127.0, 1.0, 200_000.0, 500_000.0),  # 중부원점 (카카오맵 등)
    5185: TransverseMercator(38.0, 125.0, 1.0, 200_000.0, 600_000.0),  # 서부원점 2010
    5186: TransverseMercator(38.0, 127.0, 1.0, 200_000.0, 600_000.0),  # 중부원점 2010
    5187: TransverseMercator(38.0, 129.0, 1.0, 200_000.0, 600_000.0),  # 동부원점 2010
    5188: TransverseMercator(38.0, 131.0, 1.0, 200_000.0, 600_000.0),  # 동해원점 2010
}


def to_wgs84(x: float, y: float, epsg: int) -> tuple[float, float]:
    try:
        crs = KOREAN_CRS[epsg]
    except KeyError:
        raise ValueError(f"unsupported EPSG:{epsg}; known: {sorted(KOREAN_CRS)}") from None
    return crs.inverse(x, y)
