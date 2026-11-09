#!/usr/bin/env python3
"""
RGB モーションキャプチャ（深度センサー・マーカー不要）。

普通の Web カメラ、または撮影済みの動画（RGB）から MediaPipe Pose で
全身の姿勢を推定し、次のファイルを出力します。

  <output>.mp4            モーション参照動画（30fps に正規化。MimicMotion の参照動画として使用）
  <output>_pose.json      フレームごとの 33 点ランドマーク（画像座標 + 3D ワールド座標）
  <output>_skeleton.mp4   骨格だけを描いた確認用動画（--skeleton_video 指定時）

使い方:
  # Web カメラで収録（SPACE で開始/停止、Q/ESC で終了）
  py -3.11 rgb_mocap.py --camera 0 --output my_motion.mp4

  # 10 秒間だけ自動収録（3 秒カウントダウン後に開始）
  py -3.11 rgb_mocap.py --camera 0 --duration 10 --output my_motion.mp4

  # 撮影済み動画からモーションを抽出
  py -3.11 rgb_mocap.py --input 自撮り動画.mp4 --output my_motion.mp4 --skeleton_video

収録したモーションでアバター動画を作る:
  py -3.11 generate_avatar_video.py --text "セリフ" --photo 写真.jpg \\
      --voice_sample 録音.m4a --motion_video my_motion.mp4
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
MODELS_DIR = BASE / "models"
TARGET_FPS = 30.0

MODEL_URLS = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}

LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner",
    "right_eye", "right_eye_outer", "left_ear", "right_ear", "mouth_left",
    "mouth_right", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky", "left_index",
    "right_index", "left_thumb", "right_thumb", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle", "left_heel",
    "right_heel", "left_foot_index", "right_foot_index",
]

POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
]


# ---------------------------------------------------------------------------
# 姿勢推定
# ---------------------------------------------------------------------------

def ensure_model(complexity: str) -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / f"pose_landmarker_{complexity}.task"
    if not path.exists():
        print(f"姿勢推定モデルをダウンロード中: {path.name}")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URLS[complexity], tmp)
        tmp.replace(path)
    return path


class PoseEstimator:
    """MediaPipe Pose のラッパー。Tasks API を優先し、無ければ旧 solutions API を使う。"""

    def __init__(self, complexity: str = "full", min_confidence: float = 0.5):
        import mediapipe as mp

        self._mp = mp
        self._last_ts = -1
        try:
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python import vision

            options = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model(complexity))),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=min_confidence,
                min_pose_presence_confidence=min_confidence,
                min_tracking_confidence=min_confidence,
            )
            self._landmarker = vision.PoseLandmarker.create_from_options(options)
            self._legacy = None
        except (ImportError, AttributeError):
            self._landmarker = None
            self._legacy = mp.solutions.pose.Pose(
                model_complexity={"lite": 0, "full": 1, "heavy": 2}[complexity],
                min_detection_confidence=min_confidence,
                min_tracking_confidence=min_confidence,
            )

    def detect(self, rgb, timestamp_ms: int):
        """RGB 画像 (H, W, 3, uint8) から姿勢を推定する。

        戻り値: (landmarks, world_landmarks) — それぞれ [[x, y, z, visibility], ...] (33 点)。
        人物が検出できなければ (None, None)。
        """
        if self._landmarker is not None:
            ts = max(int(timestamp_ms), self._last_ts + 1)  # VIDEO モードは単調増加が必須
            self._last_ts = ts
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect_for_video(image, ts)
            if not result.pose_landmarks:
                return None, None
            lms = result.pose_landmarks[0]
            wlms = result.pose_world_landmarks[0] if result.pose_world_landmarks else []
        else:
            result = self._legacy.process(rgb)
            if result.pose_landmarks is None:
                return None, None
            lms = result.pose_landmarks.landmark
            wlms = result.pose_world_landmarks.landmark if result.pose_world_landmarks else []

        def pack(points):
            return [[p.x, p.y, p.z, float(getattr(p, "visibility", 1.0) or 0.0)] for p in points]

        return pack(lms), (pack(wlms) if wlms else None)

    def close(self):
        if self._landmarker is not None:
            self._landmarker.close()
        if self._legacy is not None:
            self._legacy.close()


# ---------------------------------------------------------------------------
# 平滑化（One Euro Filter）: 推定のブレを抑えつつ素早い動きには追従する
# ---------------------------------------------------------------------------

class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.05, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self._x = None
        self._dx = None
        self._t = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: list[float], t: float) -> list[float]:
        if self._x is None or t <= self._t:
            self._x, self._dx, self._t = list(x), [0.0] * len(x), t
            return list(x)
        dt = t - self._t
        self._t = t
        a_d = self._alpha(self.d_cutoff, dt)
        dx = [(xi - pi) / dt for xi, pi in zip(x, self._x)]
        self._dx = [a_d * d + (1 - a_d) * pd for d, pd in zip(dx, self._dx)]
        out = []
        for xi, pi, di in zip(x, self._x, self._dx):
            a = self._alpha(self.min_cutoff + self.beta * abs(di), dt)
            out.append(a * xi + (1 - a) * pi)
        self._x = out
        return out


class LandmarkSmoother:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._filters: dict[str, OneEuroFilter] = {}

    def __call__(self, key: str, landmarks, t: float):
        if not self.enabled or landmarks is None:
            return landmarks
        flat = [c for p in landmarks for c in p[:3]]
        f = self._filters.setdefault(key, OneEuroFilter())
        sm = f(flat, t)
        return [[sm[i * 3], sm[i * 3 + 1], sm[i * 3 + 2], p[3]] for i, p in enumerate(landmarks)]


# ---------------------------------------------------------------------------
# 描画・書き出し
# ---------------------------------------------------------------------------

def draw_skeleton(img, landmarks, min_visibility: float = 0.3):
    import cv2

    if landmarks is None:
        return img
    h, w = img.shape[:2]
    pts = [(int(p[0] * w), int(p[1] * h), p[3]) for p in landmarks]
    thick = max(2, int(min(h, w) / 240))
    for a, b in POSE_CONNECTIONS:
        if pts[a][2] >= min_visibility and pts[b][2] >= min_visibility:
            cv2.line(img, pts[a][:2], pts[b][:2], (0, 255, 128), thick, cv2.LINE_AA)
    for x, y, v in pts:
        if v >= min_visibility:
            cv2.circle(img, (x, y), thick + 1, (0, 128, 255), -1, cv2.LINE_AA)
    return img


def open_writer(path: Path, fps: float, size: tuple[int, int]):
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError(f"動画ファイルを開けません: {path}")
    return writer


class MocapRecorder:
    """フレームを TARGET_FPS に揃えて書き出し、ランドマークも記録する。"""

    def __init__(self, output: Path, size: tuple[int, int], fps: float, skeleton_video: bool):
        self.output = output
        self.size = size
        self.fps = fps
        self.video = open_writer(output, fps, size)
        self.skeleton = (
            open_writer(output.with_name(output.stem + "_skeleton.mp4"), fps, size) if skeleton_video else None
        )
        self.frames: list[dict] = []

    def write(self, bgr, landmarks, world_landmarks):
        import numpy as np

        idx = len(self.frames)
        self.video.write(bgr)
        if self.skeleton is not None:
            canvas = np.zeros_like(bgr)
            self.skeleton.write(draw_skeleton(canvas, landmarks))
        self.frames.append({
            "frame": idx,
            "time": round(idx / self.fps, 4),
            "detected": landmarks is not None,
            "landmarks": landmarks,
            "world_landmarks": world_landmarks,
        })

    def close(self) -> dict:
        self.video.release()
        if self.skeleton is not None:
            self.skeleton.release()
        detected = sum(1 for f in self.frames if f["detected"])
        summary = {
            "fps": self.fps,
            "width": self.size[0],
            "height": self.size[1],
            "num_frames": len(self.frames),
            "duration": round(len(self.frames) / self.fps, 3),
            "detection_rate": round(detected / len(self.frames), 3) if self.frames else 0.0,
        }
        json_path = self.output.with_name(self.output.stem + "_pose.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                **summary,
                "format": "mediapipe_pose_33",
                "landmark_names": LANDMARK_NAMES,
                "connections": POSE_CONNECTIONS,
                "note": "landmarks: 画像に対する正規化座標 [x, y, z, visibility] / "
                        "world_landmarks: 腰中心のメートル単位 3D 座標 [x, y, z, visibility]",
                "frames": self.frames,
            }, f, ensure_ascii=False)
        summary["pose_json"] = str(json_path)
        return summary


def report(summary: dict) -> None:
    print(f"\nモーション動画: {summary['output']}")
    print(f"ランドマーク:   {summary['pose_json']}")
    print(f"長さ: {summary['duration']:.1f} 秒 / {summary['num_frames']} フレーム ({summary['fps']:.0f}fps)")
    rate = summary["detection_rate"]
    print(f"人物検出率: {rate * 100:.0f}%")
    if rate < 0.8:
        print("警告: 人物を検出できないフレームが多いです。全身が画面に収まるよう、"
              "明るい場所でカメラから離れて撮影してください。")


def fit_size(w: int, h: int, max_height: int) -> tuple[int, int]:
    if max_height and h > max_height:
        w, h = int(round(w * max_height / h)), max_height
    return w - w % 2, h - h % 2  # コーデック都合で偶数に


# ---------------------------------------------------------------------------
# 動画ファイルから抽出
# ---------------------------------------------------------------------------

def process_video(input_path: str | Path, output: str | Path, *, complexity: str = "full",
                  smooth: bool = True, skeleton_video: bool = False, max_duration: float | None = None,
                  max_height: int = 1024, fps: float = TARGET_FPS, quiet: bool = False) -> dict:
    """撮影済み RGB 動画からモーションを抽出し、fps を揃えたモーション動画を書き出す。"""
    import cv2

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"動画を開けません: {input_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    if not (0 < src_fps < 1000):
        src_fps = fps
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w0, h0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    size = fit_size(w0, h0, max_height)

    output = Path(output)
    estimator = PoseEstimator(complexity)
    smoother = LandmarkSmoother(smooth)
    rec = MocapRecorder(output, size, fps, skeleton_video)

    src_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t_src = src_idx / src_fps
            src_idx += 1
            if max_duration is not None and t_src >= max_duration:
                break
            # 出力 fps に合わせてフレームを間引き/複製（時刻ベースのリサンプリング）
            n_out = int(math.floor((t_src + 1.0 / src_fps) * fps + 1e-6)) - len(rec.frames)
            if max_duration is not None:
                n_out = min(n_out, int(round(max_duration * fps)) - len(rec.frames))
            if n_out <= 0:
                continue
            if (frame.shape[1], frame.shape[0]) != size:
                frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            lms, wlms = estimator.detect(rgb, int(t_src * 1000))
            lms = smoother("img", lms, t_src)
            wlms = smoother("world", wlms, t_src)
            for _ in range(n_out):
                rec.write(frame, lms, wlms)
            if not quiet and total and src_idx % 30 == 0:
                print(f"\r  解析中... {src_idx}/{total} フレーム", end="", flush=True)
    finally:
        cap.release()
        estimator.close()
        summary = rec.close()
    if not quiet:
        print()
    summary["output"] = str(output)
    if summary["num_frames"] == 0:
        raise RuntimeError(f"動画からフレームを読み込めませんでした: {input_path}")
    return summary


# ---------------------------------------------------------------------------
# Web カメラから収録
# ---------------------------------------------------------------------------

def capture_webcam(output: str | Path, *, camera: int = 0, duration: float | None = None,
                   countdown: int = 3, complexity: str = "full", smooth: bool = True,
                   skeleton_video: bool = False, width: int = 1280, height: int = 720,
                   mirror: bool = True, fps: float = TARGET_FPS, on_start=None) -> dict:
    """Web カメラからリアルタイムで姿勢推定しながらモーションを収録する。

    duration を指定するとカウントダウン後に自動で収録を開始し、その秒数で終了する。
    指定しない場合は SPACE で開始/停止。on_start は収録開始時に呼ばれる（音声再生などに使用）。
    """
    import cv2

    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise RuntimeError(f"カメラ {camera} を開けません")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        raise RuntimeError(f"カメラ {camera} から映像を取得できません")
    size = fit_size(frame.shape[1], frame.shape[0], 0)

    output = Path(output)
    estimator = PoseEstimator(complexity)
    smoother = LandmarkSmoother(smooth)
    rec: MocapRecorder | None = None
    win = "RGB Mocap  [SPACE: 収録開始/停止  Q/ESC: 終了]"
    t0 = time.monotonic()
    countdown_until = t0 + countdown if duration is not None else None
    rec_start = None

    print("カメラを起動しました。全身が映る位置に立ってください。")
    if duration is None:
        print("SPACE で収録開始/停止、Q または ESC で終了します。")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("カメラからの映像が途切れました")
                break
            now = time.monotonic()
            if mirror:
                frame = cv2.flip(frame, 1)
            if (frame.shape[1], frame.shape[0]) != size:
                frame = cv2.resize(frame, size)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            lms, wlms = estimator.detect(rgb, int((now - t0) * 1000))
            lms = smoother("img", lms, now - t0)
            wlms = smoother("world", wlms, now - t0)

            # カウントダウン完了で自動開始
            if countdown_until is not None and rec is None and now >= countdown_until:
                rec, rec_start = MocapRecorder(output, size, fps, skeleton_video), now
                countdown_until = None
                if on_start:
                    on_start()

            if rec is not None:
                elapsed = now - rec_start
                if duration is not None and elapsed >= duration:
                    while len(rec.frames) < int(round(duration * fps)):  # 末尾の不足分を補完
                        rec.write(frame, lms, wlms)
                    break
                # 実際の経過時間に合わせて書き込み、カメラの fps 揺れを吸収
                target = int(elapsed * fps) + 1
                if duration is not None:
                    target = min(target, int(round(duration * fps)))
                while len(rec.frames) < target:
                    rec.write(frame, lms, wlms)

            # プレビュー
            view = draw_skeleton(frame.copy(), lms)
            if rec is not None:
                msg = f"REC {now - rec_start:5.1f}s" + (f" / {duration:.1f}s" if duration else "")
                cv2.circle(view, (24, 28), 9, (0, 0, 255), -1)
                cv2.putText(view, msg, (42, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
            elif countdown_until is not None:
                n = math.ceil(countdown_until - now)
                cv2.putText(view, str(n), (size[0] // 2 - 30, size[1] // 2 + 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 8, cv2.LINE_AA)
            else:
                cv2.putText(view, "SPACE: start", (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                            (255, 255, 255), 2, cv2.LINE_AA)
            if lms is None:
                cv2.putText(view, "no person", (20, size[1] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 200, 255), 2, cv2.LINE_AA)
            cv2.imshow(win, view)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" ") and duration is None:
                if rec is None:
                    rec, rec_start = MocapRecorder(output, size, fps, skeleton_video), now
                    print("収録開始")
                    if on_start:
                        on_start()
                else:
                    print("収録停止")
                    break
    finally:
        cap.release()
        estimator.close()
        cv2.destroyAllWindows()
        summary = rec.close() if rec is not None else None

    if summary is None or summary["num_frames"] == 0:
        raise RuntimeError("収録されたフレームがありません")
    summary["output"] = str(output)
    return summary


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RGB カメラ/動画からモーションキャプチャ")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--camera", type=int, default=None, help="Web カメラ番号 (既定: 0)")
    src.add_argument("--input", help="撮影済みの動画ファイル（RGB）")
    parser.add_argument("--output", default="my_motion.mp4", help="出力モーション動画")
    parser.add_argument("--duration", type=float, default=None,
                        help="収録秒数。カメラ: カウントダウン後に自動収録 / 動画: 先頭から切り出し")
    parser.add_argument("--countdown", type=int, default=3, help="自動収録前のカウントダウン秒数")
    parser.add_argument("--model", choices=list(MODEL_URLS), default="full",
                        help="姿勢推定モデル (lite=高速, heavy=高精度)")
    parser.add_argument("--no_smooth", action="store_true", help="ランドマークの平滑化を無効化")
    parser.add_argument("--no_mirror", action="store_true", help="カメラ映像を左右反転しない")
    parser.add_argument("--skeleton_video", action="store_true", help="骨格だけの確認用動画も出力")
    parser.add_argument("--width", type=int, default=1280, help="カメラの解像度 (幅)")
    parser.add_argument("--height", type=int, default=720, help="カメラの解像度 (高さ)")
    args = parser.parse_args()

    try:
        if args.input:
            if not Path(args.input).exists():
                print(f"エラー: 動画が見つかりません: {args.input}")
                sys.exit(1)
            summary = process_video(args.input, args.output, complexity=args.model,
                                    smooth=not args.no_smooth, skeleton_video=args.skeleton_video,
                                    max_duration=args.duration)
        else:
            summary = capture_webcam(args.output, camera=args.camera or 0, duration=args.duration,
                                     countdown=args.countdown, complexity=args.model,
                                     smooth=not args.no_smooth, skeleton_video=args.skeleton_video,
                                     width=args.width, height=args.height, mirror=not args.no_mirror)
    except RuntimeError as e:
        print(f"エラー: {e}")
        sys.exit(1)
    report(summary)


if __name__ == "__main__":
    main()
