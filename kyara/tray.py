"""タスクトレイ常駐(pystray)。"""
from __future__ import annotations

import logging

log = logging.getLogger("kyara")


def _icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 8, 60, 48), 6, fill=(30, 100, 200, 255))
    d.polygon([(26, 18), (26, 38), (44, 28)], fill=(255, 255, 255, 255))
    d.rectangle((28, 50, 36, 58), fill=(30, 100, 200, 255))
    return img


def start_tray(on_open, on_quit):
    """トレイを別スレッドで開始する。使えない環境では None を返す。"""
    try:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("設定を開く", lambda *_: on_open(), default=True),
            pystray.MenuItem("終了", lambda *_: on_quit()))
        icon = pystray.Icon("kyara", _icon_image(), "kyara スライドショー", menu)
        icon.run_detached()
        return icon
    except Exception:
        log.exception("トレイアイコンを作成できませんでした")
        return None
