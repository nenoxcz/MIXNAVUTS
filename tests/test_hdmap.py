import tempfile
import unittest
from pathlib import Path

from test_korea import CITY_HALL, small_nodelink, tm

from mixnavuts.api import Engine
from mixnavuts.korea.cameras import camera_kind, load_cameras
from mixnavuts.korea.hdmap import LaneGraph, LaneLink, attach_lanes, attach_points, load_hdmap
from mixnavuts.korea.nodelink import build_network
from mixnavuts.korea.tm import detect_epsg
from mixnavuts.roadinfo import RoadDetails, rule_lanes

try:
    import shapefile  # pyshp
except ImportError:
    shapefile = None

DEPART = 1_792_537_800

PRJ_5186 = (
    'PROJCS["Korea_2000_Korea_Central_Belt_2010",GEOGCS["GCS_Korea_2000",DATUM["D_Korea_2000",'
    'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",200000.0],PARAMETER["False_Northing",600000.0],'
    'PARAMETER["Central_Meridian",127.0],PARAMETER["Scale_Factor",1.0],PARAMETER["Latitude_Of_Origin",38.0],UNIT["Meter",1.0]]'
)
PRJ_5179 = (
    'PROJCS["Korea_2000_Korea_Unified_Coordinate_System",GEOGCS["GCS_Korea_2000",DATUM["D_Korea_2000",'
    'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",1000000.0],PARAMETER["False_Northing",2000000.0],'
    'PARAMETER["Central_Meridian",127.5],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",38.0],UNIT["Meter",1.0]]'
)


def junction_lanes() -> list[LaneLink]:
    """을지로(2000000001, 3 lanes) → junction → 세종대로 south (2000000003) or the motorway (2000000007).

    Only lane 3 has a connector to the right turn; lanes 1 and 2 go straight onto the motorway.
    """
    links = [LaneLink(f"L{n}", f"a{n}", f"b{n}", n, "2000000001", 390.0) for n in (1, 2, 3)]
    links += [
        LaneLink("J3", "b3", "c3", 0, "", 25.0),  # right-turn connector
        LaneLink("S1", "c3", "d1", 1, "2000000003", 500.0),
        LaneLink("J1", "b1", "c1", 0, "", 30.0),
        LaneLink("J2", "b2", "c2", 0, "", 30.0),
        LaneLink("M1", "c1", "e1", 1, "2000000007", 1_000.0),
        LaneLink("M2", "c2", "e2", 2, "2000000007", 1_000.0),
    ]
    return links


class LaneGraphTest(unittest.TestCase):
    def test_recommendations_follow_connectors(self) -> None:
        graph = LaneGraph(junction_lanes())
        self.assertEqual(graph.lane_count("2000000001"), 3)
        self.assertEqual(graph.recommend("2000000001", "2000000003"), (3,))
        self.assertEqual(graph.recommend("2000000001", "2000000007"), (1, 2))
        self.assertIsNone(graph.recommend("2000000001", "9999999999"))

    def test_junction_budget_stops_long_searches(self) -> None:
        links = junction_lanes()
        far = [
            LaneLink("J3", "b3", "c3", 0, "", 25.0),
            LaneLink("X", "c3", "c4", 0, "", 400.0),  # a connector longer than the junction budget
            LaneLink("S1", "c4", "d1", 1, "2000000003", 1),
        ]
        graph = LaneGraph([link for link in links if link.id not in ("J3", "S1")] + far)
        self.assertIsNone(graph.recommend("2000000001", "2000000003"))

    def test_rule_lanes(self) -> None:
        self.assertEqual(rule_lanes(3, "turn", "left"), (1,))
        self.assertEqual(rule_lanes(3, "turn", "right"), (3,))
        self.assertEqual(rule_lanes(4, "turn", "straight"), (2, 3))
        self.assertEqual(rule_lanes(4, "ramp_off", "slight_right"), (3, 4))
        self.assertEqual(rule_lanes(3, "fork", "slight_left"), (1,))

    def test_lane_hint_skips_single_lane_and_all_lane_cases(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)
        a, b = net.graph.edge_by_ext("2000000001"), net.graph.edge_by_ext("2000000003")
        details = RoadDetails()
        self.assertIsNone(details.lane_hint(a, b, "turn", "right"))  # lane count unknown
        details.lane_count[a.id] = 3
        self.assertEqual(details.lane_hint(a, b, "turn", "right").recommended, (3,))
        self.assertIsNone(details.lane_hint(a, b, "continue", "straight"))
        details.lane_count[a.id] = 2
        self.assertIsNone(details.lane_hint(a, b, "turn", "straight"))  # both lanes go straight


