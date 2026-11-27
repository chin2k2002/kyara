"""起動: kyara.exe [--minimized] [--headless] [設定JSON]"""
import argparse
import ctypes
import os
import sys
import threading

from . import autostart
from .engine import Controller, setup_logging
from .powerpoint import PowerPointPlayer
from .schedule import Schedule


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?")
    ap.add_argument("--minimized", action="store_true", help="トレイに入れて起動")
    ap.add_argument("--headless", action="store_true", help="GUI なしで実行")
    a = ap.parse_args()

    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "kyara")
    cfg = a.config or os.path.join(base, "schedule.json")
    setup_logging(os.path.join(base, "kyara.log"))
    if not autostart.acquire_single_instance():
        return  # 既に起動中
    schedule = Schedule.load(cfg)
    ctl = Controller(schedule, PowerPointPlayer())
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
