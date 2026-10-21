"""Command line: `python -m mixnavuts route|backtest|places`."""

from __future__ import annotations

import argparse
import random
import sys

from .backtest import STRATEGIES, format_report, knowledge_at, run_backtest
from .candidates import candidate_stats, generate_candidates
from .evaluate import RouteEvaluation, evaluate
from .graph import RoadGraph
from .ranking import MODES, select_routes
from .synthetic import build_city, realize_day
from .text import clock, duration


def parse_clock(text: str) -> float:
    hours, _, minutes = text.partition(":")
    return int(hours) * 3600 + int(minutes or 0) * 60


def road_summary(ev: RouteEvaluation, min_m: float = 800.0, limit: int = 5) -> str:
    groups: list[list] = []  # [name, metres]
    for edge in ev.route.edges:
        if groups and groups[-1][0] == edge.name:
            groups[-1][1] += edge.length_m
        else:
            groups.append([edge.name, edge.length_m])
    names = [name for name, metres in groups if metres >= min_m and name != "이면도로" and not name.endswith(" IC")]
    names = [name for i, name in enumerate(names) if i == 0 or names[i - 1] != name]
    if len(names) > limit:
        names = names[: limit - 1] + ["…", names[-1]]
    return " → ".join(names) or "이면도로"


def cmd_places(args: argparse.Namespace) -> int:
    city = build_city()
    for name, node_id in sorted(city.graph.places().items(), key=lambda item: item[1]):
        node = city.graph.nodes[node_id]
        print(f"{name}\t(x {node.x / 1000:.1f} km, y {node.y / 1000:.1f} km)")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    city = build_city()
    g: RoadGraph = city.graph
    try:
        source, target = g.resolve(args.origin), g.resolve(args.destination)
    except KeyError as exc:
        print(f"{exc.args[0]} — `python -m mixnavuts places`로 장소 목록을 확인하세요.", file=sys.stderr)
        return 2
    depart = parse_clock(args.depart)
    rng = random.Random(args.seed)
    today = realize_day(city, rng)
    knowledge = knowledge_at(city, today, depart, rng)
    model = STRATEGIES["live+history+incidents"](knowledge)

    routes = generate_candidates(g, source, target, model, depart)
    if not routes:
        print("경로를 찾을 수 없습니다.", file=sys.stderr)
        return 1
    evaluations = [evaluate(route, model, depart) for route in routes]
    suggestions = select_routes(evaluations, MODES[args.mode], k=args.k)
    fastest = min(evaluations, key=lambda ev: ev.arrival)

    stats = ", ".join(f"{tag} {count}" for tag, count in candidate_stats(routes).items())
    print(f"MIXNAVUTS · {args.origin} → {args.destination} · 출발 {clock(depart)} · 모드 {args.mode}")
    print(f"후보 {len(routes)}개 ({stats}) → 시간 의존 ETA 평가 → {len(suggestions)}개 제시")
    if knowledge.reports:
        print(f"반영된 돌발상황 {len(knowledge.reports)}건")
    print("[합성 도시 · 합성 교통 데이터]\n")
    for rank, suggestion in enumerate(suggestions, 1):
        ev = suggestion.evaluation
        extra = ev.duration_s - fastest.duration_s
        delta = f" (+{extra / 60:.0f}분)" if extra >= 30 else ""
        print(f"[{rank}] {' · '.join(suggestion.labels)}")
        print(
            f"    도착 {clock(ev.arrival)}  소요 {duration(ev.duration_s)}{delta}  ·  {ev.distance_m / 1000:.1f} km"
            f"  ·  통행료 {ev.toll_krw:,}원  ·  고속도로 {ev.highway_share:.0%}"
        )
        print(f"    {road_summary(ev)}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    print(format_report(run_backtest(days=args.days, trips_per_day=args.trips, seed=args.seed)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mixnavuts", description="MIXNAVUTS engine prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    places = sub.add_parser("places", help="합성 도시의 장소 목록")
    places.set_defaults(func=cmd_places)

    route = sub.add_parser("route", help="후보 경로를 탐색하고 3~5개를 제시")
    route.add_argument("origin", help="출발지 이름 또는 노드 번호")
    route.add_argument("destination", help="도착지 이름 또는 노드 번호")
    route.add_argument("--depart", default="08:10", help="출발 시각 HH:MM (기본 08:10)")
    route.add_argument("--mode", choices=sorted(MODES), default="balanced", help="주행 목적")
    route.add_argument("--k", type=int, default=4, help="제시할 경로 수")
    route.add_argument("--seed", type=int, default=1, help="오늘의 교통 상황(합성) 시드")
    route.set_defaults(func=cmd_route)

    backtest = sub.add_parser("backtest", help="ETA 예측 전략 비교")
    backtest.add_argument("--days", type=int, default=4)
    backtest.add_argument("--trips", type=int, default=15, help="하루당 주행 수")
    backtest.add_argument("--seed", type=int, default=7)
    backtest.set_defaults(func=cmd_backtest)

    args = parser.parse_args(argv)
    return args.func(args)
