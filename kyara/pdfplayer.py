"""PDF プレーヤー。PowerPoint を PDF に書き出したファイルを、1 ページずつ全画面で流す。

PowerPoint も LibreOffice も不要。ページごとに枠の「1 スライドの表示時間」だけ表示し、
最後のページの次は先頭に戻って繰り返す。
"""
from __future__ import annotations

import logging
import time

from .engine import PlaybackError
from .schedule import Playback
from .videoplayer import Run, Window, _CvPlayerBase

log = logging.getLogger("kyara")


def render_page(doc, index: int, sw: int, sh: int):
    """ページを画面に収まる大きさで描画し、BGR の ndarray を返す。"""
    import numpy as np
    import pymupdf
    page = doc[index]
    zoom = min(sw / page.rect.width, sh / page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return np.ascontiguousarray(img[:, :, ::-1])  # RGB → BGR


class PdfPlayer(_CvPlayerBase):
    def play(self, pb: Playback) -> None:
        self.stop()
        import pymupdf
        try:
            doc = pymupdf.open(pb.file)
        except Exception as e:
            raise PlaybackError(f"PDF を開けません: {e}") from e
        if doc.needs_pass:
            doc.close()
            raise PlaybackError("パスワード付きの PDF は再生できません")
        if doc.page_count == 0:
            doc.close()
            raise PlaybackError("PDF にページがありません")
        log.info("PDF: %s  %d ページ × %d 秒", pb.file, doc.page_count, pb.slide_seconds)
        self._start(self._loop, doc, pb.slide_seconds)

    @staticmethod
    def _loop(run: Run, win: Window, doc, seconds: int) -> None:
        try:
            while not run.stop.is_set():
                started = time.monotonic()
                for i in range(doc.page_count):
                    win.show(render_page(doc, i, win.sw, win.sh))
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        if run.stop.is_set() or win.wait(100):
                            return
                run.wrapped.set()
                log.info("PDF 1 周: 実測 %.1f 秒", time.monotonic() - started)
        finally:
            doc.close()
