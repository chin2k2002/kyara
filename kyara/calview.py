"""週表示カレンダーの計算(tkinter 非依存)。"""
from __future__ import annotations

import re

from .schedule import DAY, Entry, Schedule

DAY_NAMES = "月火水木金土日"
SNAP = 15


def day_segments(schedule: Schedule, day: int) -> list[tuple[int, int, Entry]]:
    """指定曜日(0=月)の列に表示する (開始分, 終了分, 枠)。日またぎは分割される。"""
    lo, hi = day * DAY, (day + 1) * DAY
    out = []
    for e in schedule.entries:
        for s, t in e.intervals():
            a, b = max(s, lo), min(t, hi)
            if a < b:
                out.append((a - lo, b - lo, e))
    return sorted(out, key=lambda x: x[0])


def free_segments(busy: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, cur = [], 0
    for s, e in sorted(busy):
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < DAY:
        out.append((cur, DAY))
    return out


def is_free(busy: list[tuple[int, int]], minute: int) -> bool:
    return not any(s <= minute < e for s, e in busy)


def clamp_range(busy: list[tuple[int, int]], anchor: int, cur: int
                ) -> tuple[int, int]:
    """ドラッグ範囲を、既存の枠にぶつからないよう空き時間内に収める。"""
    if cur >= anchor:
        hi = min([s for s, _ in busy if s >= anchor] + [DAY, cur])
        return anchor, max(hi, anchor)
    lo = max([e for _, e in busy if e <= anchor] + [0, cur])
    return min(lo, anchor), anchor


def snap(minute: float, mode: str = "round") -> int:
    q = minute / SNAP
    q = int(q) if mode == "floor" else round(q)
    return max(0, min(DAY, q * SNAP))


def fmt_hm(minute: int) -> str:
    minute %= DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"


def parse_hm(text: str) -> int:
    m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})\s*", text)
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        raise ValueError("時刻は HH:MM の形式で入力してください")
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi:
        raise ValueError("時刻は 24:00 までです")
    return h * 60 + mi


def parse_seconds(text: str) -> int:
    m = re.fullmatch(r"\s*(?:(\d+)[:：](\d{1,2})|(\d+))\s*", text)
    if not m:
        raise ValueError("表示時間は秒(例 60)または 分:秒(例 1:30)で入力してください")
    if m.group(3) is not None:
        return int(m.group(3))
    return int(m.group(1)) * 60 + int(m.group(2))


def fmt_seconds(sec: int) -> str:
    return f"{sec}秒" if sec < 60 or sec % 60 else f"{sec // 60}分"
