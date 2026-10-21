import json
import sqlite3
import tempfile
import unittest
import urllib.parse
from datetime import datetime
from pathlib import Path

from mixnavuts.api import Engine
from mixnavuts.graph import RoadClass
from mixnavuts.korea.archive import learn_profiles, open_archive, record_once
from mixnavuts.korea.its import KST, ItsClient, ItsFeed, parse_kst
from mixnavuts.korea.kakao import KakaoLocalSearch
from mixnavuts.korea.nodelink import build_network, load_nodelink
from mixnavuts.korea.tm import KOREAN_CRS, to_wgs84

try:
    import shapefile  # pyshp
except ImportError:
    shapefile = None

TM = KOREAN_CRS[5186]
CITY_HALL = (37.5665, 126.9780)


def tm(lat: float, lon: float) -> tuple[float, float]:
    return TM.forward(lat, lon)


def small_nodelink():
    """Four junctions around 서울시청 and a short tolled motorway east of them."""
    lat, lon = CITY_HALL
    d = 0.0045  # ≈ 500 m
    nodes = {
        "1000000001": ("서울시청앞", lat, lon),
        "1000000002": ("을지로입구", lat, lon + d),
        "1000000003": ("", lat - d, lon + d),
        "1000000004": ("", lat - d, lon),
        "1000000005": ("", lat, lon + 3 * d),
    }
    node_records = [
        ({"NODE_ID": nid, "NODE_NAME": name, "NODE_TYPE": "101"}, tm(la, lo)) for nid, (name, la, lo) in nodes.items()
    ]

    def link(link_id, f, t, rank="104", name="세종대로", speed=60, connect="000", bend=False):
        (_, la1, lo1), (_, la2, lo2) = nodes[f], nodes[t]
        points = [tm(la1, lo1)]
        if bend:
            points.append(tm((la1 + la2) / 2 + 0.001, (lo1 + lo2) / 2))
        points.append(tm(la2, lo2))
        record = {"LINK_ID": link_id, "F_NODE": f, "T_NODE": t, "ROAD_RANK": rank, "ROAD_NAME": name, "MAX_SPD": speed}
        record.update({"LENGTH": 0, "CONNECT": connect, "ROAD_NO": ""})
        return record, points

    links = [
        link("2000000001", "1000000001", "1000000002", name="을지로"),
        link("2000000002", "1000000002", "1000000001", name="을지로"),
        link("2000000003", "1000000002", "1000000003"),
        link("2000000004", "1000000003", "1000000004", bend=True),
        link("2000000005", "1000000004", "1000000001"),
        link("2000000006", "1000000001", "1000000004"),
        link("2000000007", "1000000002", "1000000005", rank="101", name="경부고속도로", speed=100),
        link("2000000008", "1000000005", "1000000002", rank="101", name="경부고속도로", speed=100, connect="101"),
    ]
    return node_records, links


class TmTest(unittest.TestCase):
    def test_origin_of_central_belt(self) -> None:
        lat, lon = to_wgs84(200_000.0, 600_000.0, 5186)
        self.assertAlmostEqual(lat, 38.0, places=9)
        self.assertAlmostEqual(lon, 127.0, places=9)

    def test_round_trip_all_belts(self) -> None:
        for epsg, crs in KOREAN_CRS.items():
            for lat, lon in [(37.5665, 126.978), (35.1796, 129.0756), (33.4996, 126.5312), (38.2, 128.6)]:
                back = to_wgs84(*crs.forward(lat, lon), epsg)
                self.assertAlmostEqual(back[0], lat, places=6, msg=epsg)
                self.assertAlmostEqual(back[1], lon, places=6, msg=epsg)

    def test_unknown_crs(self) -> None:
        with self.assertRaises(ValueError):
            to_wgs84(0, 0, 4326)


