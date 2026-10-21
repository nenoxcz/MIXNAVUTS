"""ETA backtest: does the engine know which route actually arrives first?

For each trip the engine only sees what would be available at departure
time: the historical profile, live speeds on observed edges and incident
reports. It picks a route and predicts an arrival. The route is then driven
through the day's actual traffic and compared with the true earliest
arrival (time-dependent Dijkstra on the actual traffic).

With real data the "actual traffic" is archived link speeds replayed in
time; here it is a synthetic day from `synthetic.realize_day`.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field

from .candidates import CandidateConfig, generate_candidates
from .evaluate import evaluate
from .ranking import MODES, select_routes
from .search import td_fastest_path
from .synthetic import City, Day, build_city, observed_edges, realize_day
from .text import pad
from .traffic import Incident, PredictiveTraffic, SnapshotTraffic, TrafficModel, observe


@dataclass(frozen=True)
class Trip:
    day: int
    source: int
    target: int
    depart: float


@dataclass(frozen=True)
class Knowledge:
    """What the engine can know at departure time."""

    city: City
    now: float
    observed: dict[int, float]
    reports: list[Incident]


Strategy = Callable[[Knowledge], TrafficModel]

STRATEGIES: dict[str, Strategy] = {
    "historical": lambda k: k.city.historical,
    "live_snapshot": lambda k: SnapshotTraffic(k.city.historical, k.now, k.observed),
    "live+history": lambda k: PredictiveTraffic(k.city.historical, k.now, k.observed),
    "live+history+incidents": lambda k: PredictiveTraffic(k.city.historical, k.now, k.observed, incidents=k.reports),
}
_DESCRIPTIONS = {
    "historical": "시간대별 평소 속도만",
    "live_snapshot": "현재 속도가 끝까지 유지된다고 가정",
    "live+history": "현재 속도 → 평소 패턴으로 수렴",
    "live+history+incidents": "+ 돌발상황 해소 예상시각 반영",
}


@dataclass
class StrategyResult:
    name: str
    predicted_s: list[float] = field(default_factory=list)  # ETA of the chosen route
    actual_s: list[float] = field(default_factory=list)  # the chosen route, driven
    best_s: list[float] = field(default_factory=list)  # true earliest arrival
    pool_best_s: list[float] = field(default_factory=list)  # best candidate, driven

    def summary(self) -> dict[str, float]:
        errors = [p - a for p, a in zip(self.predicted_s, self.actual_s)]
        abs_err = sorted(abs(e) for e in errors)
        p90 = abs_err[math.ceil(0.9 * len(abs_err)) - 1]
        regrets = [a - b for a, b in zip(self.actual_s, self.best_s)]
        hits = [r <= max(60.0, 0.02 * b) for r, b in zip(regrets, self.best_s)]
        return {
            "mae_min": statistics.fmean(abs_err) / 60,
            "p90_min": p90 / 60,
            "bias_min": statistics.fmean(errors) / 60,
            "mape_pct": 100 * statistics.fmean(abs(e) / a for e, a in zip(errors, self.actual_s)),
            "hit_rate_pct": 100 * sum(hits) / len(hits),
            "regret_min": statistics.fmean(regrets) / 60,
            "pool_regret_min": statistics.fmean(p - b for p, b in zip(self.pool_best_s, self.best_s)) / 60,
        }


def make_trips(city: City, rng: random.Random, days: int, trips_per_day: int, min_km: float = 5.0) -> list[Trip]:
    nodes = [city.graph.nodes[i] for i in city.intersections]
    trips = []
    for day in range(days):
        while sum(t.day == day for t in trips) < trips_per_day:
            a, b = rng.sample(nodes, 2)
            if math.hypot(a.x - b.x, a.y - b.y) < min_km * 1000:
                continue
            roll = rng.random()
            if roll < 0.4:
                hour = rng.uniform(7.0, 9.5)
            elif roll < 0.8:
                hour = rng.uniform(17.0, 19.5)
            else:
                hour = rng.uniform(6.0, 22.0)
            trips.append(Trip(day, a.id, b.id, hour * 3600))
    return trips


def knowledge_at(city: City, day: Day, now: float, rng: random.Random) -> Knowledge:
    edges = observed_edges(city, rng)
    observed = {i: v * max(0.5, rng.gauss(1.0, 0.06)) for i, v in observe(city.graph, day.truth, now, edges).items()}
    reports = [
        Incident(inc.edge_ids, inc.start, now + (inc.end - now) * rng.uniform(0.6, 1.5), inc.speed_factor)
        for inc in day.incidents
        if inc.start <= now < inc.end
    ]
    return Knowledge(city, now, observed, reports)


def run_backtest(
    days: int = 4,
    trips_per_day: int = 15,
    seed: int = 7,
    strategies: dict[str, Strategy] | None = None,
    config: CandidateConfig | None = None,
) -> list[StrategyResult]:
    strategies = strategies or STRATEGIES
    rng = random.Random(seed)
    city = build_city(seed=seed)
    realized = [realize_day(city, rng) for _ in range(days)]
    trips = make_trips(city, rng, days, trips_per_day)
    results = {name: StrategyResult(name) for name in strategies}
    g = city.graph
    for trip in trips:
        day = realized[trip.day]
        oracle = td_fastest_path(g, trip.source, trip.target, day.truth, trip.depart)
        if oracle is None:
            continue
        best_s = oracle[1] - trip.depart
        knowledge = knowledge_at(city, day, trip.depart, rng)
        for name, strategy in strategies.items():
            model = strategy(knowledge)
            routes = generate_candidates(g, trip.source, trip.target, model, trip.depart, config)
            evals = [evaluate(route, model, trip.depart) for route in routes]
            choice = select_routes(evals, MODES["fastest"], k=1)[0].evaluation
            r = results[name]
            r.predicted_s.append(choice.duration_s)
            r.actual_s.append(evaluate(choice.route, day.truth, trip.depart).duration_s)
            r.best_s.append(best_s)
            r.pool_best_s.append(min(evaluate(route, day.truth, trip.depart).duration_s for route in routes))
    return list(results.values())


def format_report(results: list[StrategyResult]) -> str:
    n = len(results[0].actual_s) if results else 0
    mean_min = statistics.fmean(results[0].best_s) / 60 if n else 0.0
    columns = [("MAE", "분"), ("P90", "분"), ("편향", "분"), ("MAPE", "%"), ("적중률", "%"), ("손실", "분"), ("후보풀", "분")]
    lines = [
        f"ETA 백테스트 — 합성 도시, {n}회 주행, 평균 {mean_min:.0f}분",
        "(합성 데이터: 절대 수치보다 전략 간 비교에 의미가 있음)",
        "",
        pad("전략", 24) + "".join(pad(name, 8, ">") for name, _ in columns),
        pad("", 24) + "".join(pad(f"({unit})", 8, ">") for _, unit in columns),
    ]
    for r in results:
        s = r.summary()
        values = [
            f"{s['mae_min']:.2f}",
            f"{s['p90_min']:.2f}",
            f"{s['bias_min']:+.2f}",
            f"{s['mape_pct']:.1f}",
            f"{s['hit_rate_pct']:.0f}",
            f"{s['regret_min']:.2f}",
            f"{s['pool_regret_min']:.2f}",
        ]
        lines.append(pad(r.name, 24) + "".join(pad(v, 8, ">") for v in values))
    lines += [
        "",
        *(f"  {pad(r.name, 24)}{_DESCRIPTIONS[r.name]}" for r in results if r.name in _DESCRIPTIONS),
        "",
        "  MAE·P90·편향  고른 경로의 예측 소요시간 − 실제 소요시간",
        "  적중률        실제로 가장 빨리 도착하는 경로(±max(1분, 2%))를 골랐는가",
        "  손실          고른 경로의 실제 소요시간 − 실제 최적 경로의 소요시간",
        "  후보풀        후보 중 실제로 가장 빠른 경로 − 실제 최적 (0이면 정답이 후보에 있었음)",
    ]
    return "\n".join(lines)
