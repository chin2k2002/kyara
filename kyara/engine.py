"""再生制御(スケジュールに従ってプレーヤーを起動・停止する)。

プレーヤーの実体(PowerPoint)に依存しないので、ここは Linux でもテストできる。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable, Protocol

from .schedule import Playback, Schedule

log = logging.getLogger("kyara")

RUNNING = "running"
USER_STOPPED = "user_stopped"  # クリック/Esc などで利用者が終了した
ERROR = "error"  # PowerPoint の異常終了など

RETRY_SECONDS = 30


class PlaybackError(Exception):
    """ファイル不在・パスワード付きなど、再生を開始できなかった。"""


class Player(Protocol):
    def play(self, pb: Playback) -> None: ...
    def stop(self) -> None: ...
    def poll(self) -> str: ...
    def loop_wrapped(self) -> bool: ...


def _mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


class Controller:
    def __init__(self, schedule: Schedule, player: Player,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.schedule = schedule
        self.player = player
        self.clock = clock
        self._current: Playback | None = None
        self._current_mtime: float | None = None
        self._pending_reload = False
        self._suppressed_until: datetime | None = None
        self._failed: dict[tuple, tuple[float, float | None]] = {}
        self._wanted: tuple | None = None
        self._lock = threading.Lock()

    def set_schedule(self, schedule: Schedule) -> None:
        """GUI から設定が変更されたときに呼ぶ。次の tick で反映される。"""
        with self._lock:
            self.schedule = schedule

    def status(self) -> str:
        # GUI から頻繁に呼ばれるので、再生開始処理中のロックは待たない
        sup, cur = self._suppressed_until, self._current
        if sup:
            return f"停止中(クリックで終了): {sup:%m/%d %H:%M} に再開"
        if cur is None:
            return "再生なし(既定ファイルが未設定、または待機中)"
        kind = "既定" if cur.is_default else "スケジュール"
        return (f"再生中[{kind}]: {os.path.basename(cur.file)}"
                f"  ({cur.slide_seconds}秒/枚)")

    def resume(self) -> None:
        """クリックで終了した状態から、すぐに再開する。"""
        self._suppressed_until = None

    @staticmethod
    def _key(pb: Playback) -> tuple:
        return (pb.file, pb.slide_seconds, pb.entry_id)

    def _stop(self) -> None:
        if self._current is not None:
            self.player.stop()
            self._current = None

    def _start(self, pb: Playback, mono: float) -> bool:
        key = self._key(pb)
        try:
            self.player.play(pb)
        except PlaybackError as e:
            log.error("再生できません: %s (%s)", pb.file, e)
            self._failed[key] = (mono + RETRY_SECONDS, _mtime(pb.file))
            return False
        self._failed.pop(key, None)
        self._current = pb
        self._current_mtime = _mtime(pb.file)
        self._pending_reload = False
        log.info("再生開始: %s (%s秒/枚, %s, %s まで)", pb.file,
                 pb.slide_seconds, "既定" if pb.is_default else "スケジュール",
                 pb.until.strftime("%m/%d %H:%M"))
        return True

    def _can_retry(self, pb: Playback, mono: float) -> bool:
        failed = self._failed.get(self._key(pb))
        if failed is None:
            return True
        retry_at, mtime = failed
        # 時間が経った、またはファイルが差し替えられたら再試行する
        return mono >= retry_at or _mtime(pb.file) != mtime

    def tick(self, mono: float | None = None) -> None:
        with self._lock:
            self._tick(time.monotonic() if mono is None else mono)

    def _tick(self, mono: float) -> None:
        now = self.clock()
        if self._suppressed_until and now >= self._suppressed_until:
            self._suppressed_until = None
        if self._suppressed_until:
            self._stop()
            return

        pb = self.schedule.resolve(now)
        if pb is None:
            self._wanted = None
            self._stop()
            return

        cur = self._current
        if self._wanted == self._key(pb) and cur is not None:
            state = self.player.poll()
            if state == USER_STOPPED:
                log.info("利用者が終了しました。%s まで再開しません",
                         pb.until.strftime("%m/%d %H:%M"))
                self._current = None
                self._suppressed_until = pb.until
                return
            if state == ERROR:
                log.error("PowerPoint が異常終了しました。再起動します")
                self._current = None
                return
            if cur.file != pb.file:
                # 退避中: 枠のファイルが直った/差し替わったら戻す
                if self._can_retry(pb, mono) and os.path.isfile(pb.file):
                    self._stop()
                    if not self._start(pb, mono):
                        fb = self.schedule.fallback(now, pb.until)
                        if fb is not None:
                            self._start(fb, mono)
                return
            # ファイル更新は次のループ先頭で読み直す
            if _mtime(pb.file) != self._current_mtime:
                self._pending_reload = True
            if self._pending_reload and self.player.loop_wrapped():
                log.info("ファイルが更新されたため読み直します: %s", pb.file)
                self._stop()
                self._start(pb, mono)
            return

        # 枠が切り替わった(または未再生・異常終了後)
        self._wanted = self._key(pb)
        self._stop()
        if self._can_retry(pb, mono) and self._start(pb, mono):
            return
        fb = self.schedule.fallback(now, pb.until)
        if fb is not None and self._key(fb) != self._key(pb):
            if self._current is None or self._current.file != fb.file:
                log.warning("既定ファイルに退避します: %s", fb.file)
                self._start(fb, mono)

    def run(self, stop_event: threading.Event, interval: float = 0.5) -> None:
        log.info("スケジューラー開始")
        try:
            while not stop_event.wait(interval):
                try:
                    self.tick()
                except Exception:
                    log.exception("予期しないエラー")
        finally:
            with self._lock:
                self._stop()
            log.info("スケジューラー終了")


def setup_logging(path: str) -> None:
    from logging.handlers import RotatingFileHandler
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