class NodeLinkTest(unittest.TestCase):
    def test_build_network(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)
        g = net.graph
        self.assertEqual(len(g.nodes), 5)
        self.assertEqual(len(g.edges), 8)
        motorway = g.edge_by_ext("2000000007")
        self.assertEqual(motorway.road_class, RoadClass.MOTORWAY)
        self.assertGreater(motorway.toll_krw, 0)
        self.assertEqual(g.edge_by_ext("2000000008").road_class, RoadClass.RAMP)
        self.assertGreater(g.edge_by_ext("2000000004").curvature, 0)
        self.assertIn(g.edge_by_ext("2000000004").id, net.shapes)
        self.assertAlmostEqual(g.edge_by_ext("2000000001").length_m, 396, delta=10)  # 0.0045° of longitude at 37.57°N
        self.assertEqual(net.places()["서울시청앞"], net.nearest(*CITY_HALL))

    def test_bbox_filter(self) -> None:
        nodes, links = small_nodelink()
        lat, lon = CITY_HALL
        net = build_network(nodes, links, bbox=(lon - 0.001, lat - 0.01, lon + 0.006, lat + 0.001))
        self.assertEqual(len(net.graph.nodes), 4)
        self.assertIsNone(net.graph.edge_by_ext("2000000007"))

    def test_engine_routes_on_real_coordinates(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)
        plan = Engine(net).plan(
            {"origin": {"place": "서울시청앞"}, "destination": {"place": "을지로입구"}, "depart": 1_792_537_800}
        )
        route = plan["routes"][0]
        self.assertFalse(plan["synthetic"])
        self.assertEqual([s["link_id"] for s in route["segments"]], ["2000000001"])
        self.assertAlmostEqual(route["geometry"][0][0], CITY_HALL[0], places=5)

    @unittest.skipIf(shapefile is None, "pyshp not installed")
    def test_load_shapefiles(self) -> None:
        nodes, links = small_nodelink()
        with tempfile.TemporaryDirectory() as tmp:
            w = shapefile.Writer(str(Path(tmp) / "MOCT_NODE"), shapeType=shapefile.POINT, encoding="cp949")
            for name in ("NODE_ID", "NODE_NAME", "NODE_TYPE"):
                w.field(name, "C", 30)
            for record, (x, y) in nodes:
                w.point(x, y)
                w.record(record["NODE_ID"], record["NODE_NAME"], record["NODE_TYPE"])
            w.close()
            w = shapefile.Writer(str(Path(tmp) / "MOCT_LINK"), shapeType=shapefile.POLYLINE, encoding="cp949")
            fields = ["LINK_ID", "F_NODE", "T_NODE", "ROAD_RANK", "ROAD_NAME", "MAX_SPD", "LENGTH", "CONNECT", "ROAD_NO"]
            for name in fields:
                w.field(name, "N" if name in ("MAX_SPD", "LENGTH") else "C", 30, 2 if name == "LENGTH" else 0)
            for record, points in links:
                w.line([points])
                w.record(*[record[f] for f in fields])
            w.close()
            net = load_nodelink(tmp)
        self.assertEqual(len(net.graph.edges), 8)
        self.assertIn("서울시청앞", net.places())


def its_payload(items) -> bytes:
    return json.dumps(
        {"header": {"resultCode": 0, "resultMsg": "success"}, "body": {"totalCount": len(items), "items": items}}
    ).encode()


class FakeIts:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        if "/trafficInfo" in url:
            return its_payload(
                [
                    {"linkId": "2000000001", "speed": "18.5", "travelTime": "77", "createdDate": "20261021080500"},
                    {"linkId": "2000000003", "speed": "0", "travelTime": "", "createdDate": "20261021080500"},
                    {"linkId": "9999999999", "speed": "50", "travelTime": "10", "createdDate": "20261021080500"},
                ]
            )
        return its_payload(
            [
                {
                    "type": "its",
                    "eventType": "사고",
                    "eventDetailType": "차량사고",
                    "startDate": "20261021074000",
                    "endDate": "",
                    "coordX": "126.98",
                    "coordY": "37.56",
                    "linkId": "2000000003",
                    "roadName": "세종대로",
                    "lanesBlocked": "1",
                    "message": "2차로 사고",
                }
            ]
        )


