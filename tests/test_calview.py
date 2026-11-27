import pytest

from kyara.calview import (clamp_range, day_segments, free_segments, is_free,
                           parse_hm, parse_seconds, snap)
from kyara.schedule import Default, Entry, Schedule


def test_day_segments_split_overnight():
    s = Schedule(None, [Entry((0,), 22 * 60, 6 * 60, "n.pptx")])
    assert [(a, b) for a, b, _ in day_segments(s, 0)] == [(1320, 1440)]
    assert [(a, b) for a, b, _ in day_segments(s, 1)] == [(0, 360)]
    assert day_segments(s, 2) == []


def test_free_and_clamp():
    busy = [(540, 720), (780, 1080)]
    assert free_segments(busy) == [(0, 540), (720, 780), (1080, 1440)]
    assert is_free(busy, 720) and not is_free(busy, 540)
    assert clamp_range(busy, 480, 600) == (480, 540)  # 下方向: 次の枠で止まる
    assert clamp_range(busy, 780 - 15, 700) == (720, 765)  # 上方向
    assert clamp_range(busy, 1100, 1439) == (1100, 1439)


def test_parsers():
    assert parse_hm("9:05") == 545 and parse_hm("24:00") == 1440
    for bad in ("25:00", "9", "9:60", "24:30"):
        with pytest.raises(ValueError):
            parse_hm(bad)
    assert parse_seconds("90") == 90 and parse_seconds("1:30") == 90
    with pytest.raises(ValueError):
        parse_seconds("abc")
    assert snap(547) == 540 and snap(548) == 555
    assert snap(547, "floor") == 540


def test_folder_persist_and_copy(tmp_path):
    s = Schedule(Default("d.pptx"), [], folder="C:\\slides")
    c = s.copy()
    c.folder = "x"
    assert s.folder == "C:\\slides"
    s.save(tmp_path / "a.json")
    assert Schedule.load(tmp_path / "a.json").folder == "C:\\slides"
