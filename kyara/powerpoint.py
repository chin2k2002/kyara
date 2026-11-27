"""PowerPoint(COM)を使ったプレーヤー。Windows + PowerPoint 専用。

- PowerPoint ファイル専用(動画ファイルは videoplayer.py が再生する)。
- PPT: 全スライドに「枠の表示秒数で自動送り」を設定してループ再生する。
  動画のあるスライドは max(表示秒数, 動画の長さ) にする。
- 音声は常時ミュート。クリックまたは Esc でスライドショーを終了する(再開は上位が制御)。
- 元ファイルは読み取り専用で開き、保存はしない。
"""
from __future__ import annotations

import logging
import os
import time

from .engine import ERROR, RUNNING, USER_STOPPED, PlaybackError
from .schedule import Playback

log = logging.getLogger("kyara")

# PowerPoint 定数
PP_SHOW_TYPE_SPEAKER = 1
PP_ADVANCE_USE_TIMINGS = 2
MSO_MEDIA = 16
PP_MEDIA_MOVIE = 3
MSO_ANIM_EFFECT_MEDIA_PLAY = 83
MSO_ANIM_TRIGGER_WITH_PREVIOUS = 2
VK_LBUTTON = 0x01
CLICK_GRACE_SECONDS = 1.5  # 開始直後のクリックは無視


class PowerPointPlayer:
    def __init__(self) -> None:
        self._app = None
        self._pres = None
        self._window = None
        self._started = 0.0
        self._last_pos = 0
        self._click_down = False
        self._stopping = False

    # --- COM ---
    def _get_app(self):
        if self._app is not None:
            try:
                _ = self._app.Version
                return self._app
            except Exception:
                self._app = None
        import pythoncom
        pythoncom.CoInitialize()  # 再生スレッドで COM を使うため
        import win32com.client
        self._app = win32com.client.Dispatch("PowerPoint.Application")
        return self._app

    # --- Player API ---
    def play(self, pb: Playback) -> None:
        self.stop()
        if not os.path.isfile(pb.file):
            raise PlaybackError("ファイルが存在しません")
        try:
            app = self._get_app()
            self._pres = self._open_pptx(app, pb)
            s = self._pres.SlideShowSettings
            s.ShowType = PP_SHOW_TYPE_SPEAKER
            s.AdvanceMode = PP_ADVANCE_USE_TIMINGS
            s.LoopUntilStopped = True
            self._window = s.Run()
        except PlaybackError:
            self._close()
            raise
        except Exception as e:
            self._close()
            if getattr(e, "args", None) and e.args[0] == -2147221005:
                raise PlaybackError(
                    "この PC には PowerPoint がありません。PowerPoint を PDF に書き出して指定してください"
                ) from e
            raise PlaybackError(f"開けません: {e}") from e
        self._started = time.monotonic()
        self._last_pos = 1
        self._click_down = self._lbutton()
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True
        try:
            if self._window is not None:
                self._window.View.Exit()
        except Exception:
            pass
        self._close()

    def poll(self) -> str:
        if self._pres is None:
            return USER_STOPPED
        try:
            if self._app.SlideShowWindows.Count == 0:
                return USER_STOPPED  # Esc などでショーが終わった
        except Exception:
            return ERROR
        down = self._lbutton()
        clicked = down and not self._click_down
        self._click_down = down
        if clicked and time.monotonic() - self._started > CLICK_GRACE_SECONDS:
            self.stop()
            return USER_STOPPED
        return RUNNING

    def loop_wrapped(self) -> bool:
        try:
            pos = self._window.View.CurrentShowPosition
        except Exception:
            return False
        wrapped = pos < self._last_pos
        self._last_pos = pos
        return wrapped

    # --- 内部 ---
    @staticmethod
    def _lbutton() -> bool:
        try:
            import win32api
            return bool(win32api.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        except Exception:
            return False

    def _close(self) -> None:
        pres, self._pres, self._window = self._pres, None, None
        if pres is not None:
            try:
                pres.Saved = True  # 保存確認を出さない
                pres.Close()
            except Exception:
                pass

    def _open_pptx(self, app, pb: Playback):
        # ReadOnly=True, Untitled=False, WithWindow=True
        pres = app.Presentations.Open(os.path.abspath(pb.file), True, False, True)
        for slide in pres.Slides:
            length = self._prepare_media(slide)
            tr = slide.SlideShowTransition
            tr.AdvanceOnClick = False
            tr.AdvanceOnTime = True
            tr.AdvanceTime = max(pb.slide_seconds, int(length) + 1)
        return pres

    def _prepare_media(self, slide) -> float:
        """動画をミュート・自動再生にし、最長の動画の長さ(秒)を返す。"""
        longest = 0.0
        for shape in slide.Shapes:
            try:
                if shape.Type != MSO_MEDIA or shape.MediaType != PP_MEDIA_MOVIE:
                    continue
                shape.MediaFormat.Muted = True
                longest = max(longest, shape.MediaFormat.Length / 1000.0)
                seq = slide.TimeLine.MainSequence
                has_effect = any(seq.Item(i).Shape.Name == shape.Name
                                 for i in range(1, seq.Count + 1))
                if not has_effect:  # クリック再生のままだと止まるので自動再生にする
                    seq.AddEffect(shape, MSO_ANIM_EFFECT_MEDIA_PLAY,
                                  0, MSO_ANIM_TRIGGER_WITH_PREVIOUS)
            except Exception:
                log.exception("動画の設定に失敗しました(スライド %s)", slide.SlideIndex)
        return longest
