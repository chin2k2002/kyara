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

CHAR_DUR = 0.27      # 1文字あたりの平均表示時間（秒）
JITTER = 0.05        # 打鍵間隔のゆらぎ（秒）
LEAD_IN = 0.3        # 最初の無音・黒画面
GAP = 0.05           # 1文字表示の後、タイトル全体までの間
TITLE_HOLD = 3.6     # タイトル全体の表示時間
TAIL = 0.5           # 最後の黒画面

OUT = sys.argv[1] if len(sys.argv) > 1 else "lupin_style_title.mp4"
# 2番目の引数に参考動画/音声を渡すと、その音を切り出して使う（省略時は合成音）
REF = sys.argv[2] if len(sys.argv) > 2 else None
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


def bandpass(x, lo_a, hi_a):
    return lowpass(x, hi_a) - lowpass(x, lo_a)


def clack(strength=1.0):
    """タイプライターの打鍵音（高く硬い「カ・タッ」の2段打ち）"""
    n = int(SR * 0.2)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for delay, amp, decay in [(0.0, 1.0, 55), (rng.uniform(0.07, 0.09), 0.55, 70)]:
        i = int(delay * SR)
        m = n - i
        tt = t[:m]
        noise = rng.standard_normal(m)
        hit = bandpass(noise, 0.35, 0.75) * np.exp(-tt * decay)          # 3〜5kHz帯のカチッ
        hit += np.sin(2 * np.pi * rng.uniform(3800, 4300) * tt) * np.exp(-tt * 40) * 0.25
        hit += np.sin(2 * np.pi * rng.uniform(140, 180) * tt) * np.exp(-tt * 50) * 0.35
        s[i:] += hit * amp
    s[: int(SR * 0.001)] *= np.linspace(0, 1, int(SR * 0.001))
    return s / np.max(np.abs(s)) * 0.75 * strength


def big_hit():
    """タイトル全体が出たときの低い持続音（約290Hz、ゆっくり減衰）"""
    n = int(SR * 3.6)
    t = np.arange(n) / SR
    f0 = 290.0
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
    ph = 2 * np.pi * f0 * np.cumsum(vib) / SR
    s = np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.3 * np.sin(3 * ph) + 0.12 * np.sin(5 * ph)
    s += np.sin(ph / 2) * 0.4
    env = np.minimum(t / 0.03, 1) * np.where(t < 2.4, 1 - 0.25 * t / 2.4, 0.75 * np.exp(-(t - 2.4) * 3))
    s *= env
    # 頭に打鍵音を重ねる
    c = clack(1.0)
    s[: len(c)] += c * 1.5
    return s / np.max(np.abs(s)) * 0.8


def load_ref_sounds(path):
    """参考音源から打鍵音（複数）と、最後の打鍵＋持続音を切り出す"""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, "<i2").astype(float) / 32768
    h = SR // 100
    e = np.array([np.sqrt(np.mean(x[i:i + h] ** 2)) for i in range(0, len(x) - h, h)])
    onsets = []
    for i in range(1, len(e)):
        if e[i] > 0.05 and e[i - 1] < 0.06 and (not onsets or i - onsets[-1] > 15):
            onsets.append(i)
    # 打鍵の後に音が1秒以上途切れず続く最初の打鍵＝締め（打鍵＋持続音）。そこから最後までを使う
    def sustained(i):
        return np.all(e[i:i + 100] > 0.03)
    last = next(i for i in onsets if sustained(i))
    onsets = [i for i in onsets if i <= last]
    tail_start = max(0, last * h - int(SR * 0.005))
    finale = x[tail_start:]
    hits = []
    for a, b in zip(onsets[:-1], onsets[1:]):
        seg = x[max(0, a * h - int(SR * 0.005)): min(b * h, a * h + int(SR * 0.26))].copy()
        fade = int(SR * 0.03)
        seg[-fade:] *= np.linspace(1, 0, fade)
        hits.append(seg)
    # 弱い・短い断片（打鍵の途中で切れたもの）は除く
    hits = [hh for hh in hits if len(hh) >= SR * 0.2 and np.abs(hh).max() >= 0.8 * max(np.abs(g).max() for g in hits)]
    print(f"ref: {len(hits)} hits, finale {len(finale) / SR:.2f}s")
    return hits, finale


def main():
    starts = [LEAD_IN]
    for _ in TOKENS[1:]:
        starts.append(starts[-1] + CHAR_DUR + rng.uniform(-JITTER, JITTER))
    chars_end = starts[-1] + CHAR_DUR
    total = chars_end + GAP + TITLE_HOLD + TAIL
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

    t_title = chars_end + GAP
    if REF:
        hits, finale = load_ref_sounds(REF)
        for k, st in enumerate(starts):
            mix(hits[k % len(hits)], st)
        mix(finale, t_title)
    else:
        for st in starts:
            mix(clack(rng.uniform(0.85, 1.0)), st)
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
        elif t < chars_end:
            frame = char_imgs[max(k for k, st in enumerate(starts) if st <= t)]
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
