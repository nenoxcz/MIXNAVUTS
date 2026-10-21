import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from mixnavuts.api import Engine, serve
from mixnavuts.korea.juso import JusoSearch
from mixnavuts.korea.tm import KOREAN_CRS
from mixnavuts.korea.vworld import VWorldSearch, VWorldTiles
from mixnavuts.network import synthetic_network
from mixnavuts.tiles import EXTENT, TileRenderer, clip_line, tile_of

try:
    import mapbox_vector_tile
except ImportError:
    mapbox_vector_tile = None


# --- a minimal MVT reader, so the tests do not depend on a tile library ---


def _varint(data: bytes, i: int) -> tuple[int, int]:
    shift = value = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def _fields(data: bytes):
    i = 0
    while i < len(data):
        key, i = _varint(data, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(data, i)
        elif wire == 2:
            length, i = _varint(data, i)
            value, i = data[i : i + length], i + length
        elif wire == 1:
            value, i = data[i : i + 8], i + 8
        else:
            raise ValueError(f"wire type {wire}")
        yield field, value


def _packed(data: bytes) -> list[int]:
    out, i = [], 0
    while i < len(data):
        value, i = _varint(data, i)
        out.append(value)
    return out


def decode(tile: bytes) -> dict[str, dict]:
    layers = {}
    for field, layer_bytes in _fields(tile):
        assert field == 3
        layer = {"features": [], "keys": [], "values": [], "extent": None, "version": None}
        for f, v in _fields(layer_bytes):
            if f == 1:
                layer["name"] = v.decode()
            elif f == 2:
                feature = {}
                for ff, fv in _fields(v):
                    if ff == 2:
                        feature["tags"] = _packed(fv)
                    elif ff == 3:
                        feature["type"] = fv
                    elif ff == 4:
                        feature["geometry"] = _packed(fv)
                layer["features"].append(feature)
            elif f == 3:
                layer["keys"].append(v.decode())
            elif f == 4:
                layer["values"].append(next(_fields(v))[1])
            elif f == 5:
                layer["extent"] = v
            elif f == 15:
                layer["version"] = v
        for feature in layer["features"]:
            tags = feature.get("tags", [])
            feature["properties"] = {
                layer["keys"][k]: (val.decode() if isinstance(val, bytes) else val)
                for k, val in ((tags[i], layer["values"][tags[i + 1]]) for i in range(0, len(tags), 2))
            }
        layers[layer["name"]] = layer
    return layers


def first_point(geometry: list[int]) -> tuple[int, int]:
    unzig = [(v >> 1) ^ -(v & 1) for v in geometry[1:3]]
    return unzig[0], unzig[1]


class ClipTest(unittest.TestCase):
    def test_inside_line_is_kept(self) -> None:
        self.assertEqual(clip_line([(10, 10), (100, 100)]), [[(10, 10), (100, 100)]])

    def test_crossing_line_is_cut_at_the_buffer(self) -> None:
        (part,) = clip_line([(-1_000, 2_000), (2_000, 2_000)])
        self.assertEqual(part, [(-64, 2_000), (2_000, 2_000)])

    def test_outside_line_is_dropped_and_reentry_splits(self) -> None:
        self.assertEqual(clip_line([(-500, -500), (-400, -300)]), [])
        parts = clip_line([(100, 100), (100, -1_000), (300, -1_000), (300, 100)])
        self.assertEqual(len(parts), 2)


class TileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.network = synthetic_network()
        cls.renderer = TileRenderer(cls.network)
        cls.lat, cls.lon = cls.network.latlon(cls.network.places()["시청"])

    def test_city_tile_has_roads_and_alerts(self) -> None:
        z = 14
        x, y = tile_of(self.lat, self.lon, z)
        layers = decode(self.renderer.tile(z, x, y))
        roads, alerts = layers["roads"], layers["alerts"]
        self.assertEqual((roads["version"], roads["extent"]), (2, EXTENT))
        self.assertTrue(roads["features"])
        self.assertTrue(all(f["type"] == 2 for f in roads["features"]))
        classes = {f["properties"]["class"] for f in roads["features"]}
        self.assertIn("local", classes)
        self.assertTrue(all("name" in f["properties"] for f in roads["features"]))
        self.assertTrue({f["properties"]["type"] for f in alerts["features"]} <= {"traffic_light", "speed_bump", "speed_camera"})
        for feature in alerts["features"]:
            px, py = first_point(feature["geometry"])
            self.assertTrue(0 <= px < EXTENT and 0 <= py < EXTENT)

    def test_low_zoom_keeps_only_major_roads(self) -> None:
        z = 9
        x, y = tile_of(self.lat, self.lon, z)
        layers = decode(self.renderer.tile(z, x, y))
        classes = {f["properties"]["class"] for f in layers["roads"]["features"]}
        self.assertTrue(classes <= {"motorway", "trunk"})
        self.assertNotIn("alerts", layers)

    def test_empty_and_invalid_tiles(self) -> None:
        self.assertEqual(self.renderer.tile(14, 0, 0), b"")
        with self.assertRaises(ValueError):
            self.renderer.tile(3, 9, 0)

    @unittest.skipIf(mapbox_vector_tile is None, "mapbox-vector-tile not installed")
    def test_reference_decoder_agrees(self) -> None:
        x, y = tile_of(self.lat, self.lon, 13)
        decoded = mapbox_vector_tile.decode(self.renderer.tile(13, x, y))
        ours = decode(self.renderer.tile(13, x, y))
        self.assertEqual(len(decoded["roads"]["features"]), len(ours["roads"]["features"]))


class FakeBaseMap:
    content_type = "image/png"

    def tile(self, z: int, x: int, y: int) -> bytes:
        return b"\x89PNG" + bytes([z])


class MapHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = Engine(synthetic_network(), basemap=FakeBaseMap(), attribution="test")
        cls.server = serve(cls.engine, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path: str):
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as resp:
                return resp.status, resp.headers.get("Content-Type"), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers.get("Content-Type"), err.read()

    def test_style_points_at_this_server(self) -> None:
        status, _, body = self.get("/v1/style.json")
        style = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(style["version"], 8)
        self.assertEqual(style["sources"]["mixnavuts"]["tiles"], [f"{self.base}/v1/tiles/{{z}}/{{x}}/{{y}}.mvt"])
        self.assertEqual(style["sources"]["basemap"]["tiles"], [f"{self.base}/v1/basemap/{{z}}/{{x}}/{{y}}.png"])
        self.assertIn("alerts", [layer["id"] for layer in style["layers"]])

    def test_vector_and_base_tiles(self) -> None:
        lat, lon = self.engine.network.latlon(self.engine.network.places()["시청"])
        x, y = tile_of(lat, lon, 14)
        status, content_type, body = self.get(f"/v1/tiles/14/{x}/{y}.mvt")
        self.assertEqual((status, content_type), (200, "application/vnd.mapbox-vector-tile"))
        self.assertIn("roads", decode(body))
        status, content_type, body = self.get("/v1/basemap/12/3490/1590.png")
        self.assertEqual((status, content_type, body), (200, "image/png", b"\x89PNG\x0c"))
        self.assertEqual(self.get("/v1/tiles/3/99/0.mvt")[0], 400)

    def test_without_basemap(self) -> None:
        engine = Engine(synthetic_network())
        self.assertNotIn("basemap", engine.style("http://x")["sources"])
        self.assertIsNone(engine.health()["basemap"])


class VWorldTest(unittest.TestCase):
    def test_tiles_are_cached_and_keyed(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, request.get_header("Referer")))
            return b"tile"

        tiles = VWorldTiles("KEY", "Satellite", domain="https://mixnavuts.example", opener=opener)
        self.assertEqual(tiles.tile(15, 27940, 12700), b"tile")
        self.assertEqual(tiles.tile(15, 27940, 12700), b"tile")
        self.assertEqual(
            calls, [("https://api.vworld.kr/req/wmts/1.0.0/KEY/Satellite/15/12700/27940.jpeg", "https://mixnavuts.example")]
        )
        self.assertEqual(tiles.content_type, "image/jpeg")
        with self.assertRaises(ValueError):
            tiles.tile(3, 0, 0)

    def test_search_falls_back_to_addresses(self) -> None:
        seen = []

        def opener(request, timeout):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            seen.append(query["type"][0])
            if query["type"] == ["place"]:
                return json.dumps({"response": {"status": "NOT_FOUND"}}).encode()
            return json.dumps(
                {
                    "response": {
                        "status": "OK",
                        "result": {
                            "items": [
                                {"address": {"road": "서울특별시 중구 세종대로 110"}, "point": {"x": "126.9779", "y": "37.5663"}},
                                {"address": {"road": "좌표 없음"}, "point": {}},
                            ]
                        },
                    }
                }
            ).encode()

        results = VWorldSearch("KEY", opener=opener).search("세종대로 110")
        self.assertEqual(seen, ["place", "address"])
        self.assertEqual([(r.name, r.source) for r in results], [("서울특별시 중구 세종대로 110", "vworld")])
        self.assertAlmostEqual(results[0].lat, 37.5663)

    def test_search_error(self) -> None:
        def opener(request, timeout):
            return json.dumps({"response": {"status": "ERROR", "error": {"text": "인증키 오류"}}}).encode()

        with self.assertRaises(RuntimeError):
            VWorldSearch("BAD", opener=opener).search("시청")


