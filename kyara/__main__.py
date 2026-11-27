"""ヘッドレス実行: python -m kyara [設定JSON]  (Ctrl+C で終了)"""
import os
import sys
import threading

from .engine import Controller, setup_logging
from .powerpoint import PowerPointPlayer
from .schedule import Schedule


def main() -> None:
    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "kyara")
    cfg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "schedule.json")
    setup_logging(os.path.join(base, "kyara.log"))
    ctl = Controller(Schedule.load(cfg), PowerPointPlayer())
    stop = threading.Event()
    try:
        ctl.run(stop)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
