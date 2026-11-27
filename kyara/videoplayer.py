"""OpenCV の全画面ウィンドウと、動画ファイル(.mov/.mp4 等)用プレーヤー。PowerPoint 不要。

全画面・無音。クリックまたは Esc で終了。動画は尺(実時間)を守ってループ再生する。
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


class Run:
    """1 回の再生の状態(再生スレッドと poll() で共有)。"""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.state = RUNNING
        self.wrapped = threading.Event()
        self.clicked = False
        self.thread: threading.Thread | None = None


class Window:
    """全画面ウィンドウ。作ったスレッドでのみ使うこと(OpenCV の制約)。"""

    def __init__(self, run: Run) -> None:
        import cv2
        self.cv2, self.run = cv2, run
        self.started = time.monotonic()
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
        self.sw, self.sh = screen_size()

    def show(self, frame) -> None:
        self.cv2.imshow(WIN, letterbox(frame, self.sw, self.sh))

    def wait(self, ms: int) -> bool:
        """ms 待つ。利用者が終了操作をしたら True(state も更新)。"""
        key = self.cv2.waitKey(max(1, ms))
        grace_over = time.monotonic() - self.started > CLICK_GRACE_SECONDS
        if key == 27 or (self.run.clicked and grace_over):
            self.run.state = USER_STOPPED
            return True
        self.run.clicked = self.run.clicked and not grace_over
        return False

    def close(self) -> None:
        try:
            self.cv2.destroyWindow(WIN)
            self.cv2.waitKey(1)
        except Exception:
            pass


class _CvPlayerBase:
    """スレッド管理と Player API の共通部分。"""

    def __init__(self) -> None:
        self._run: Run | None = None

    def _start(self, target, *args) -> None:
        run = Run()
        run.thread = threading.Thread(target=self._guarded, args=(target, run, *args),
                                      daemon=True, name="kyara-cv")
        self._run = run
        run.thread.start()

    @staticmethod
    def _guarded(target, run: Run, *args) -> None:
        win = None
        try:
            win = Window(run)
            target(run, win, *args)
        except Exception:
            log.exception("再生中にエラー")
            run.state = ERROR
        finally:
            if win is not None:
                win.close()

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


class VideoPlayer(_CvPlayerBase):
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
        fps = cap.get(cv2.CAP_PROP_FPS)
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        log.info("動画: %s  尺=%s 秒 (%.2f fps, %d コマ)", pb.file,
                 f"{n / fps:.1f}" if fps > 0 and n > 0 else "不明", fps, n)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._start(self._loop, cap)

    @staticmethod
    def _loop(run: Run, win: Window, cap) -> None:
        import cv2
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            interval = 1.0 / fps if 1 <= fps <= 120 else 1 / 30
            pass_start = time.monotonic()  # 今回のループの開始時刻
            consumed = 0  # このループで読んだコマ数
            last_ts = 0.0
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
                    log.info("動画 1 周: 実測 %.1f 秒", time.monotonic() - pass_start)
                    pass_start, consumed, last_ts = time.monotonic(), 0, 0.0
                    continue
                failures = 0
                consumed += 1
                win.show(frame)
                # 動画の時間(尺)を守る: 遅れたらコマを飛ばして実時間に追いつく
                ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                due = pass_start + (ts if ts > 0 and ts >= last_ts
                                    else consumed * interval)
                last_ts = max(last_ts, ts)
                now = time.monotonic()
                if now - due > interval:
                    behind = min(int((now - due) / interval), 60)
                    for _ in range(behind):
                        if not cap.grab():
                            break
                        consumed += 1
                    ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                    due = pass_start + (ts if ts > 0 else consumed * interval)
                    last_ts = max(last_ts, ts)
                    now = time.monotonic()
                if win.wait(int((due - now) * 1000)):
                    break
        finally:
            cap.release()
