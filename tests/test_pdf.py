import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("numpy")
pytest.importorskip("cv2")

from datetime import datetime

from kyara.pdfplayer import render_page
from kyara.player import RoutingPlayer
from kyara.schedule import Playback, is_pdf


def test_render_page_fits_screen():
    doc = pymupdf.open()
    doc.new_page(width=960, height=540)
    img = render_page(doc, 0, 800, 600)
    assert img.shape[2] == 3 and img.shape[1] <= 800 and img.shape[0] <= 600
    assert img.shape[1] == 800  # 横幅いっぱいに収まる


def test_pdf_routing():
    class F:
        def __init__(self): self.c = []
        def play(self, pb): self.c.append(pb.file)
        def stop(self): pass
        def poll(self): return "running"
        def loop_wrapped(self): return False
    ppt, vid = F(), F()
    r = RoutingPlayer(ppt, vid)
    r._pdf = pdf = F()
    r.play(Playback("a.PDF", 60, False, None, datetime(2026, 1, 1)))
    assert pdf.c == ["a.PDF"] and not ppt.c and not vid.c
    assert is_pdf("x.pdf") and not is_pdf("x.pptx")
