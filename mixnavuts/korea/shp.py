"""Shapefile helpers shared by the 표준노드링크 and 정밀도로지도 loaders (optional `pyshp`)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any


def field(record: Mapping[str, Any], *names: str) -> str:
    """First non-empty field among `names`, matching field names case-insensitively."""
    for name in names:
        value = record.get(name)
        if value is None:
            value = next((v for k, v in record.items() if k.upper() == name.upper()), None)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def number(record: Mapping[str, Any], *names: str) -> float:
    try:
        return float(field(record, *names) or 0)
    except ValueError:
        return 0.0


def open_shapefile(path: str | Path, encoding: str = "cp949"):
    try:
        import shapefile  # pyshp
    except ImportError as exc:
        raise RuntimeError('reading shapefiles needs pyshp: pip install "mixnavuts[korea]"') from exc
    return shapefile.Reader(str(path), encoding=encoding, encodingErrors="replace")


def find_layer(directory: str | Path, token: str) -> Path | None:
    """The .shp in `directory` (searched recursively) whose name contains `token`."""
    token = token.upper()
    matches = sorted(p for p in Path(directory).rglob("*.shp") if token in p.name.upper())
    return matches[0] if matches else None


def records(path: Path, encoding: str = "cp949") -> Iterator[tuple[dict[str, Any], list[tuple[float, float]]]]:
    """(attributes, planar points) for every feature; Z values are dropped."""
    reader = open_shapefile(path, encoding)
    for item in reader.iterShapeRecords():
        yield item.record.as_dict(), [(p[0], p[1]) for p in item.shape.points]


def describe(paths: list[Path], encoding: str = "cp949") -> str:
    """Field names and a sample record of each shapefile, to check a download's layout."""
    lines = []
    for path in paths:
        reader = open_shapefile(path, encoding)
        fields = [f[0] for f in reader.fields[1:]]
        sample = reader.record(0).as_dict() if len(reader) else {}
        first = reader.shape(0).points[:1] if len(reader) else []
        prj = path.with_suffix(".prj")
        lines += [
            f"{path.name}: {len(reader)} records, shape type {reader.shapeTypeName}",
            f"  fields: {', '.join(fields)}",
            f"  sample: {sample}",
            f"  first point: {first}",
            f"  prj: {prj.read_text(errors='replace')[:160] if prj.exists() else '(none)'}",
        ]
    return "\n".join(lines)
