import json
import random
import threading
import unittest
import urllib.error
import urllib.request

from mixnavuts.api import ApiError, Engine, local_day_start, serve
from mixnavuts.guidance import _with_ro, modifier
from mixnavuts.live import SyntheticFeed
from mixnavuts.network import synthetic_network
from mixnavuts.synthetic import build_city, realize_day

DEPART = 1_792_537_800.0  # 2026-10-21 08:10 KST


def engine() -> Engine:
    city = build_city()
    return Engine(synthetic_network(city=city), SyntheticFeed(city, realize_day(city, random.Random(1))), clock=lambda: DEPART)


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = engine()
        cls.plan = cls.engine.plan(
            {"origin": {"place": "서부터미널"}, "destination": {"place": "동부산업단지"}, "depart": DEPART, "k": 4}
        )

    def test_summary_fields(self) -> None:
        self.assertTrue(self.plan["synthetic"])
        self.assertGreater(self.plan["candidates"], 50)
        self.assertEqual(self.plan["live"]["source"], "synthetic")
        self.assertTrue(1 <= len(self.plan["routes"]) <= 4)

    def test_route_geometry_and_segments_line_up(self) -> None:
        for route in self.plan["routes"]:
            geometry, segments = route["geometry"], route["segments"]
            self.assertEqual(segments[0]["start_index"], 0)
            self.assertEqual(segments[-1]["end_index"], len(geometry) - 1)
            for a, b in zip(segments, segments[1:], strict=False):
                self.assertEqual(a["end_index"], b["start_index"])
            distances = [p[2] for p in geometry]
            self.assertEqual(distances, sorted(distances))
            self.assertAlmostEqual(distances[-1], route["distance_m"], delta=1.0)
            self.assertAlmostEqual(sum(s["duration_s"] for s in segments), route["duration_s"], delta=1.0)
            self.assertAlmostEqual(route["arrival"] - route["depart"], route["duration_s"], delta=1.0)

    def test_maneuvers(self) -> None:
        for route in self.plan["routes"]:
            maneuvers = route["maneuvers"]
            self.assertEqual(maneuvers[0]["type"], "depart")
            self.assertEqual(maneuvers[-1]["type"], "arrive")
            self.assertEqual(maneuvers[-1]["point_index"], len(route["geometry"]) - 1)
            for m in maneuvers:
                self.assertAlmostEqual(route["geometry"][m["point_index"]][2], m["distance_m"], delta=1.0)
                self.assertTrue(m["instruction"])

    def test_motorway_route_gets_ramp_instructions(self) -> None:
        route = next(r for r in self.plan["routes"] if r["highway_share"] > 0.5)
        types = [m["type"] for m in route["maneuvers"]]
        self.assertIn("ramp_on", types)
        self.assertIn("ramp_off", types)

    def test_lat_lon_origin_snaps_to_network(self) -> None:
        lat, lon = self.engine.network.latlon(self.engine.network.places()["시청"])
        plan = self.engine.plan(
            {"origin": {"lat": lat + 0.0005, "lon": lon}, "destination": {"place": "북부캠퍼스"}, "depart": DEPART, "k": 1}
        )
        first = plan["routes"][0]["geometry"][0]
        self.assertAlmostEqual(first[0], lat, places=4)
        self.assertAlmostEqual(first[1], lon, places=4)

    def test_errors(self) -> None:
        with self.assertRaises(ApiError):
            self.engine.plan({"origin": {"place": "없음"}, "destination": {"place": "시청"}})
        with self.assertRaises(ApiError):
            self.engine.plan({"origin": {"lat": 10.0, "lon": 10.0}, "destination": {"place": "시청"}})
        with self.assertRaises(ApiError):
            self.engine.plan({"origin": {"place": "시청"}, "destination": {"place": "시청"}})
        with self.assertRaises(ApiError):
            self.engine.plan({"origin": {"place": "시청"}, "destination": {"place": "서부터미널"}, "mode": "rally"})

    def test_scenic_route_reports_curves(self) -> None:
        plan = self.engine.plan(
            {"origin": {"place": "북부캠퍼스"}, "destination": {"place": "북동리조트"}, "depart": DEPART, "mode": "scenic"}
        )
        curves = [c for r in plan["routes"] for c in r["curves"]]
        self.assertTrue(curves)
        self.assertTrue(all(c["end_m"] > c["start_m"] for c in curves))

    def test_search_and_places(self) -> None:
        names = [p["name"] for p in self.engine.places()["places"]]
        self.assertIn("시청", names)
        results = self.engine.search("리조트")["results"]
        self.assertEqual([r["name"] for r in results], ["북동리조트"])


class HelpersTest(unittest.TestCase):
    def test_local_day_start_is_kst_midnight(self) -> None:
        start = local_day_start(DEPART)
        self.assertAlmostEqual(DEPART - start, 8 * 3600 + 10 * 60)

    def test_modifier(self) -> None:
        self.assertEqual(modifier(5), "straight")
        self.assertEqual(modifier(90), "left")
        self.assertEqual(modifier(-90), "right")
        self.assertEqual(modifier(-40), "slight_right")
        self.assertEqual(modifier(150), "sharp_left")
        self.assertEqual(modifier(178), "uturn")

    def test_korean_particle(self) -> None:
        self.assertEqual(_with_ro("국도 7호선"), "국도 7호선으로")
        self.assertEqual(_with_ro("동서대로 14"), "동서대로 14로")
        self.assertEqual(_with_ro("강변북로"), "강변북로로")
        self.assertEqual(_with_ro("올림픽대로 1"), "올림픽대로 1로")
        self.assertEqual(_with_ro("3"), "3으로")


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = serve(engine(), "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.server.log_message = lambda *a: None
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_health(self) -> None:
        status, payload = self.request("/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["network"], "synthetic")

    def test_routes(self) -> None:
        body = {"origin": {"place": "시청"}, "destination": {"place": "남부물류센터"}, "depart": DEPART, "k": 2}
        status, payload = self.request("/v1/routes", body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["routes"])

    def test_errors(self) -> None:
        self.assertEqual(self.request("/v1/routes", {"origin": {"place": "없음"}, "destination": {"place": "시청"}})[0], 404)
        self.assertEqual(self.request("/v1/search?q=")[0], 400)
        self.assertEqual(self.request("/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
