"""MapLibre style for the engine's own map: 브이월드 base map (optional) + the road network as vector tiles.

No glyphs are served yet, so there are no text labels of our own; the 브이월드
base map carries place and road names. Serve Noto Sans KR glyph PBFs and add
symbol layers to label roads from the vector tiles.
"""

from __future__ import annotations

from typing import Any

ROAD_STYLE = [  # class, colour, width at z10, width at z16
    ("local", "#ffffff", 0.5, 6.0),
    ("secondary", "#fff4c2", 1.0, 9.0),
    ("primary", "#ffd27f", 1.5, 11.0),
    ("ramp", "#f7a65a", 1.0, 7.0),
    ("trunk", "#f7a65a", 2.0, 12.0),
    ("motorway", "#e8833a", 2.5, 14.0),
]
ALERT_COLOURS = {
    "speed_camera": "#d7263d",
    "signal_camera": "#d7263d",
    "section_camera": "#8f1d2c",
    "traffic_light": "#2a9d4b",
    "speed_bump": "#f4a261",
}


def build_style(base_url: str, *, basemap: bool, attribution: str) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    sources: dict[str, Any] = {
        "mixnavuts": {
            "type": "vector",
            "tiles": [f"{base_url}/v1/tiles/{{z}}/{{x}}/{{y}}.mvt"],
            "minzoom": 5,
            "maxzoom": 14,
            "attribution": attribution,
        }
    }
    layers: list[dict[str, Any]] = [{"id": "background", "type": "background", "paint": {"background-color": "#f2efe9"}}]
    if basemap:
        sources["basemap"] = {
            "type": "raster",
            "tiles": [f"{base_url}/v1/basemap/{{z}}/{{x}}/{{y}}.png"],
            "tileSize": 256,
            "minzoom": 6,
            "maxzoom": 19,
            "attribution": "© 국토교통부 브이월드",
        }
        layers.append({"id": "basemap", "type": "raster", "source": "basemap"})

    def width(at10: float, at16: float, extra: float = 0.0) -> list[Any]:
        return ["interpolate", ["exponential", 1.5], ["zoom"], 10, at10 + extra, 16, at16 + extra]

    if not basemap:  # with 브이월드 underneath, its own roads and labels are the map
        for road_class, colour, at10, at16 in ROAD_STYLE:
            flt = ["==", ["get", "class"], road_class]
            line = {
                "source": "mixnavuts",
                "source-layer": "roads",
                "filter": flt,
                "layout": {"line-cap": "round", "line-join": "round"},
            }
            layers.append(
                {
                    "id": f"road-{road_class}-casing",
                    "type": "line",
                    **line,
                    "paint": {"line-color": "#b9b1a5", "line-width": width(at10, at16, 1.5)},
                }
            )
            layers.append(
                {
                    "id": f"road-{road_class}",
                    "type": "line",
                    **line,
                    "paint": {"line-color": colour, "line-width": width(at10, at16)},
                }
            )
    colour = ["match", ["get", "type"], *[v for pair in ALERT_COLOURS.items() for v in pair], "#555555"]
    layers.append(
        {
            "id": "alerts",
            "type": "circle",
            "source": "mixnavuts",
            "source-layer": "alerts",
            "minzoom": 13,
            "paint": {
                "circle-color": colour,
                "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 2.5, 17, 6],
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 1,
            },
        }
    )
    return {"version": 8, "name": "MIXNAVUTS", "sources": sources, "layers": layers}
