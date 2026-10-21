"""Archive ITS link speeds and learn historical profiles from them.

Backtesting ETAs and learning 시간대별 평소 속도 both need months of past
speeds, so start recording early:

    ITS_API_KEY=… python -m mixnavuts archive --bbox 126.76,37.41,127.18,37.70 --db its.sqlite
"""

from __future__ import annotations

import sqlite3
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..network import RoadNetwork
from ..traffic import DAY_S, ProfileTraffic, typical_class_profiles
from .its import KST, ItsClient

_SCHEMA = """
CREATE TABLE IF NOT EXISTS link_speed (
    link_id TEXT NOT NULL,
    observed_at INTEGER NOT NULL,
    speed_kmh REAL NOT NULL,
    PRIMARY KEY (link_id, observed_at)
);
CREATE TABLE IF NOT EXISTS event (
    link_id TEXT NOT NULL,
    start_at INTEGER,
    end_at INTEGER,
    event_type TEXT,
    detail TEXT,
    message TEXT,
    seen_at INTEGER NOT NULL,
    PRIMARY KEY (link_id, start_at, event_type)
);
"""


def open_archive(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.executescript(_SCHEMA)
    return db


def record_once(client: ItsClient, db: sqlite3.Connection, clock=time.time) -> tuple[int, int]:
    now = int(clock())
    speeds = [(s.link_id, int(s.observed_at or now), s.speed_kmh) for s in client.traffic()]
    events = [
        (e.link_id, int(e.start) if e.start else None, int(e.end) if e.end else None, e.event_type, e.detail, e.message, now)
        for e in client.events()
    ]
    with db:
        db.executemany("INSERT OR IGNORE INTO link_speed VALUES (?, ?, ?)", speeds)
        db.executemany(
            "INSERT INTO event VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(link_id, start_at, event_type) DO UPDATE SET end_at = excluded.end_at, seen_at = excluded.seen_at",
            events,
        )
    return len(speeds), len(events)


def run_recorder(client: ItsClient, db: sqlite3.Connection, interval_s: float = 300.0) -> None:
    while True:
        started = time.time()
        try:
            speeds, events = record_once(client, db)
            print(f"{datetime.now(KST):%Y-%m-%d %H:%M:%S} 속도 {speeds}건 · 돌발 {events}건 저장")
        except Exception as exc:  # a failed poll must not stop a months-long recording
            print(f"{datetime.now(KST):%Y-%m-%d %H:%M:%S} 수집 실패: {exc}")
        time.sleep(max(1.0, interval_s - (time.time() - started)))


def learn_profiles(
    db: sqlite3.Connection,
    network: RoadNetwork,
    *,
    bucket_s: float = 900.0,
    weekdays_only: bool = True,
    min_samples: int = 3,
) -> ProfileTraffic:
    """Median speed per link per time-of-day bucket, as a share of the limit.

    Buckets without enough samples are filled from the nearest learned
    bucket; links without data fall back to the class profile.
    """
    buckets = round(DAY_S / bucket_s)
    samples: dict[str, list[list[float]]] = defaultdict(lambda: [[] for _ in range(buckets)])
    for link_id, observed_at, speed in db.execute("SELECT link_id, observed_at, speed_kmh FROM link_speed"):
        local = datetime.fromtimestamp(observed_at, KST)
        if weekdays_only and local.weekday() >= 5:
            continue
        seconds = local.hour * 3600 + local.minute * 60 + local.second
        samples[link_id][int(seconds // bucket_s)].append(speed)

    profiles: dict[int, list[float]] = {}
    for link_id, rows in samples.items():
        edge = network.graph.edge_by_ext(link_id)
        if edge is None:
            continue
        learned = [
            min(1.2, max(0.05, statistics.median(row) / edge.speed_limit_kmh)) if len(row) >= min_samples else None
            for row in rows
        ]
        known = [i for i, value in enumerate(learned) if value is not None]
        if not known:
            continue
        profile = []
        for i, value in enumerate(learned):
            if value is None:
                nearest = min(known, key=lambda k: min(abs(k - i), buckets - abs(k - i)))
                value = learned[nearest]
            profile.append(value)
        profiles[edge.id] = profile
    return ProfileTraffic(profiles, class_profiles=typical_class_profiles(bucket_s), bucket_s=bucket_s)
