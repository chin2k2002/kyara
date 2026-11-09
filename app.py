#!/usr/bin/env python3
"""
Kyara — Windows 向け GUI アプリ。

  - モーション収録: Web カメラ / 動画ファイルから RGB モーションキャプチャ（お手本動画を見ながら収録も可）
  - アバター動画:   自分の声で読み上げ + 写真のアバターを動かした動画を生成
  - セットアップ:   環境の確認、MimicMotion の導入

Kyara.cmd から起動してください（install.cmd で runtime\\ を作成済みであること）。
処理は各スクリプトを別プロセスで実行し、ログをこの画面に表示します。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BASE = Path(__file__).resolve().parent
SETTINGS = BASE / "kyara_settings.json"
IS_WIN = sys.platform == "win32"

VIDEO_TYPES = [("動画", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v"), ("すべて", "*.*")]
IMAGE_TYPES = [("画像", "*.jpg *.jpeg *.png *.webp"), ("すべて", "*.*")]
AUDIO_TYPES = [("音声", "*.wav *.m4a *.mp3 *.flac *.ogg"), ("すべて", "*.*")]

NOISE_PREFIXES = ("W0000", "I0000", "INFO: Created TensorFlow", "WARNING: All log messages",
                  "WARNING: Logging before InitGoogle")


def open_path(path: Path) -> None:
    if IS_WIN:
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Runner:
    """スクリプトを子プロセスで実行し、出力をキューに流す。"""

    def __init__(self, on_line, on_exit):
        self.proc: subprocess.Popen | None = None
        self.on_line, self.on_exit = on_line, on_exit

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, args: list[str]) -> None:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
        self.proc = subprocess.Popen(
            [sys.executable, "-u", *args], cwd=str(BASE), env=env, creationflags=flags,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen) -> None:
        buf = b""
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            # \r（進捗の上書き）と \n / \r\n の両方で区切る
            while True:
                idx = min((i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0), default=-1)
                if idx < 0:
                    break
                if buf[idx:idx + 1] == b"\r":
                    if idx + 1 >= len(buf):
                        break  # 次が \n かどうか、続きを待つ
                    if buf[idx + 1:idx + 2] == b"\n":
                        line, buf = buf[:idx], buf[idx + 2:]
                        self.on_line(line.decode("utf-8", "replace"), False)
                        continue
                    line, buf = buf[:idx], buf[idx + 1:]
                    self.on_line(line.decode("utf-8", "replace"), True)
                else:
                    line, buf = buf[:idx], buf[idx + 1:]
                    self.on_line(line.decode("utf-8", "replace"), False)
        if buf.rstrip(b"\r"):
            self.on_line(buf.rstrip(b"\r").decode("utf-8", "replace"), False)
        self.on_exit(proc.wait())

    def stop(self) -> None:
        if self.running:
            self.proc.terminate()


class PathField:
    """ラベル + 入力欄 + 参照ボタン。"""

    def __init__(self, parent, row: int, label: str, var: tk.StringVar, kind: str, types=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        self.entry = ttk.Entry(parent, textvariable=var, width=56)
        self.entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.button = ttk.Button(parent, text="参照...", command=lambda: self._browse(var, kind, types))
        self.button.grid(row=row, column=2, padx=(6, 0), pady=3)

    @staticmethod
    def _browse(var: tk.StringVar, kind: str, types) -> None:
        initial = Path(var.get()).parent if var.get() else BASE
        if kind == "save":
            path = filedialog.asksaveasfilename(initialdir=initial, defaultextension=".mp4",
                                                filetypes=[("MP4 動画", "*.mp4")],
                                                initialfile=Path(var.get()).name if var.get() else "")
        else:
            path = filedialog.askopenfilename(initialdir=initial, filetypes=types or [("すべて", "*.*")])
        if path:
            var.set(str(Path(path)))

    def set_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.button.configure(state=state)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kyara — RGB モーションキャプチャ & アバター動画")
        self.geometry("900x760")
        self.minsize(760, 620)
        import tkinter.font as tkfont
        families = set(tkfont.families(self))
        ui_font = next((f for f in ("Meiryo UI", "Yu Gothic UI", "Noto Sans CJK JP", "Noto Sans JP",
                                    "Hiragino Sans") if f in families), None)
        if ui_font:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
                try:
                    tkfont.nametofont(name).configure(family=ui_font, size=10)
                except tk.TclError:
                    pass
        self.ui_font = ui_font or "TkDefaultFont"
        self.style = ttk.Style(self)
        if "vista" in self.style.theme_names():
            self.style.theme_use("vista")
        self.style.configure("Accent.TButton", font=(self.ui_font, 11, "bold"))

        self.queue: queue.Queue = queue.Queue()
        self.runner = Runner(lambda line, cr: self.queue.put(("line", line, cr)),
                             lambda code: self.queue.put(("exit", code, None)))
        self.after_done = None  # 実行完了時に呼ぶ追加処理
        self.v: dict[str, tk.Variable] = {}
        self._load_vars()

        nb = ttk.Notebook(self)
        nb.pack(fill="x", padx=10, pady=(10, 4))
        self._build_mocap(nb)
        self._build_avatar(nb)
        self._build_setup(nb)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10)
        self.status = ttk.Label(bar, text="待機中")
        self.status.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="中止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=8)

        logf = ttk.Frame(self)
        logf.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log = tk.Text(logf, height=12, wrap="word", state="disabled",
                           background="#1e1e1e", foreground="#d4d4d4", insertbackground="#d4d4d4",
                           font=("Consolas" if IS_WIN else self.ui_font, 10))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._cr_pending = False

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        self._update_mocap_state()
        self._update_avatar_state()
        self.write("Kyara を起動しました。上のタブから操作してください。\n")

    # ------------------------------------------------------------------ 設定
    DEFAULTS = {
        "m_source": "camera", "m_camera": 0, "m_input": "", "m_guide": "", "m_mirror_guide": True,
        "m_start": "0", "m_duration": "", "m_model": "full", "m_skeleton": True,
        "m_output": str(BASE / "output" / "my_motion.mp4"),
        "a_photo": "", "a_voice": "", "a_motion": "default", "a_motion_video": "", "a_guide": "",
        "a_mirror_guide": True, "a_motion_start": "0", "a_camera": 0, "a_language": "ja",
        "a_output": str(BASE / "output" / "avatar_output.mp4"), "a_text": "",
    }

    def _load_vars(self) -> None:
        saved = {}
        if SETTINGS.exists():
            try:
                saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
        for k, default in self.DEFAULTS.items():
            val = saved.get(k, default)
            if isinstance(default, bool):
                self.v[k] = tk.BooleanVar(value=bool(val))
            elif isinstance(default, int):
                self.v[k] = tk.IntVar(value=int(val))
            else:
                self.v[k] = tk.StringVar(value=str(val))

    def _save_vars(self) -> None:
        data = {k: v.get() for k, v in self.v.items()}
        if hasattr(self, "text_box"):
            data["a_text"] = self.text_box.get("1.0", "end").strip()
        try:
            SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ タブ: モーション収録
    def _build_mocap(self, nb) -> None:
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="  モーション収録  ")
        f.columnconfigure(1, weight=1)
        v = self.v

        src = ttk.Frame(f)
        src.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(src, text="入力:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(src, text="Web カメラ", value="camera", variable=v["m_source"],
                        command=self._update_mocap_state).pack(side="left")
        ttk.Label(src, text="  カメラ番号").pack(side="left")
        self.m_cam_spin = ttk.Spinbox(src, from_=0, to=9, width=4, textvariable=v["m_camera"])
        self.m_cam_spin.pack(side="left", padx=(4, 16))
        ttk.Radiobutton(src, text="動画ファイルから抽出", value="video", variable=v["m_source"],
                        command=self._update_mocap_state).pack(side="left")

        self.m_input = PathField(f, 1, "入力動画", v["m_input"], "open", VIDEO_TYPES)
        self.m_guide = PathField(f, 2, "お手本動画", v["m_guide"], "open", VIDEO_TYPES)
        g = ttk.Frame(f)
        g.grid(row=3, column=1, columnspan=2, sticky="w")
        self.m_mirror = ttk.Checkbutton(g, text="お手本を左右反転（鏡のように真似する）", variable=v["m_mirror_guide"])
        self.m_mirror.pack(side="left")
        ttk.Label(g, text="（空欄ならお手本なし。お手本の長さで自動収録）", foreground="#666").pack(side="left", padx=8)

        opt = ttk.Frame(f)
        opt.grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Label(opt, text="開始位置(秒)").pack(side="left")
        ttk.Entry(opt, textvariable=v["m_start"], width=6).pack(side="left", padx=(4, 14))
        ttk.Label(opt, text="長さ(秒)").pack(side="left")
        ttk.Entry(opt, textvariable=v["m_duration"], width=6).pack(side="left", padx=(4, 14))
        ttk.Label(opt, text="精度").pack(side="left")
        ttk.Combobox(opt, textvariable=v["m_model"], values=["lite", "full", "heavy"], width=7,
                     state="readonly").pack(side="left", padx=(4, 14))
        ttk.Checkbutton(opt, text="骨格動画も出力", variable=v["m_skeleton"]).pack(side="left")

        PathField(f, 5, "保存先", v["m_output"], "save")

        btns = ttk.Frame(f)
        btns.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.m_run = ttk.Button(btns, text="● 収録 / 抽出を開始", style="Accent.TButton", command=self.run_mocap)
        self.m_run.pack(side="left")
        ttk.Button(btns, text="保存先フォルダを開く",
                   command=lambda: self._open_dir(v["m_output"].get())).pack(side="left", padx=8)
        ttk.Label(btns, text="カメラ画面: SPACE=開始/停止  Q/ESC=終了", foreground="#666").pack(side="right")

    def _update_mocap_state(self) -> None:
        cam = self.v["m_source"].get() == "camera"
        self.m_input.set_state(not cam)
        self.m_guide.set_state(cam)
        self.m_mirror.configure(state="normal" if cam else "disabled")
        self.m_cam_spin.configure(state="normal" if cam else "disabled")

    def run_mocap(self) -> None:
        v = self.v
        out = v["m_output"].get().strip()
        if not out:
            return self.error("保存先を指定してください")
        args = ["rgb_mocap.py", "--output", out, "--model", v["m_model"].get()]
        try:
            start = float(v["m_start"].get() or 0)
            dur = v["m_duration"].get().strip()
            dur_f = float(dur) if dur else None
        except ValueError:
            return self.error("開始位置・長さは数字で入力してください")
        if start:
            args += ["--start", str(start)]
        if dur_f:
            args += ["--duration", str(dur_f)]
        if v["m_skeleton"].get():
            args.append("--skeleton_video")
        if v["m_source"].get() == "camera":
            args += ["--camera", str(v["m_camera"].get())]
            guide = v["m_guide"].get().strip()
            if guide:
                if not Path(guide).exists():
                    return self.error(f"お手本動画が見つかりません:\n{guide}")
                args += ["--guide", guide]
                if v["m_mirror_guide"].get():
                    args.append("--mirror_guide")
            self.write("カメラのウィンドウが開きます。"
                       + ("カウントダウン後に自動で収録します。\n" if guide or dur_f else "SPACE で収録開始/停止。\n"))
        else:
            src = v["m_input"].get().strip()
            if not src or not Path(src).exists():
                return self.error("入力動画を指定してください")
            args += ["--input", src]
        self.run(args, "モーション収録", on_success=lambda: self._offer_open(out))

    # ------------------------------------------------------------------ タブ: アバター動画
    def _build_avatar(self, nb) -> None:
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="  アバター動画  ")
        f.columnconfigure(1, weight=1)
        v = self.v

        ttk.Label(f, text="セリフ").grid(row=0, column=0, sticky="nw", pady=3)
        self.text_box = tk.Text(f, height=3, wrap="word")
        self.text_box.grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
        self.text_box.insert("1.0", v["a_text"].get())

        PathField(f, 1, "写真", v["a_photo"], "open", IMAGE_TYPES)
        PathField(f, 2, "声のサンプル", v["a_voice"], "open", AUDIO_TYPES)

        mf = ttk.Frame(f)
        mf.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 2))
        ttk.Label(mf, text="動き:").pack(side="left", padx=(0, 8))
        for text, val in (("既定の参照動画", "default"), ("Web カメラで収録", "mocap"), ("動画の動きを使う", "video")):
            ttk.Radiobutton(mf, text=text, value=val, variable=v["a_motion"],
                            command=self._update_avatar_state).pack(side="left", padx=(0, 10))
        ttk.Label(mf, text="カメラ番号").pack(side="left")
        self.a_cam_spin = ttk.Spinbox(mf, from_=0, to=9, width=4, textvariable=v["a_camera"])
        self.a_cam_spin.pack(side="left", padx=4)

        self.a_motion_video = PathField(f, 4, "動きの動画", v["a_motion_video"], "open", VIDEO_TYPES)
        self.a_guide = PathField(f, 5, "お手本動画", v["a_guide"], "open", VIDEO_TYPES)
        g = ttk.Frame(f)
        g.grid(row=6, column=1, columnspan=2, sticky="w")
        self.a_mirror = ttk.Checkbutton(g, text="お手本を左右反転", variable=v["a_mirror_guide"])
        self.a_mirror.pack(side="left")
        ttk.Label(g, text="  開始位置(秒)").pack(side="left")
        self.a_start = ttk.Entry(g, textvariable=v["a_motion_start"], width=6)
        self.a_start.pack(side="left", padx=4)
        ttk.Label(g, text="  言語").pack(side="left")
        ttk.Combobox(g, textvariable=v["a_language"], width=5,
                     values=["ja", "en", "zh-cn", "ko", "fr", "de", "es"]).pack(side="left", padx=4)

        PathField(f, 7, "保存先", v["a_output"], "save")

        btns = ttk.Frame(f)
        btns.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text="▶ アバター動画を生成", style="Accent.TButton",
                   command=self.run_avatar).pack(side="left")
        ttk.Button(btns, text="保存先フォルダを開く",
                   command=lambda: self._open_dir(v["a_output"].get())).pack(side="left", padx=8)
        ttk.Label(btns, text="NVIDIA GPU と MimicMotion のセットアップが必要です", foreground="#666").pack(side="right")

    def _update_avatar_state(self) -> None:
        m = self.v["a_motion"].get()
        self.a_motion_video.set_state(m == "video")
        self.a_guide.set_state(m == "mocap")
        self.a_mirror.configure(state="normal" if m == "mocap" else "disabled")
        self.a_cam_spin.configure(state="normal" if m == "mocap" else "disabled")
        self.a_start.configure(state="normal" if m != "default" else "disabled")

    def run_avatar(self) -> None:
        v = self.v
        text = self.text_box.get("1.0", "end").strip()
        photo, voice, out = v["a_photo"].get().strip(), v["a_voice"].get().strip(), v["a_output"].get().strip()
        if not text:
            return self.error("セリフを入力してください")
        if not photo or not Path(photo).exists():
            return self.error("写真を指定してください")
        if not voice or not Path(voice).exists():
            return self.error("声のサンプルを指定してください")
        if not (BASE / "MimicMotion").exists():
            return self.error("MimicMotion がセットアップされていません。\n「セットアップ」タブから導入してください。")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        args = ["generate_avatar_video.py", "--text", text, "--photo", photo, "--voice_sample", voice,
                "--output", out, "--language", v["a_language"].get() or "ja"]
        m = v["a_motion"].get()
        try:
            start = float(v["a_motion_start"].get() or 0)
        except ValueError:
            return self.error("開始位置は数字で入力してください")
        if m == "mocap":
            args += ["--mocap", "--camera", str(v["a_camera"].get())]
            guide = v["a_guide"].get().strip()
            if guide:
                if not Path(guide).exists():
                    return self.error(f"お手本動画が見つかりません:\n{guide}")
                args += ["--guide", guide]
                if v["a_mirror_guide"].get():
                    args.append("--mirror_guide")
        elif m == "video":
            mv = v["a_motion_video"].get().strip()
            if not mv or not Path(mv).exists():
                return self.error("動きの動画を指定してください")
            args += ["--motion_video", mv]
        if m != "default" and start:
            args += ["--motion_start", str(start)]
        self.run(args, "アバター動画の生成", on_success=lambda: self._offer_open(out))

    # ------------------------------------------------------------------ タブ: セットアップ
    def _build_setup(self, nb) -> None:
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="  セットアップ  ")
        f.columnconfigure(1, weight=1)
        self.env_labels = {}
        for i, (key, label) in enumerate((("python", "Python"), ("torch", "PyTorch / GPU"),
                                          ("mocap", "モーションキャプチャ"), ("mimic", "MimicMotion"))):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=2)
            self.env_labels[key] = ttk.Label(f, text="確認中...")
            self.env_labels[key].grid(row=i, column=1, sticky="w", pady=2)
        btns = ttk.Frame(f)
        btns.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(btns, text="環境を再確認", command=self.check_env).pack(side="left")
        ttk.Button(btns, text="MimicMotion をセットアップ（約 15GB）",
                   command=self.setup_mimic).pack(side="left", padx=8)
        ttk.Button(btns, text="アプリのフォルダを開く", command=lambda: open_path(BASE)).pack(side="left")
        self.after(300, self.check_env)

    def check_env(self) -> None:
        labels = self.env_labels
        labels["python"].configure(text=f"{sys.version.split()[0]}  ({sys.executable})")
        mimic_ok = (BASE / "MimicMotion" / "models" / "MimicMotion_1-1.pth").exists()
        labels["mimic"].configure(text="導入済み" if mimic_ok else "未導入（アバター動画を作るには必要）")

        def worker():
            try:
                import torch
                cuda = torch.cuda.is_available()
                gpu = torch.cuda.get_device_name(0) if cuda else "GPU なし（CPU で動作）"
                t = f"torch {torch.__version__} / {gpu}"
            except Exception as e:  # noqa: BLE001
                t = f"読み込めません: {e}"
            try:
                import cv2
                import mediapipe
                m = f"mediapipe {mediapipe.__version__} / opencv {cv2.__version__}"
            except Exception as e:  # noqa: BLE001
                m = f"読み込めません: {e}"
            self.queue.put(("env", t, m))

        threading.Thread(target=worker, daemon=True).start()

    def setup_mimic(self) -> None:
        if not messagebox.askyesno("MimicMotion", "MimicMotion とモデル（約 15GB）をダウンロードします。\n"
                                                  "NVIDIA GPU が必要です。続けますか？"):
            return

        def then_patch():
            self.run(["patch_mimicmotion.py"], "MimicMotion パッチ適用", on_success=self.check_env)

        self.run(["setup_mimicmotion.py"], "MimicMotion のセットアップ", on_success=then_patch)

    # ------------------------------------------------------------------ 実行・ログ
    def run(self, args: list[str], title: str, on_success=None) -> None:
        if self.runner.running:
            return self.error("別の処理を実行中です。終わるまでお待ちください。")
        self._save_vars()
        self.write(f"\n===== {title} =====\n")
        self.status.configure(text=f"{title} を実行中...")
        self.progress.start(12)
        self.stop_btn.configure(state="normal")
        self.after_done = on_success
        self.current_title = title
        try:
            self.runner.start(args)
        except OSError as e:
            self._finish(-1)
            self.error(f"起動できませんでした: {e}")

    def stop(self) -> None:
        if self.runner.running and messagebox.askyesno("中止", "実行中の処理を中止しますか？"):
            self.runner.stop()

    def _finish(self, code: int) -> None:
        self.progress.stop()
        self.progress["value"] = 0
        self.stop_btn.configure(state="disabled")
        title = getattr(self, "current_title", "")
        if code == 0:
            self.status.configure(text=f"{title}: 完了")
            self.write(f"----- 完了 -----\n")
            cb, self.after_done = self.after_done, None
            if cb:
                cb()
        else:
            self.status.configure(text=f"{title}: 失敗 (code {code})")
            self.write(f"----- 失敗しました (code {code})。上のログを確認してください -----\n")
            self.after_done = None

    def _poll(self) -> None:
        try:
            while True:
                kind, a, b = self.queue.get_nowait()
                if kind == "line":
                    if a.startswith(NOISE_PREFIXES) or (not a.strip() and b):
                        continue
                    self._write_line(a, b)
                elif kind == "exit":
                    self._finish(a)
                elif kind == "env":
                    self.env_labels["torch"].configure(text=a)
                    self.env_labels["mocap"].configure(text=b)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _write_line(self, line: str, carriage: bool) -> None:
        self.log.configure(state="normal")
        if self._cr_pending:  # 前の行が \r で終わった進捗表示なら上書き
            self.log.delete("end-2l linestart", "end-1c")
        self.log.insert("end", line + "\n")
        self._cr_pending = carriage
        self.log.see("end")
        self.log.configure(state="disabled")

    def write(self, text: str) -> None:
        self._cr_pending = False
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def error(self, msg: str) -> None:
        messagebox.showerror("Kyara", msg)

    def _open_dir(self, path: str) -> None:
        d = Path(path).parent if path else BASE
        d.mkdir(parents=True, exist_ok=True)
        open_path(d)

    def _offer_open(self, path: str) -> None:
        if Path(path).exists() and messagebox.askyesno("完了", f"保存しました:\n{path}\n\n再生しますか？"):
            open_path(Path(path))

    def on_close(self) -> None:
        if self.runner.running:
            if not messagebox.askyesno("終了", "実行中の処理があります。中止して終了しますか？"):
                return
            self.runner.stop()
        self._save_vars()
        self.destroy()


def main() -> None:
    if IS_WIN:
        try:  # 高 DPI で文字がぼやけないように
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
