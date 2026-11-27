"""動画ファイル(.mov/.mp4 等)用プレーヤー。PowerPoint 不要。

OpenCV で全画面・無音・ループ再生する。クリックまたは Esc で終了。
"""
from __future__ import annotations

import logging
import sys
import threading
import time

from .engine import ERROR, RUNNING, USER_STOPPED, PlaybackError
from .schedule import Playback

log = logging.getLogger("kyara")

WIN = "kyara-video"
CLICK_GRACE_SECONDS = 1.5


def screen_size() -> tuple[int, int]:
    if sys.platform == "win32":
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    return 1920, 1080


def letterbox(frame, sw: int, sh: int):
    """アスペクト比を保って画面に収め、余白は黒で埋める。"""
    import cv2
    h, w = frame.shape[:2]
    scale = min(sw / w, sh / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = cv2.resize(frame, (nw, nh),
                     interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    top, left = (sh - nh) // 2, (sw - nw) // 2
    return cv2.copyMakeBorder(img, top, sh - nh - top, left, sw - nw - left,
                              cv2.BORDER_CONSTANT, value=(0, 0, 0))


class _Run:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.state = RUNNING
        self.wrapped = threading.Event()
        self.clicked = False
        self.thread: threading.Thread | None = None


class VideoPlayer:
    def __init__(self) -> None:
        self._run: _Run | None = None

    def play(self, pb: Playback) -> None:
        self.stop()
        import cv2
        cap = cv2.VideoCapture(pb.file)
        ok = cap.isOpened()
        if ok:
            ok, _ = cap.read()
        if not ok:
            cap.release()
            raise PlaybackError("動画を開けません(ファイルが壊れている、または未対応の形式)")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        run = _Run()
        run.thread = threading.Thread(target=self._loop, args=(cap, run),
                                      daemon=True, name="kyara-video")
        self._run = run
        run.thread.start()

    def stop(self) -> None:
        run, self._run = self._run, None
        if run is not None:
            run.stop.set()
            if run.thread is not None:
                run.thread.join(5)

    def poll(self) -> str:
        return self._run.state if self._run else USER_STOPPED

    def loop_wrapped(self) -> bool:
        run = self._run
        if run is None or not run.wrapped.is_set():
            return False
        run.wrapped.clear()
        return True

    # --- 再生スレッド(OpenCV の GUI は作ったスレッドでしか触れない) ---
    def _loop(self, cap, run: _Run) -> None:
        import cv2
        started = time.monotonic()
        try:
            cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            try:
                cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
            except Exception:
                pass

            def on_mouse(event, *_):
                if event == cv2.EVENT_LBUTTONDOWN:
                    run.clicked = True
            cv2.setMouseCallback(WIN, on_mouse)

            sw, sh = screen_size()
            fps = cap.get(cv2.CAP_PROP_FPS)
            interval = 1.0 / fps if 1 <= fps <= 120 else 1 / 30
            next_t = time.monotonic()
            failures = 0
            while not run.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    if failures > 1:  # 巻き戻しても読めない
                        run.state = ERROR
                        break
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    run.wrapped.set()
                    continue
                failures = 0
                cv2.imshow(WIN, letterbox(frame, sw, sh))
                next_t += interval
                now = time.monotonic()
                if next_t < now - 1:
                    next_t = now  # 遅れすぎたら追いつくのをやめる
                key = cv2.waitKey(max(1, int((next_t - now) * 1000)))
                grace_over = time.monotonic() - started > CLICK_GRACE_SECONDS
                if key == 27 or (run.clicked and grace_over):
                    run.state = USER_STOPPED
                    break
                run.clicked = run.clicked and not grace_over
        except Exception:
            log.exception("動画の再生中にエラー")
            run.state = ERROR
        finally:
            cap.release()
            try:
                cv2.destroyWindow(WIN)
                cv2.waitKey(1)
            except Exception:
                pass
