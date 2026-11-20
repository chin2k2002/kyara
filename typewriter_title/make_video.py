#!/usr/bin/env python3
"""黒背景に1文字ずつタイプ音付きで表示し、最後にタイトル全体を出す動画を生成する。

使い方:
    python3 make_video.py [出力ファイル.mp4]
"""
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------- 設定 ----------------
# 1文字ずつ表示するトークン（「BIC」はまとめて1つ）
TOKENS = ["BIC", "で", "実", "際", "に", "起", "こ", "っ", "た",
          "イ", "ン", "シ", "デ", "ン", "ト",
          "メ", "ー", "ル", "誤", "送", "信", "編", "③"]
# 最後に表示するタイトル（行ごと）
TITLE_LINES = ["BICで実際に起こった", "インシデント", "（メール誤送信編③）"]

W, H, FPS = 1920, 1080, 30
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc"
SR = 44100

CHAR_DUR = 0.17      # 1文字あたりの表示時間（秒）
LEAD_IN = 0.5        # 最初の無音・黒画面
GAP = 0.45           # 1文字表示の後、タイトル全体までの間
TITLE_HOLD = 3.5     # タイトル全体の表示時間
TAIL = 0.5           # 最後の黒画面

OUT = sys.argv[1] if len(sys.argv) > 1 else "lupin_style_title.mp4"
# --------------------------------------


def font(size):
    return ImageFont.truetype(FONT_PATH, size, index=0)


def draw_center(img, text, size):
    d = ImageDraw.Draw(img)
    f = font(size)
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text(((W - (r - l)) / 2 - l, (H - (b - t)) / 2 - t), text, font=f, fill="white")


def char_frame(tok):
    img = Image.new("RGB", (W, H), "black")
    draw_center(img, tok, 520 if len(tok) == 1 else 400)
    return img


def title_frame():
    img = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(img)
    f = font(150)
    sizes = [d.textbbox((0, 0), s, font=f) for s in TITLE_LINES]
    # 一番長い行が画面幅の88%に収まるよう縮小
    maxw = max(b[2] - b[0] for b in sizes)
    size = int(150 * min(1.0, W * 0.88 / maxw))
    f = font(size)
    line_h = int(size * 1.35)
    y0 = (H - line_h * len(TITLE_LINES)) / 2
    for i, s in enumerate(TITLE_LINES):
        l, t, r, b = d.textbbox((0, 0), s, font=f)
        d.text(((W - (r - l)) / 2 - l, y0 + i * line_h + (line_h - size) / 2 - t * 0.2),
               s, font=f, fill="white")
    return img


# ---------------- 効果音 ----------------
rng = np.random.default_rng(3)


def lowpass(x, a):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += a * (v - acc)
        y[i] = acc
    return y


def clack(strength=1.0):
    """タイプライターの打鍵音（金属的なクリック＋低いドスッ）"""
    n = int(SR * 0.12)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    hi = noise - lowpass(noise, 0.25)                      # 高域のカチッ
    click = hi * np.exp(-t * 90)
    body = lowpass(noise, 0.08) * np.exp(-t * 45) * 2.5    # 中低域のコツッ
    f0 = rng.uniform(170, 210)
    thump = np.sin(2 * np.pi * f0 * t) * np.exp(-t * 60) * 0.9
    ring = np.sin(2 * np.pi * rng.uniform(2600, 3200) * t) * np.exp(-t * 70) * 0.15
    s = click + body + thump + ring
    s[: int(SR * 0.0015)] *= np.linspace(0, 1, int(SR * 0.0015))
    return s / np.max(np.abs(s)) * 0.8 * strength


def big_hit():
    """タイトル全体が出る瞬間の重い打撃音＋残響"""
    n = int(SR * 2.0)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    s = lowpass(noise, 0.05) * np.exp(-t * 6) * 3
    s += (noise - lowpass(noise, 0.3)) * np.exp(-t * 30) * 0.6
    s += np.sin(2 * np.pi * 70 * t) * np.exp(-t * 4) * 1.2
    s += np.sin(2 * np.pi * 110 * t) * np.exp(-t * 7) * 0.6
    s[: int(SR * 0.002)] *= np.linspace(0, 1, int(SR * 0.002))
    return s / np.max(np.abs(s)) * 0.95


def main():
    total = LEAD_IN + len(TOKENS) * CHAR_DUR + GAP + TITLE_HOLD + TAIL
    nframes = int(round(total * FPS))
    audio = np.zeros(int(SR * (total + 2.5)))

    def mix(sig, at):
        i = int(at * SR)
        audio[i:i + len(sig)] += sig[: len(audio) - i]

    # タイムライン（フレーム -> 画像）
    black = Image.new("RGB", (W, H), "black").tobytes()
    char_imgs = [char_frame(tk).tobytes() for tk in TOKENS]
    title_img = title_frame().tobytes()
    title_frame_img = Image.frombytes("RGB", (W, H), title_img)
    title_frame_img.save(OUT.rsplit(".", 1)[0] + "_title.png")

    t_title = LEAD_IN + len(TOKENS) * CHAR_DUR + GAP
    for k in range(len(TOKENS)):
        mix(clack(rng.uniform(0.85, 1.0)), LEAD_IN + k * CHAR_DUR)
    mix(big_hit(), t_title)
    audio = audio[: int(SR * total)]
    audio = np.clip(audio, -1, 1)

    wav_path = OUT.rsplit(".", 1)[0] + "_audio.wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype("<i2").tobytes())

    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", wav_path,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT],
        stdin=subprocess.PIPE)
    for fi in range(nframes):
        t = fi / FPS
        if t < LEAD_IN:
            frame = black
        elif t < LEAD_IN + len(TOKENS) * CHAR_DUR:
            frame = char_imgs[int((t - LEAD_IN) / CHAR_DUR)]
        elif t < t_title:
            frame = black
        elif t < t_title + TITLE_HOLD:
            frame = title_img
        else:
            frame = black
        ff.stdin.write(frame)
    ff.stdin.close()
    ff.wait()
    print(f"wrote {OUT} ({total:.1f}s)")


if __name__ == "__main__":
    main()
