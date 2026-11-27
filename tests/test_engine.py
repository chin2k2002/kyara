import logging
from datetime import datetime, timedelta

from kyara.engine import (ERROR, RUNNING, USER_STOPPED, Controller,
                          PlaybackError)
from kyara.schedule import Default, Entry, Schedule

MON = datetime(2026, 11, 23)


class FakePlayer:
    def __init__(self, bad=()):
        self.bad = set(bad)
        self.played = []
        self.stops = 0
        self.state = RUNNING
        self.wrapped = False

    def play(self, pb):
        if pb.file in self.bad:
            raise PlaybackError("x")
        self.played.append(pb.file)
        self.state = RUNNING

    def stop(self):
        self.stops += 1

    def poll(self):
        return self.state

    def loop_wrapped(self):
        w, self.wrapped = self.wrapped, False
        return w


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def setup(bad=()):
    s = Schedule(Default("def.pptx", 30),
                 [Entry((0,), 9 * 60, 10 * 60, "a.pptx", 10)])
    p = FakePlayer(bad)
    c = Clock(MON + timedelta(hours=8, minutes=59))
    return Controller(s, p, c), p, c


def test_switches_by_time_without_restart():
    ctl, p, c = setup()
    ctl.tick(0); ctl.tick(1)
    assert p.played == ["def.pptx"]
    c.t = MON + timedelta(hours=9); ctl.tick(2)
    assert p.played == ["def.pptx", "a.pptx"]
    c.t = MON + timedelta(hours=9, minutes=30); ctl.tick(3)
    assert p.played == ["def.pptx", "a.pptx"]
    c.t = MON + timedelta(hours=10); ctl.tick(4)
    assert p.played[-1] == "def.pptx"


def test_user_stop_suppresses_until_next_switch():
    ctl, p, c = setup()
    ctl.tick(0)
    p.state = USER_STOPPED
    ctl.tick(1)
    p.state = RUNNING
    c.t = MON + timedelta(hours=8, minutes=59, seconds=30); ctl.tick(2)
    assert p.played == ["def.pptx"]  # 9:00 まで再開しない
    c.t = MON + timedelta(hours=9); ctl.tick(3)
    assert p.played == ["def.pptx", "a.pptx"]


def test_missing_file_falls_back_without_flicker(caplog):
    ctl, p, c = setup(bad={"a.pptx"})
    c.t = MON + timedelta(hours=9, minutes=1)
    with caplog.at_level(logging.INFO, logger="kyara"):
        for i in range(5):
            ctl.tick(i)
    assert p.played == ["def.pptx"]  # 毎 tick で再起動しない
    assert any("退避" in r.message for r in caplog.records)


def test_fallback_returns_to_entry_after_file_fixed(tmp_path):
    f = tmp_path / "a.pptx"
    s = Schedule(Default("def.pptx", 30),
                 [Entry((0,), 9 * 60, 10 * 60, str(f), 10)])
    p = FakePlayer(bad={str(f)})
    c = Clock(MON + timedelta(hours=9, minutes=1))
    ctl = Controller(s, p, c)
    ctl.tick(0)
    assert p.played == ["def.pptx"]
    f.write_text("x")  # ファイルが用意された
    p.bad.clear()
    ctl.tick(1)
    assert p.played == ["def.pptx", str(f)]


def test_error_restarts():
    ctl, p, c = setup()
    ctl.tick(0)
    p.state = ERROR
    ctl.tick(1)
    p.state = RUNNING
    ctl.tick(2)
    assert p.played == ["def.pptx", "def.pptx"]


def test_reload_on_file_update_at_loop_boundary(tmp_path):
    f = tmp_path / "x.pptx"
    f.write_text("1")
    s = Schedule(Default(str(f), 5))
    p = FakePlayer()
    ctl = Controller(s, p, Clock(MON))
    ctl.tick(0)
    f.write_text("22")
    import os
    os.utime(f, (1, 1))
    ctl.tick(1)
    assert len(p.played) == 1  # ループ途中では読み直さない
    p.wrapped = True
    ctl.tick(2)
    assert len(p.played) == 2


def test_no_default_stops_in_gap():
    s = Schedule(None, [Entry((0,), 9 * 60, 10 * 60, "a.pptx")])
    p = FakePlayer()
    c = Clock(MON + timedelta(hours=9))
    ctl = Controller(s, p, c)
    ctl.tick(0)
    c.t = MON + timedelta(hours=10); ctl.tick(1)
    assert p.stops == 1


def test_status_shows_error_when_entry_file_fails():
    ctl, p, c = setup(bad={"a.pptx"})
    c.t = MON + timedelta(hours=9, minutes=1)
    ctl.tick(0)
    assert "a.pptx" in ctl.status() and "再生できません" in ctl.status()
    assert "既定" in ctl.status()
    c.t = MON + timedelta(hours=10, minutes=1)
    ctl.tick(1)  # 枠が終わり既定に戻る → エラー表示は消える
    assert "⚠" not in ctl.status()
