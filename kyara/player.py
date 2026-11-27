"""ファイルの種類で再生方法を切り替えるプレーヤー。

動画(.mov/.mp4 等)は PowerPoint なしの OpenCV プレーヤー、
PowerPoint ファイルは PowerPoint で再生する。
"""
from __future__ import annotations

from .schedule import Playback, is_video


class RoutingPlayer:
    def __init__(self, ppt=None, video=None) -> None:
        self._ppt = ppt
        self._video = video
        self._active = None

    def _pick(self, pb: Playback):
        if is_video(pb.file):
            if self._video is None:
                from .videoplayer import VideoPlayer
                self._video = VideoPlayer()
            return self._video
        if self._ppt is None:
            from .powerpoint import PowerPointPlayer
            self._ppt = PowerPointPlayer()
        return self._ppt

    def play(self, pb: Playback) -> None:
        target = self._pick(pb)
        if self._active is not None and self._active is not target:
            self._active.stop()
            self._active = None
        target.play(pb)
        self._active = target

    def stop(self) -> None:
        if self._active is not None:
            self._active.stop()
            self._active = None

    def poll(self) -> str:
        return self._active.poll() if self._active else "user_stopped"

    def loop_wrapped(self) -> bool:
        return self._active.loop_wrapped() if self._active else False
