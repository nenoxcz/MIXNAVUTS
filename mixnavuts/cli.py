"""Command line: `python -m mixnavuts route|serve|archive|backtest|places|nodelink-info`."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from .api import ApiError, Engine, local_day_start, serve
from .backtest import format_report, run_backtest
from .live import SyntheticFeed
from .network import synthetic_network
from .ranking import MODES
from .synthetic import build_city, realize_day
from .text import clock, duration


def parse_clock(text: str) -> float:
    hours, _, minutes = text.partition(":")
    return int(hours) * 3600 + int(minutes or 0) * 60


def cmd_places(args: argparse.Namespace) -> int:
    city = build_city()
    for name, node_id in sorted(city.graph.places().items(), key=lambda item: item[1]):
        node = city.graph.nodes[node_id]
        print(f"{name}\t(x {node.x / 1000:.1f} km, y {node.y / 1000:.1f} km)")
    return 0


def synthetic_engine(seed: int) -> Engine:
    city = build_city()
    return Engine(synthetic_network(city=city), SyntheticFeed(city, realize_day(city, random.Random(seed)), seed))


def cmd_route(args: argparse.Namespace) -> int:
    engine = synthetic_engine(args.seed)
    depart = local_day_start(time.time()) + parse_clock(args.depart)
    body = {
        "origin": {"place": args.origin},
        "destination": {"place": args.destination},
        "depart": depart,
        "mode": args.mode,
        "k": args.k,
    }
    try:
        plan = engine.plan(body)
    except ApiError as exc:
        print(f"{exc.message} — `python -m mixnavuts places`로 장소 목록을 확인하세요.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 0

    stats = ", ".join(f"{tag} {count}" for tag, count in plan["candidate_sources"].items())
    fastest_s = min(route["duration_s"] for route in plan["routes"])
    print(f"MIXNAVUTS · {args.origin} → {args.destination} · 출발 {clock(depart - local_day_start(depart))} · 모드 {args.mode}")
    print(f"후보 {plan['candidates']}개 ({stats}) → 시간 의존 ETA 평가 → {len(plan['routes'])}개 제시")
    if plan["live"]["incidents"]:
        print(f"반영된 돌발상황 {plan['live']['incidents']}건")
    print("[합성 도시 · 합성 교통 데이터]\n")
    for rank, route in enumerate(plan["routes"], 1):
        extra = route["duration_s"] - fastest_s
        delta = f" (+{extra / 60:.0f}분)" if extra >= 30 else ""
        arrival = route["arrival"] - local_day_start(route["arrival"])
        print(f"[{rank}] {' · '.join(route['labels'])}")
        print(
            f"    도착 {clock(arrival)}  소요 {duration(route['duration_s'])}{delta}  ·  {route['distance_m'] / 1000:.1f} km"
            f"  ·  통행료 {route['toll_krw']:,}원  ·  고속도로 {route['highway_share']:.0%}"
        )
        print(f"    {route['summary']}")
    return 0


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    values = tuple(float(v) for v in text.split(","))
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise argparse.ArgumentTypeError("bbox는 최소경도,최소위도,최대경도,최대위도 형식")
    return values  # type: ignore[return-value]


def build_engine(args: argparse.Namespace) -> Engine:
    if args.network == "synthetic":
        return synthetic_engine(args.seed)
    from .korea.archive import learn_profiles, open_archive
    from .korea.its import ItsClient, ItsFeed
    from .korea.kakao import KakaoLocalSearch
    from .korea.nodelink import load_nodelink

    if not args.nodelink or not args.bbox:
        raise SystemExit("--network nodelink에는 --nodelink DIR 과 --bbox 가 필요합니다.")
    network = load_nodelink(args.nodelink, epsg=args.epsg, bbox=args.bbox)
    if args.archive:
        network.historical = learn_profiles(open_archive(args.archive), network)
    its_key, kakao_key = os.environ.get("ITS_API_KEY"), os.environ.get("KAKAO_REST_API_KEY")
    feed = ItsFeed(ItsClient(its_key, args.bbox), network) if its_key else None
    search = KakaoLocalSearch(kakao_key) if kakao_key else None
    return Engine(network, feed, search)


def cmd_serve(args: argparse.Namespace) -> int:
    engine = build_engine(args)
    health = engine.health()
    server = serve(engine, args.host, args.port)
    print(
        f"MIXNAVUTS Engine API · {health['network']} ({health['nodes']:,} nodes, {health['edges']:,} links)"
        f" · live {health['live']['source']} · search {health['search']}"
    )
    print(f"http://{args.host}:{args.port}/v1/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    from .korea.archive import open_archive, record_once, run_recorder
    from .korea.its import ItsClient

    key = os.environ.get("ITS_API_KEY")
    if not key:
        print("ITS_API_KEY 환경 변수가 필요합니다.", file=sys.stderr)
        return 2
    client, db = ItsClient(key, args.bbox), open_archive(args.db)
    if args.once:
        speeds, events = record_once(client, db)
        print(f"속도 {speeds}건 · 돌발 {events}건 저장 → {args.db}")
    else:
        run_recorder(client, db, args.interval)
    return 0


def cmd_nodelink_info(args: argparse.Namespace) -> int:
    from .korea.nodelink import describe

    print(describe(args.directory, args.encoding))
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
    route.add_argument("--json", action="store_true", help="API 응답 JSON으로 출력")
    route.set_defaults(func=cmd_route)

    server = sub.add_parser("serve", help="엔진 HTTP API 서버 실행")
    server.add_argument("--host", default="0.0.0.0")
    server.add_argument("--port", type=int, default=8080)
    server.add_argument("--network", choices=["synthetic", "nodelink"], default="synthetic")
    server.add_argument("--nodelink", metavar="DIR", help="국가표준노드링크 shapefile 폴더")
    server.add_argument("--bbox", type=parse_bbox, help="최소경도,최소위도,최대경도,최대위도")
    server.add_argument("--epsg", type=int, default=5186, help="노드링크 좌표계 (기본 5186)")
    server.add_argument("--archive", metavar="DB", help="ITS 속도 아카이브(SQLite)로 평소 패턴 학습")
    server.add_argument("--seed", type=int, default=1, help="합성 교통 시드")
    server.set_defaults(func=cmd_serve)

    archive = sub.add_parser("archive", help="ITS 실시간 속도·돌발 정보를 SQLite에 계속 저장")
    archive.add_argument("--bbox", type=parse_bbox, required=True, help="최소경도,최소위도,최대경도,최대위도")
    archive.add_argument("--db", default="its.sqlite")
    archive.add_argument("--interval", type=float, default=300.0, help="수집 간격(초)")
    archive.add_argument("--once", action="store_true", help="한 번만 수집")
    archive.set_defaults(func=cmd_archive)

    info = sub.add_parser("nodelink-info", help="표준노드링크 shapefile 필드 확인")
    info.add_argument("directory")
    info.add_argument("--encoding", default="cp949")
    info.set_defaults(func=cmd_nodelink_info)

    backtest = sub.add_parser("backtest", help="ETA 예측 전략 비교")
    backtest.add_argument("--days", type=int, default=4)
    backtest.add_argument("--trips", type=int, default=15, help="하루당 주행 수")
    backtest.add_argument("--seed", type=int, default=7)
    backtest.set_defaults(func=cmd_backtest)

    args = parser.parse_args(argv)
    return args.func(args)