class JusoTest(unittest.TestCase):
    def test_address_to_coordinates(self) -> None:
        x, y = KOREAN_CRS[5179].forward(37.5663, 126.9779)

        def opener(url, timeout):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            common = {"errorCode": "0", "errorMessage": "정상"}
            if "addrLinkApi" in url:
                self.assertEqual(query["confmKey"], ["S"])
                juso = [
                    {
                        "roadAddr": "서울특별시 중구 세종대로 110 (태평로1가)",
                        "bdNm": "서울특별시청",
                        "admCd": "1114010300",
                        "rnMgtSn": "111403101001",
                        "udrtYn": "0",
                        "buldMnnm": "110",
                        "buldSlno": "0",
                    }
                ]
            else:
                self.assertEqual((query["confmKey"], query["buldMnnm"]), (["C"], ["110"]))
                juso = [{"entX": str(x), "entY": str(y)}]
            return json.dumps({"results": {"common": common, "juso": juso}}).encode()

        (result,) = JusoSearch("S", "C", opener=opener).search("세종대로 110")
        self.assertEqual((result.name, result.source), ("서울특별시청", "juso"))
        self.assertAlmostEqual(result.lat, 37.5663, places=6)
        self.assertAlmostEqual(result.lon, 126.9779, places=6)

    def test_error_code(self) -> None:
        def opener(url, timeout):
            return json.dumps({"results": {"common": {"errorCode": "E0001", "errorMessage": "승인되지 않은 KEY"}}}).encode()

        with self.assertRaises(RuntimeError):
            JusoSearch("BAD", "BAD", opener=opener).search("세종대로")


if __name__ == "__main__":
    unittest.main()
