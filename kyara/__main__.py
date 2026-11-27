"""起動: kyara.exe [--minimized] [--headless] [設定JSON]"""
import argparse
import ctypes
import os
import sys
import threading

from . import autostart
from .engine import Controller, setup_logging
from .player import RoutingPlayer
from .schedule import Schedule


def selftest() -> int:
    """exe に OpenCV / PyMuPDF が正しく同梱されたかを確認する(CI 用)。"""
    import tempfile
    import traceback
    log_path = os.path.join(tempfile.gettempdir(), "kyara_selftest.log")
    try:
        import numpy as np
        import pymupdf
        import cv2
        from .pdfplayer import render_page
        from .videoplayer import letterbox
        doc = pymupdf.open()
        doc.new_page(width=400, height=300).insert_text((50, 100), "selftest")
        img = render_page(doc, 0, 800, 600)
        assert img.shape == (600, 800, 3), img.shape
        out = letterbox(np.zeros((100, 200, 3), np.uint8), 400, 400)
        assert out.shape == (400, 400, 3)
        cv2.imencode(".png", out)
        open(log_path, "w").write("OK")
        return 0
    except Exception:
        open(log_path, "w").write(traceback.format_exc())
        return 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?")
    ap.add_argument("--minimized", action="store_true", help="トレイに入れて起動")
    ap.add_argument("--selftest", action="store_true", help="同梱ライブラリの動作確認")
    ap.add_argument("--headless", action="store_true", help="GUI なしで実行")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())

    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "kyara")
    cfg = a.config or os.path.join(base, "schedule.json")
    setup_logging(os.path.join(base, "kyara.log"))
    if not autostart.acquire_single_instance():
        return  # 既に起動中
    schedule = Schedule.load(cfg)
    ctl = Controller(schedule, RoutingPlayer())
    stop = threading.Event()
    worker = threading.Thread(target=ctl.run, args=(stop,), daemon=True)
    worker.start()

    if a.headless:
        try:
            worker.join()
        except KeyboardInterrupt:
            stop.set()
            worker.join(5)
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    import tkinter as tk

    from .gui import App
    from .tray import start_tray

    root = tk.Tk()
    tray = None

    def quit_app() -> None:
        stop.set()
        worker.join(5)  # 再生を止めてから閉じる
        if tray is not None:
            tray.stop()
        root.destroy()

    app = App(root, schedule, cfg, ctl, quit_app)
    tray = start_tray(lambda: root.after(0, app.show),
                      lambda: root.after(0, quit_app))
    app.has_tray = tray is not None
    if a.minimized and app.has_tray:
        root.withdraw()
    elif not schedule.default and not schedule.entries:
        pass  # 初回は設定画面を表示
    root.mainloop()


if __name__ == "__main__":
    main()
