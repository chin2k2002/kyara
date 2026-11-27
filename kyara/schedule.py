"""スケジュール判定ロジック(GUI/PowerPoint 非依存)。

時刻は「0:00 からの分」、週は月曜 0:00 起点の分(0〜10079)で扱う。
日またぎの枠(end <= start)は翌日の end まで続くものとして扱う。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

DAY = 1440
WEEK = DAY * 7
MIN_SLIDE_SECONDS = 1
MAX_SLIDE_SECONDS = 3600
DEFAULT_SLIDE_SECONDS = 60
VIDEO_EXTENSIONS = {".mp4", ".mov", ".wmv", ".avi", ".mkv", ".m4v"}


class ScheduleError(ValueError):
    pass


class OverlapError(ScheduleError):
    pass


def is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_pdf(path: str) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def _check_slide_seconds(sec: int) -> None:
    if not MIN_SLIDE_SECONDS <= sec <= MAX_SLIDE_SECONDS:
        raise ScheduleError(
            f"表示秒数は {MIN_SLIDE_SECONDS}〜{MAX_SLIDE_SECONDS} 秒で指定してください")


@dataclass(frozen=True)
class Entry:
    days: tuple[int, ...]  # 0=月 … 6=日
    start: int  # 分
    end: int  # 分。end <= start なら翌日にまたぐ
    file: str
    slide_seconds: int = DEFAULT_SLIDE_SECONDS
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not self.days or any(d not in range(7) for d in self.days):
            raise ScheduleError("曜日を 1 つ以上選択してください")
        object.__setattr__(self, "days", tuple(sorted(set(self.days))))
        if not (0 <= self.start < DAY and 0 <= self.end < DAY + 1):
            raise ScheduleError("時刻が範囲外です")
        if self.end == DAY:  # 24:00 は 0:00 として扱う
            object.__setattr__(self, "end", 0)
        if self.start == self.end:
            raise ScheduleError("開始と終了が同じ時刻です")
        if not self.file:
            raise ScheduleError("ファイルを指定してください")
        _check_slide_seconds(self.slide_seconds)

    @property
    def overnight(self) -> bool:
        return self.end <= self.start

    def intervals(self) -> list[tuple[int, int]]:
        """週内の [start, end) 区間(週末でまたぐ場合は 2 つに分割)。"""
        out: list[tuple[int, int]] = []
        length = (self.end - self.start) % DAY
        for d in self.days:
            s = d * DAY + self.start
            e = s + length
            if e <= WEEK:
                out.append((s, e))
            else:
                out.append((s, WEEK))
                out.append((0, e - WEEK))
        return out


@dataclass(frozen=True)
class Default:
    file: str
    slide_seconds: int = DEFAULT_SLIDE_SECONDS

    def __post_init__(self) -> None:
        if not self.file:
            raise ScheduleError("既定ファイルを指定してください")
        _check_slide_seconds(self.slide_seconds)


@dataclass(frozen=True)
class Playback:
    file: str
    slide_seconds: int
    is_default: bool
    entry_id: str | None
    until: datetime  # この時刻に再判定する


def _overlaps(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(s1 < e2 and s2 < e1 for s1, e1 in a for s2, e2 in b)


class Schedule:
    def __init__(self, default: Default | None = None,
                 entries: list[Entry] | None = None,
                 folder: str = "") -> None:
        self.default = default
        self.folder = folder  # GUI のファイル選択に使う素材フォルダ
        self.entries: list[Entry] = []
        for e in entries or []:
            self.add(e)

    # --- 編集 ---
    def can_place(self, entry: Entry, ignore_id: str | None = None) -> bool:
        mine = entry.intervals()
        return not any(
            _overlaps(mine, o.intervals())
            for o in self.entries if o.id != ignore_id)

    def add(self, entry: Entry) -> None:
        if not self.can_place(entry):
            raise OverlapError("他のスケジュールと時間が重なっています")
        self.entries.append(entry)

    def update(self, entry: Entry) -> None:
        if not any(e.id == entry.id for e in self.entries):
            raise KeyError(entry.id)
        if not self.can_place(entry, ignore_id=entry.id):
            raise OverlapError("他のスケジュールと時間が重なっています")
        self.entries = [entry if e.id == entry.id else e for e in self.entries]

    def copy(self) -> "Schedule":
        return Schedule.from_dict(self.to_dict())

    def remove(self, entry_id: str) -> None:
        self.entries = [e for e in self.entries if e.id != entry_id]

    # --- 判定 ---
    def _state_at(self, w: int) -> tuple[Entry | None, int]:
        """週内分 w の時点の枠と、その状態が続く週内の終端(分)。"""
        nxt = WEEK
        for e in self.entries:
            for s, t in e.intervals():
                if s <= w < t:
                    return e, t
                if s > w:
                    nxt = min(nxt, s)
        return None, nxt

    def resolve(self, now: datetime) -> Playback | None:
        """now に再生すべき内容を返す。何も再生するものがなければ None。"""
        base = now.replace(second=0, microsecond=0)
        w = base.weekday() * DAY + base.hour * 60 + base.minute
        entry, end_w = self._state_at(w)
        total = end_w - w
        # 週境界をまたいで同じ状態が続く場合は終端を延ばす
        cur = end_w % WEEK
        for _ in range(2):
            if end_w - w < 0 or total >= WEEK:
                break
            nxt_entry, nxt_end = self._state_at(cur)
            same = (nxt_entry.id if nxt_entry else None) == (
                entry.id if entry else None)
            if not (same and end_w >= WEEK):
                break
            total += nxt_end - cur
            end_w, cur = nxt_end, nxt_end % WEEK
        until = base + timedelta(minutes=total)
        if entry:
            return Playback(entry.file, entry.slide_seconds, False,
                            entry.id, until)
        if self.default:
            return Playback(self.default.file, self.default.slide_seconds,
                            True, None, until)
        return None

    def fallback(self, now: datetime, until: datetime) -> Playback | None:
        """枠のファイルが開けない場合の退避先(既定ファイル)。"""
        if not self.default:
            return None
        return Playback(self.default.file, self.default.slide_seconds,
                        True, None, until)

    # --- 保存 ---
    def to_dict(self) -> dict:
        return {
            "folder": self.folder,
            "default": ({"file": self.default.file,
                         "slide_seconds": self.default.slide_seconds}
                        if self.default else None),
            "entries": [{"id": e.id, "days": list(e.days), "start": e.start,
                         "end": e.end, "file": e.file,
                         "slide_seconds": e.slide_seconds}
                        for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        d = data.get("default")
        default = Default(d["file"], d.get("slide_seconds",
                                           DEFAULT_SLIDE_SECONDS)) if d else None
        entries = [Entry(tuple(x["days"]), x["start"], x["end"], x["file"],
                         x.get("slide_seconds", DEFAULT_SLIDE_SECONDS),
                         x.get("id") or uuid.uuid4().hex)
                   for x in data.get("entries", [])]
        return cls(default, entries, data.get("folder", ""))

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(p)

    @classmethod
    def load(cls, path: str | Path) -> "Schedule":
        p = Path(path)
        if not p.exists():
            return cls()
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
