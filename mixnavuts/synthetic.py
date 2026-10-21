"""A synthetic city for development and backtesting.

Nothing here is real data. The city has a street grid with arterials, two
tolled motorways that cross at a JC, a toll-free 국도 parallel to one of them
and a winding mountain road around the north. Historical profiles have
directional rush hours (inbound in the morning, outbound in the evening).
`realize_day` produces the "actual" traffic of one day: the usual profile
plus persistent day-to-day deviations and incidents the profile knows
nothing about.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .graph import RoadClass, RoadGraph
from .traffic import DAY_S, Incident, ProfileTraffic

BUCKET_S = 900.0
BUCKETS = round(DAY_S / BUCKET_S)

# (morning depth, evening depth): how much speed the rush hour takes away.
_RUSH_DEPTH = {
    RoadClass.MOTORWAY: (0.55, 0.50),
    RoadClass.RAMP: (0.45, 0.45),
    RoadClass.TRUNK: (0.35, 0.35),
    RoadClass.PRIMARY: (0.40, 0.40),
    RoadClass.SECONDARY: (0.30, 0.30),
    RoadClass.LOCAL: (0.12, 0.12),
}
_OBSERVED_SHARE = {  # detector / probe coverage by road class
    RoadClass.MOTORWAY: 1.0,
    RoadClass.RAMP: 1.0,
    RoadClass.TRUNK: 1.0,
    RoadClass.PRIMARY: 0.8,
    RoadClass.SECONDARY: 0.5,
    RoadClass.LOCAL: 0.2,
}


@dataclass
class City:
    graph: RoadGraph
    historical: ProfileTraffic
    intersections: list[int]  # street-grid nodes, where trips start and end


def build_city(n: int = 28, spacing_m: float = 700.0, seed: int = 7) -> City:
    rng = random.Random(seed)
    g = RoadGraph()
    names = {
        (0, n // 2 - 1): "서부터미널",
        (n - 1, n // 2 + 1): "동부산업단지",
        (n // 2, n // 2): "시청",
        (n // 3, n - 1): "북부캠퍼스",
        (3 * n // 4, 0): "남부물류센터",
        (3, 3): "남서주거단지",
    }
    grid = [[g.add_node(i * spacing_m, j * spacing_m, names.get((i, j), "")) for j in range(n)] for i in range(n)]
    trunk_row = 2 * n // 3

    def street(i: int, j: int, along_row: bool) -> tuple[RoadClass, float, str]:
        line = j if along_row else i
        axis = "동서대로" if along_row else "남북대로"
        if along_row and line == trunk_row:
            return RoadClass.TRUNK, 70.0, "국도 7호선"
        if line % 4 == 0:
            return RoadClass.PRIMARY, 60.0, f"{axis} {line}"
        if line % 4 == 2:
            return RoadClass.SECONDARY, 50.0, f"{axis} {line}"
        return RoadClass.LOCAL, 40.0, "이면도로"

    for i in range(n):
        for j in range(n):
            if i + 1 < n:
                cls, speed, name = street(i, j, along_row=True)
                length = spacing_m * rng.uniform(1.0, 1.06)
                g.add_road(grid[i][j], grid[i + 1][j], cls, speed, length_m=length, name=name)
            if j + 1 < n:
                cls, speed, name = street(i, j, along_row=False)
                length = spacing_m * rng.uniform(1.0, 1.06)
                g.add_road(grid[i][j], grid[i][j + 1], cls, speed, length_m=length, name=name)

    def motorway(points: list[tuple[float, float]], name: str, ic_every: int, shared: dict[tuple[float, float], int]) -> None:
        ids = []
        for k, (x, y) in enumerate(points):
            node = shared.get((x, y))
            if node is None:
                node = shared[(x, y)] = g.add_node(x, y, "")
            ids.append(node)
            if k % ic_every == 0:  # IC: ramps to the nearest grid intersection, 기본요금 on entry
                gi = min(n - 1, max(0, round(x / spacing_m)))
                gj = min(n - 1, max(0, round(y / spacing_m)))
                street_node = grid[gi][gj]
                ramp_m = g.euclidean_m(node, street_node) + 350.0
                g.add_edge(street_node, node, RoadClass.RAMP, 50.0, length_m=ramp_m, toll_krw=900, name=f"{name} IC")
                g.add_edge(node, street_node, RoadClass.RAMP, 50.0, length_m=ramp_m, name=f"{name} IC")
        for a, b in zip(ids, ids[1:]):
            length = g.euclidean_m(a, b)
            toll = int(round(length / 1000 * 60, -1))
            g.add_road(a, b, RoadClass.MOTORWAY, 100.0, length_m=length, toll_krw=toll, name=name)

    extent = (n - 1) * spacing_m
    m1_y = (n // 2 - 0.5) * spacing_m
    m2_x = (n // 4 - 0.5) * spacing_m
    step = 2 * spacing_m
    m1 = sorted({(min(extent, k * step + spacing_m / 2), m1_y) for k in range(n // 2)} | {(m2_x, m1_y)})
    m2 = sorted({(m2_x, min(extent, k * step + spacing_m / 2)) for k in range(n // 2)} | {(m2_x, m1_y)}, key=lambda p: p[1])
    shared: dict[tuple[float, float], int] = {}
    motorway(m1, "중앙고속도로", 2, shared)
    motorway(m2, "순환고속도로", 2, shared)

    # Mountain road: a winding arc north of the city, ending at a resort in the north-east.
    arc = []
    for k in range(13):
        x = extent * k / 12
        y = extent + 300.0 + 1_200.0 * math.sin(math.pi * k / 12)
        arc.append(g.add_node(x, y, "북동리조트" if k == 12 else ""))
    for a, b in zip(arc, arc[1:]):
        g.add_road(a, b, RoadClass.SECONDARY, 70.0, length_m=g.euclidean_m(a, b) * 1.25, curvature=0.85, name="산악도로")
    for k in (0, 4, 8, 12):
        node = g.nodes[arc[k]]
        entrance = grid[min(n - 1, round(node.x / spacing_m))][n - 1]
        g.add_road(
            arc[k],
            entrance,
            RoadClass.SECONDARY,
            50.0,
            length_m=g.euclidean_m(arc[k], entrance) * 1.2,
            curvature=0.4,
            name="산악도로 입구",
        )

    center = (extent / 2, extent / 2)
    return City(g, _historical_profiles(g, center, rng), [node for column in grid for node in column])


def _gauss(h: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((h - mu) / sigma) ** 2)


def _historical_profiles(g: RoadGraph, center: tuple[float, float], rng: random.Random) -> ProfileTraffic:
    profiles = {}
    for edge in g.edges:
        a, b = g.nodes[edge.source], g.nodes[edge.target]
        dx, dy = b.x - a.x, b.y - a.y
        mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
        cx, cy = center[0] - mx, center[1] - my
        norm = math.hypot(dx, dy) * math.hypot(cx, cy)
        cos = (dx * cx + dy * cy) / norm if norm else 0.0
        am_dir = 0.55 + 0.6 * max(0.0, cos)
        pm_dir = 0.55 + 0.6 * max(0.0, -cos)
        am, pm = _RUSH_DEPTH[edge.road_class]
        if edge.curvature >= 0.5:
            am, pm = 0.05, 0.08
        jitter = rng.uniform(0.85, 1.15)
        midday = 0.08 if edge.road_class in (RoadClass.PRIMARY, RoadClass.TRUNK, RoadClass.MOTORWAY) else 0.03
        profile = []
        for b_idx in range(BUCKETS):
            h = (b_idx + 0.5) * BUCKET_S / 3600.0
            loss = jitter * (am * am_dir * _gauss(h, 8.25, 0.75) + pm * pm_dir * _gauss(h, 18.5, 1.0))
            loss += midday * _gauss(h, 13.0, 2.0)
            profile.append(min(1.0, max(0.12, 1.0 - loss)))
        profiles[edge.id] = profile
    return ProfileTraffic(profiles, bucket_s=BUCKET_S)


@dataclass
class Day:
    truth: ProfileTraffic
    incidents: list[Incident]


def realize_day(city: City, rng: random.Random, n_incidents: tuple[int, int] = (6, 12)) -> Day:
    """The traffic that actually happens on one day."""
    g, hist = city.graph, city.historical
    intensity = rng.uniform(0.8, 1.3)  # weather, events: the whole city is a bit better or worse
    # Deviations from the usual: a slow part that lasts for hours and a fast
    # part (signal cycles, platoons) that a single reading cannot predict.
    slow_rho, slow_sigma = 0.95, 0.04
    fast_rho, fast_sigma = 0.5, 0.06
    factors: dict[int, list[float]] = {}
    for edge in g.edges:
        usual = hist.profiles[edge.id]
        slow = rng.gauss(0.0, slow_sigma / math.sqrt(1 - slow_rho**2))
        fast = 0.0
        row = []
        for b_idx in range(BUCKETS):
            slow = slow_rho * slow + rng.gauss(0.0, slow_sigma)
            fast = fast_rho * fast + rng.gauss(0.0, fast_sigma)
            congested = 1.0 - (1.0 - usual[b_idx]) * intensity
            row.append(min(1.1, max(0.05, congested * math.exp(slow + fast))))
        factors[edge.id] = row

    incidents = []
    busy = [e for e in g.edges if e.road_class in (RoadClass.MOTORWAY, RoadClass.TRUNK, RoadClass.PRIMARY)]
    for _ in range(rng.randint(*n_incidents)):
        edge = rng.choice(busy)
        start_b = rng.randrange(round(6 * 3600 / BUCKET_S), round(21 * 3600 / BUCKET_S))
        end_b = start_b + rng.randint(2, 8)
        severity = rng.uniform(0.12, 0.4)
        affected = {edge.id: severity}
        upstream = edge
        for hop in range(2):  # queues spill back onto the same road
            same_road = [e for e in g.in_edges(upstream.source) if e.name == edge.name and e.source != upstream.target]
            if not same_road:
                break
            upstream = same_road[0]
            affected[upstream.id] = min(1.0, severity * (2 + hop))
        for edge_id, factor in affected.items():
            row = factors[edge_id]
            for b_idx in range(start_b, min(end_b, BUCKETS)):
                row[b_idx] = min(row[b_idx], factor)
        incidents.append(Incident(frozenset([edge.id]), start_b * BUCKET_S, end_b * BUCKET_S, severity))
    return Day(ProfileTraffic(factors, bucket_s=BUCKET_S), incidents)


def observed_edges(city: City, rng: random.Random) -> list[int]:
    """Edges that have a detector or enough probe vehicles to report a speed."""
    return [e.id for e in city.graph.edges if rng.random() < _OBSERVED_SHARE[e.road_class]]
