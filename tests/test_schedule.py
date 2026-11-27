from datetime import datetime, timedelta

import pytest

from kyara.schedule import (Default, Entry, OverlapError, Schedule,
                            ScheduleError, is_video)

# 2026-11-23 は月曜
MON = datetime(2026, 11, 23)


def at(day, h, m=0):
    return MON + timedelta(days=day, hours=h, minutes=m)


def hm(h, m=0):
    return h * 60 + m


def make():
    return Schedule(Default("default.pptx", 30), [
        Entry((0, 1, 2, 3, 4), hm(9), hm(12), "a.pptx", 45),
        Entry((0, 1, 2, 3, 4), hm(13), hm(18), "b.mp4"),
    ])


def test_inside_entry():
    p = make().resolve(at(0, 10, 30))
    assert (p.file, p.slide_seconds, p.is_default) == ("a.pptx", 45, False)
    assert p.until == at(0, 12)


def test_start_inclusive_end_exclusive():
    s = make()
    assert s.resolve(at(0, 9)).file == "a.pptx"
    assert s.resolve(at(0, 12)).is_default


def test_gap_uses_default_until_next_start():
    p = make().resolve(at(0, 12, 30))
    assert p.file == "default.pptx" and p.slide_seconds == 30
    assert p.until == at(0, 13)


def test_weekend_default_until_monday_entry():
    p = make().resolve(at(5, 10))  # 土曜
    assert p.is_default and p.until == at(7, 9)  # 翌月曜 9:00


def test_no_default_returns_none():
    assert Schedule().resolve(at(0, 10)) is None


def test_overlap_rejected():
    s = make()
    with pytest.raises(OverlapError):
        s.add(Entry((0,), hm(11), hm(14), "c.pptx"))
    s.add(Entry((0,), hm(12), hm(13), "c.pptx"))  # 隣接は OK


def test_overnight():
    s = Schedule(Default("d.pptx"), [Entry((0,), hm(22), hm(6), "n.pptx")])
    assert s.resolve(at(0, 23)).file == "n.pptx"
    assert s.resolve(at(1, 5)).file == "n.pptx"
    assert s.resolve(at(1, 6)).is_default
    assert s.resolve(at(0, 5)).is_default
    assert s.resolve(at(0, 23)).until == at(1, 6)


def test_overnight_overlap_with_next_day():
    s = Schedule(None, [Entry((0,), hm(22), hm(6), "n.pptx")])
    with pytest.raises(OverlapError):
        s.add(Entry((1,), hm(5), hm(7), "x.pptx"))


def test_sunday_night_wraps_to_monday():
    s = Schedule(Default("d.pptx"), [Entry((6,), hm(22), hm(6), "n.pptx")])
    assert s.resolve(at(6, 23)).until == at(7, 6)
    assert s.resolve(at(0, 3)).file == "n.pptx"
    assert s.resolve(at(0, 3)).until == at(0, 6)


def test_default_across_week_boundary_is_merged():
    p = Schedule(Default("d.pptx"), [Entry((2,), hm(9), hm(10), "a.pptx")]
                 ).resolve(at(5, 10))
    assert p.until == at(9, 9)  # 次の水曜 9:00


def test_update_ignores_self_and_remove():
    s = make()
    e = s.entries[0]
    s.update(Entry(e.days, hm(9), hm(12, 30), "a2.pptx", 10, e.id))
    assert s.resolve(at(0, 12, 10)).file == "a2.pptx"
    with pytest.raises(OverlapError):
        s.update(Entry(e.days, hm(9), hm(14), "a.pptx", 10, e.id))
    s.remove(e.id)
    assert s.resolve(at(0, 10)).is_default


def test_validation():
    with pytest.raises(ScheduleError):
        Entry((), 0, 60, "a.pptx")
    with pytest.raises(ScheduleError):
        Entry((0,), 60, 60, "a.pptx")
    with pytest.raises(ScheduleError):
        Entry((0,), 0, 60, "a.pptx", 0)
    with pytest.raises(ScheduleError):
        Entry((0,), 0, 60, "a.pptx", 3601)
    with pytest.raises(ScheduleError):
        Default("")


def test_fallback_and_video():
    s = make()
    p = s.resolve(at(0, 10))
    f = s.fallback(at(0, 10), p.until)
    assert f.is_default and f.until == p.until
    assert is_video("X.MP4") and not is_video("a.pptx")


def test_save_load_roundtrip(tmp_path):
    s = make()
    path = tmp_path / "sub" / "cfg.json"
    s.save(path)
    s2 = Schedule.load(path)
    assert s2.to_dict() == s.to_dict()
    assert Schedule.load(tmp_path / "none.json").entries == []