class HdMapNetworkTest(unittest.TestCase):
    def network(self):
        nodes, links = small_nodelink()
        return build_network(nodes, links)

    def test_engine_returns_hd_lane_guidance_and_light_alert(self) -> None:
        net = self.network()
        graph = LaneGraph(junction_lanes())
        self.assertEqual(attach_lanes(net, graph), 3)
        lat, lon = CITY_HALL
        light = ({"ID": "T1", "LinkID": "L3"}, [tm(lat, lon + 0.0044)])  # near the end of 을지로
        self.assertEqual(attach_points(net, graph, [light], "traffic_light", 5186), 1)
        node3 = net.graph.nodes[net.graph.edge_by_ext("2000000003").target]
        lat3, lon3 = net.projection.to_latlon(node3.x, node3.y)
        plan = Engine(net).plan({"origin": {"place": "서울시청앞"}, "destination": {"lat": lat3, "lon": lon3}, "depart": DEPART})
        route = plan["routes"][0]
        self.assertEqual([s["link_id"] for s in route["segments"]], ["2000000001", "2000000003"])
        turn = next(m for m in route["maneuvers"] if m["type"] == "turn")
        self.assertEqual(turn["lanes"], {"count": 3, "recommended": [3]})
        (alert,) = route["alerts"]
        self.assertEqual(alert["type"], "traffic_light")
        self.assertAlmostEqual(alert["distance_m"], 390, delta=15)

    def test_prj_detection(self) -> None:
        self.assertEqual(detect_epsg(PRJ_5186), 5186)
        self.assertEqual(detect_epsg(PRJ_5179), 5179)
        self.assertIsNone(detect_epsg('GEOGCS["WGS 84"]'))

    @unittest.skipIf(shapefile is None, "pyshp not installed")
    def test_load_hdmap_shapefiles(self) -> None:
        net = self.network()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "정밀도로지도" / "서울"
            folder.mkdir(parents=True)
            w = shapefile.Writer(str(folder / "A2_LINK"), shapeType=shapefile.POLYLINEZ)
            for name in ("ID", "FromNodeID", "ToNodeID", "ITSLinkID"):
                w.field(name, "C", 20)
            w.field("LaneNo", "N", 4)
            w.field("Length", "N", 12, 3)
            lat, lon = CITY_HALL
            for link in junction_lanes():
                w.linez([[(*tm(lat, lon), 30.0), (*tm(lat, lon + 0.001), 30.0)]])
                w.record(link.id, link.from_node, link.to_node, link.its_link, link.lane_no, link.length_m)
            w.close()
            (folder / "A2_LINK.prj").write_text(PRJ_5186)
            w = shapefile.Writer(str(folder / "C1_TRAFFICLIGHT"), shapeType=shapefile.POINTZ)
            w.field("ID", "C", 20)
            w.field("LinkID", "C", 20)
            w.pointz(*tm(lat, lon + 0.0044), 35.0)
            w.record("T1", "L3")
            w.close()
            summary = load_hdmap(net, tmp)
        self.assertEqual(summary, {"lane_links": 9, "links_with_lanes": 3, "lights": 1, "bumps": 0})
        self.assertEqual(net.details.lane_count[net.graph.edge_by_ext("2000000001").id], 3)


class CameraTest(unittest.TestCase):
    def test_kinds(self) -> None:
        self.assertEqual(camera_kind("01"), "speed_camera")
        self.assertEqual(camera_kind("신호단속"), "signal_camera")
        self.assertEqual(camera_kind("과속"), "speed_camera")
        self.assertEqual(camera_kind("1", section="시점"), "section_camera")
        self.assertIsNone(camera_kind("불법주정차"))

    def test_cameras_become_route_alerts(self) -> None:
        nodes, links = small_nodelink()
        net = build_network(nodes, links)
        lat, lon = CITY_HALL
        rows = [
            "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소",
            f"C1,{lat + 0.00005},{lon + 0.002},1,50,을지로 시청방향",
            f"C2,{lat},{lon + 0.003},불법주정차,0,을지로",
            "C3,,,1,50,좌표 없음",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cameras.csv"
            path.write_bytes("\n".join(rows).encode("cp949"))
            attached = load_cameras(net, path)
        self.assertEqual(attached, 2)  # both directions of 을지로
        plan = Engine(net).plan({"origin": {"place": "서울시청앞"}, "destination": {"place": "을지로입구"}, "depart": DEPART})
        (alert,) = plan["routes"][0]["alerts"]
        self.assertEqual((alert["type"], alert["speed_limit_kmh"], alert["label"]), ("speed_camera", 50, "과속 단속 50"))
        self.assertEqual(alert["note"], "을지로 시청방향")
        self.assertAlmostEqual(alert["distance_m"], 176, delta=10)


if __name__ == "__main__":
    unittest.main()
