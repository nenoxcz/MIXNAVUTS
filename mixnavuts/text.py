"""Terminal formatting that keeps Korean text aligned."""

from __future__ import annotations

import unicodedata


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, cols: int, align: str = "<") -> str:
    fill = " " * max(0, cols - width(text))
    return text + fill if align == "<" else fill + text


def clock(t: float) -> str:
    minutes = round(t / 60) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def duration(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 60}분 {total % 60:02d}초"
