import pytest

from kyara.player import RoutingPlayer
from kyara.schedule import Playback
from datetime import datetime


class Fake:
    def __init__(self):
        self.calls = []

    def play(self, pb):
        self.calls.append(("play", pb.file))

    def stop(self):
        self.calls.append(("stop",))

    def poll(self):
        return "running"

    def loop_wrapped(self):
        return False


def pb(f):
    return Playback(f, 60, False, None, datetime(2026, 1, 1))


def test_routes_by_extension_and_stops_previous():
    ppt, vid = Fake(), Fake()
    r = RoutingPlayer(ppt, vid)
    r.play(pb("a.pptx"))
    r.play(pb("b.MOV"))
    r.play(pb("c.pptx"))
    assert ppt.calls == [("play", "a.pptx"), ("stop",), ("play", "c.pptx")]
    assert vid.calls == [("play", "b.MOV"), ("stop",)]
    r.stop()
    assert ppt.calls[-1] == ("stop",)


def test_letterbox_keeps_aspect():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from kyara.videoplayer import letterbox
    out = letterbox(np.full((100, 200, 3), 255, np.uint8), 400, 400)
    assert out.shape == (400, 400, 3)
    assert out[0, 0].sum() == 0 and out[200, 200].sum() == 765  # 上下は黒帯