class ItsTest(unittest.TestCase):
    def test_parse_kst(self) -> None:
        self.assertEqual(datetime.fromtimestamp(parse_kst("20261021080500"), KST).strftime("%H:%M:%S"), "08:05:00")
        self.assertIsNone(parse_kst(""))

    def test_client_query_and_parsing(self) -> None:
        fake = FakeIts()
        client = ItsClient("KEY", (126.9, 37.5, 127.1, 37.6), opener=fake)
        speeds = client.traffic()
        self.assertEqual([s.link_id for s in speeds], ["2000000001", "9999999999"])  # 0 km/h is "no data"
        query = urllib.parse.parse_qs(urllib.parse.urlparse(fake.calls[0]).query)
        self.assertEqual(query["apiKey"], ["KEY"])
        self.assertEqual(query["minX"], ["126.9"])
        self.assertEqual(query["getType"], ["json"])
        events = client.events()
        self.assertEqual(events[0].event_type, "사고")
        self.assertIsNone(events[0].end)

    def test_error_header(self) -> None:
        def opener(url, timeout):
            return json.dumps({"header": {"resultCode": 99, "resultMsg": "인증키 오류"}}).encode()

        with self.assertRaises(RuntimeError):
            ItsClient("BAD", (0, 0, 1, 1), opener=opener).traffic()

    def test_feed_maps_links_to_edges(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)
        now = parse_kst("20261021081000")
        feed = ItsFeed(ItsClient("KEY", (126.9, 37.5, 127.1, 37.6), opener=FakeIts()), net, clock=lambda: now)
        day_start = parse_kst("20261021000000")
        snap = feed.snapshot(now, day_start)
        edge = net.graph.edge_by_ext("2000000001")
        self.assertEqual(snap.source, "its")
        self.assertAlmostEqual(snap.observed_mps[edge.id], 18.5 / 3.6)
        self.assertEqual(len(snap.observed_mps), 1)
        (incident,) = snap.incidents
        self.assertEqual(incident.edge_ids, {net.graph.edge_by_ext("2000000003").id})
        self.assertAlmostEqual(incident.start, 7 * 3600 + 40 * 60)
        self.assertGreater(incident.end, now - day_start)
        self.assertEqual(incident.speed_factor, 0.3)

    def test_feed_survives_api_failure(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)

        def broken(url, timeout):
            raise OSError("timeout")

        feed = ItsFeed(ItsClient("KEY", (0, 0, 1, 1), opener=broken), net)
        snap = feed.snapshot(0, 0)
        self.assertEqual(snap.observed_mps, {})
        self.assertIn("timeout", feed.last_error)


class KakaoTest(unittest.TestCase):
    def test_search(self) -> None:
        seen = {}

        def opener(request, timeout):
            seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
            return json.dumps(
                {
                    "documents": [
                        {
                            "place_name": "서울역",
                            "address_name": "서울 용산구 동자동 43-205",
                            "road_address_name": "서울 용산구 한강대로 405",
                            "category_name": "교통,수송 > 기차,철도 > 기차역",
                            "x": "126.970606917394",
                            "y": "37.5546788388674",
                        },
                        {"place_name": "broken", "x": "", "y": ""},
                    ],
                    "meta": {"total_count": 1},
                }
            ).encode()

        results = KakaoLocalSearch("REST", opener=opener).search("서울역", near=CITY_HALL)
        self.assertEqual(seen["auth"], "KakaoAK REST")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
        self.assertEqual(query["query"], ["서울역"])
        self.assertEqual(query["sort"], ["distance"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].address, "서울 용산구 한강대로 405")
        self.assertAlmostEqual(results[0].lat, 37.5546788388674)


class ArchiveTest(unittest.TestCase):
    def test_record_and_learn(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)
        db = open_archive(":memory:")
        speeds, events = record_once(ItsClient("KEY", (0, 0, 1, 1), opener=FakeIts()), db)
        self.assertEqual((speeds, events), (2, 1))
        # Three more weekday mornings at 08:05 so the bucket has enough samples.
        base = parse_kst("20261021080500")
        db.executemany(
            "INSERT INTO link_speed VALUES (?, ?, ?)", [("2000000001", int(base - d * 86400), 20.0) for d in (1, 2, 6)]
        )
        profiles = learn_profiles(db, net)
        edge = net.graph.edge_by_ext("2000000001")
        self.assertAlmostEqual(profiles.factor(edge, 8 * 3600 + 300), 20.0 / 60)  # median of 18.5, 20, 20, 20 over 60 km/h
        self.assertAlmostEqual(profiles.factor(edge, 3 * 3600), 20.0 / 60)  # filled from the nearest learned bucket
        other = net.graph.edge_by_ext("2000000005")
        self.assertLess(profiles.factor(other, 8.25 * 3600), 1.0)  # class profile fallback
        self.assertIsInstance(db, sqlite3.Connection)


if __name__ == "__main__":
    unittest.main()
