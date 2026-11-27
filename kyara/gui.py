"""設定 GUI(週表示スケジューラー)。tkinter。"""
from __future__ import annotations

import colorsys
import os
import tkinter as tk
import tkinter.font as tkfont
import zlib
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from . import autostart
from .calview import (DAY_NAMES, clamp_range, day_segments, fmt_hm,
                      fmt_seconds, free_segments, is_free, parse_hm,
                      parse_seconds, snap)
from .schedule import (DAY, DEFAULT_SLIDE_SECONDS, VIDEO_EXTENSIONS, Default,
                       Entry, Schedule, ScheduleError)

HOUR_H = 44
LEFT = 54
HEAD_H = 26
MEDIA_EXT = {".pptx", ".ppt", ".pptm", ".ppsx", ".pps"} | VIDEO_EXTENSIONS


def color_for(path: str) -> str:
    h = (zlib.crc32(os.path.basename(path).lower().encode()) % 360) / 360
    r, g, b = colorsys.hsv_to_rgb(h, 0.35, 0.95)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def list_media(folder: str) -> dict[str, str]:
    if not folder or not os.path.isdir(folder):
        return {}
    out = {}
    for n in sorted(os.listdir(folder)):
        if (os.path.splitext(n)[1].lower() in MEDIA_EXT
                and not n.startswith("~$")):
            out[n] = os.path.join(folder, n)
    return out


def ellipsize(font: "tkfont.Font", text: str, max_px: float) -> str:
    """幅 max_px に収まるよう、末尾を … で省略する。"""
    if max_px <= 0:
        return ""
    if font.measure(text) <= max_px:
        return text
    while text and font.measure(text + "…") > max_px:
        text = text[:-1]
    return text + "…" if text else ""


class _FileField(ttk.Frame):
    """素材フォルダ内から選ぶコンボボックス + 参照ボタン。"""

    def __init__(self, master, folder: str, current: str = "") -> None:
        super().__init__(master)
        self.map = list_media(folder)
        self.var = tk.StringVar()
        cur = os.path.basename(current) if current in self.map.values() else current
        self.var.set(cur)
        ttk.Combobox(self, textvariable=self.var, width=42,
                     values=list(self.map)).pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="参照...", command=self._browse).pack(side="left", padx=4)

    def _browse(self) -> None:
        p = filedialog.askopenfilename(
            title="ファイルを選択",
            filetypes=[("PowerPoint/動画", " ".join("*" + e for e in sorted(MEDIA_EXT))),
                       ("すべて", "*.*")])
        if p:
            self.var.set(p)

    def get(self) -> str:
        t = self.var.get().strip()
        return self.map.get(t, t)


class EntryDialog(tk.Toplevel):
    """枠の追加・編集。result は Entry、削除なら "delete"、取消なら None。"""

    def __init__(self, master, schedule: Schedule, entry: Entry | None,
                 day: int, start: int, end: int) -> None:
        super().__init__(master)
        self.title("スケジュールの編集" if entry else "スケジュールの追加")
        self.resizable(False, False)
        self.transient(master)
        self.entry = entry
        self.result = None
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="ファイル").grid(row=0, column=0, sticky="w", pady=4)
        self.file = _FileField(f, schedule.folder, entry.file if entry else "")
        self.file.grid(row=0, column=1, sticky="ew")

        ttk.Label(f, text="曜日").grid(row=1, column=0, sticky="w", pady=4)
        dayf = ttk.Frame(f)
        dayf.grid(row=1, column=1, sticky="w")
        sel = set(entry.days) if entry else {day}
        self.days = []
        for i, n in enumerate(DAY_NAMES):
            v = tk.BooleanVar(value=i in sel)
            ttk.Checkbutton(dayf, text=n, variable=v).pack(side="left")
            self.days.append(v)

        ttk.Label(f, text="開始 / 終了").grid(row=2, column=0, sticky="w", pady=4)
        tf = ttk.Frame(f)
        tf.grid(row=2, column=1, sticky="w")
        self.start = tk.StringVar(value=fmt_hm(entry.start if entry else start))
        self.end = tk.StringVar(value=fmt_hm(entry.end if entry else end)
                                if (entry or end < DAY) else "24:00")
        ttk.Entry(tf, textvariable=self.start, width=7).pack(side="left")
        ttk.Label(tf, text=" 〜 ").pack(side="left")
        ttk.Entry(tf, textvariable=self.end, width=7).pack(side="left")
        ttk.Label(tf, text="  (終了が開始より前なら翌日)").pack(side="left")

        ttk.Label(f, text="1スライドの表示時間").grid(row=3, column=0, sticky="w", pady=4)
        sf = ttk.Frame(f)
        sf.grid(row=3, column=1, sticky="w")
        self.sec = tk.StringVar(
            value=str(entry.slide_seconds if entry else DEFAULT_SLIDE_SECONDS))
        ttk.Entry(sf, textvariable=self.sec, width=7).pack(side="left")
        ttk.Label(sf, text="  秒、または 分:秒(例 1:30)。動画ページは動画の長さを優先").pack(side="left")

        bf = ttk.Frame(f)
        bf.grid(row=4, column=0, columnspan=2, pady=(12, 0), sticky="e")
        if entry:
            ttk.Button(bf, text="削除", command=self._delete).pack(side="left", padx=4)
        ttk.Button(bf, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="キャンセル", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _delete(self) -> None:
        self.result = "delete"
        self.destroy()

    def _ok(self) -> None:
        try:
            days = tuple(i for i, v in enumerate(self.days) if v.get())
            self.result = Entry(days, parse_hm(self.start.get()) % DAY,
                                parse_hm(self.end.get()), self.file.get(),
                                parse_seconds(self.sec.get()),
                                self.entry.id if self.entry else
                                __import__("uuid").uuid4().hex)
        except (ValueError, ScheduleError) as e:
            messagebox.showerror("入力エラー", str(e), parent=self)
            return
        self.destroy()


class DefaultDialog(tk.Toplevel):
    def __init__(self, master, schedule: Schedule) -> None:
        super().__init__(master)
        self.title("空き時間に流す既定ファイル")
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        d = schedule.default
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="ファイル").grid(row=0, column=0, sticky="w", pady=4)
        self.file = _FileField(f, schedule.folder, d.file if d else "")
        self.file.grid(row=0, column=1)
        ttk.Label(f, text="1スライドの表示時間").grid(row=1, column=0, sticky="w", pady=4)
        self.sec = tk.StringVar(value=str(d.slide_seconds if d else DEFAULT_SLIDE_SECONDS))
        ttk.Entry(f, textvariable=self.sec, width=8).grid(row=1, column=1, sticky="w")
        bf = ttk.Frame(f)
        bf.grid(row=2, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(bf, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="キャンセル", command=self.destroy).pack(side="left")
        self.grab_set()
        self.wait_visibility()

    def _ok(self) -> None:
        try:
            self.result = Default(self.file.get(), parse_seconds(self.sec.get()))
        except (ValueError, ScheduleError) as e:
            messagebox.showerror("入力エラー", str(e), parent=self)
            return
        self.destroy()


class App:
    def __init__(self, root: tk.Tk, schedule: Schedule, cfg_path: str,
                 controller, on_quit) -> None:
        self.root, self.schedule, self.cfg_path = root, schedule, cfg_path
        self.ctl, self.on_quit = controller, on_quit
        self._rects: list[tuple[float, float, float, float, Entry]] = []
        self._drag: tuple[int, int] | None = None
        self._drag_range: tuple[int, int] | None = None
        self.has_tray = False
        root.title("kyara - スライドショー スケジューラー")
        root.geometry("980x700")
        root.protocol("WM_DELETE_WINDOW", self.hide)
        self.f_small = tkfont.Font(family="", size=8)
        self.f_block = tkfont.Font(family="", size=9)
        self._build()
        self.root.after(100, self._scroll_initial)
        self._periodic()

    # --- 構築 ---
    def _build(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="既定ファイル...", command=self.edit_default).pack(side="left")
        ttk.Button(bar, text="素材フォルダ...", command=self.pick_folder).pack(side="left", padx=4)
        ttk.Button(bar, text="停止から再開", command=self.ctl.resume).pack(side="left")
        self.auto = tk.BooleanVar(value=autostart.is_enabled())
        ttk.Checkbutton(bar, text="Windows 起動時に自動起動", variable=self.auto,
                        command=self.toggle_autostart).pack(side="left", padx=12)
        ttk.Button(bar, text="終了", command=self.quit_clicked).pack(side="right")
        self.info = ttk.Label(self.root, foreground="#555", padding=(8, 0))
        self.info.pack(fill="x")

        self.head = tk.Canvas(self.root, height=HEAD_H, highlightthickness=0, bg="white")
        self.head.pack(fill="x")
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)
        self.cv = tk.Canvas(body, bg="white", highlightthickness=0,
                            scrollregion=(0, 0, 10, 24 * HOUR_H + 8))
        sb = ttk.Scrollbar(body, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.status = ttk.Label(self.root, relief="sunken", anchor="w", padding=4)
        self.status.pack(fill="x", side="bottom")

        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Double-Button-1>", self._double)
        self.cv.bind("<Button-3>", self._right)
        self.cv.bind("<MouseWheel>",
                     lambda e: self.cv.yview_scroll(-int(e.delta / 120), "units"))
        self.menu = tk.Menu(self.root, tearoff=0)

    def _scroll_initial(self) -> None:
        self.cv.yview_moveto(7 * HOUR_H / (24 * HOUR_H + 8))

    # --- 描画 ---
    def _colw(self) -> float:
        return max(40.0, (self.cv.winfo_width() - LEFT) / 7)

    def redraw(self) -> None:
        cv, colw = self.cv, self._colw()
        cv.delete("all")
        self.head.delete("all")
        self._rects = []
        total_h = 24 * HOUR_H
        dflt = (os.path.basename(self.schedule.default.file)
                if self.schedule.default else "未設定")
        today = datetime.now().weekday()
        for d in range(7):
            x0 = LEFT + d * colw
            self.head.create_rectangle(x0, 0, x0 + colw, HEAD_H,
                                       fill="#dbe8fb" if d == today else "#f3f3f3",
                                       outline="#ccc")
            self.head.create_text(x0 + colw / 2, HEAD_H / 2, text=DAY_NAMES[d],
                                  font=("", 10, "bold"))
            segs = day_segments(self.schedule, d)
            cv.create_rectangle(x0, 0, x0 + colw, total_h, fill="#f6f6f6", outline="", tags="bg")
            for a, b in free_segments([(s, e) for s, e, _ in segs]):
                if b - a >= 30:
                    cv.create_text(
                        x0 + 4, a / 60 * HOUR_H + 3, anchor="nw",
                        fill="#aaa", font=self.f_small,
                        text=ellipsize(self.f_small, f"既定: {dflt}", colw - 8))
            for a, b, e in segs:
                y0, y1 = a / 60 * HOUR_H, b / 60 * HOUR_H
                cv.create_rectangle(x0 + 2, y0 + 1, x0 + colw - 2, y1 - 1,
                                    fill=color_for(e.file), outline="#789")
                lines = [os.path.basename(e.file),
                         f"{fmt_hm(e.start)}–{fmt_hm(e.end)}",
                         f"{fmt_seconds(e.slide_seconds)}/枚"]
                line_h = 15
                n = min(3, int((y1 - y0 - 4) // line_h))  # 低すぎるブロックは文字なし
                if n == 1:  # 低いブロックは 1 行にまとめる
                    lines = [f"{lines[0]}  {lines[1]}"]
                elif n == 2:
                    lines = [lines[0], f"{lines[1]}  {lines[2]}"]
                for i, t in enumerate(lines[:max(n, 0)]):
                    cv.create_text(x0 + 6, y0 + 3 + i * line_h, anchor="nw",
                                   font=self.f_block,
                                   text=ellipsize(self.f_block, t, colw - 12))
                self._rects.append((x0, y0, x0 + colw, y1, e))
        for h in range(25):
            y = h * HOUR_H
            cv.create_line(LEFT, y, LEFT + 7 * colw, y, fill="#ddd", tags="grid")
            if h < 24:
                cv.create_text(LEFT - 6, y + 2, anchor="ne", text=f"{h}:00",
                               fill="#666", font=("", 9))
        for d in range(8):
            cv.create_line(LEFT + d * colw, 0, LEFT + d * colw, total_h, fill="#ddd", tags="grid")
        cv.tag_lower("grid")
        cv.tag_lower("bg")  # 背景 < 罫線 < 枠
        n = datetime.now()
        y = (n.hour * 60 + n.minute) / 60 * HOUR_H
        cv.create_line(LEFT + today * colw, y, LEFT + (today + 1) * colw, y,
                       fill="red", width=2)
        cv.configure(scrollregion=(0, 0, LEFT + 7 * colw, total_h + 8))
        self._draw_drag()
        d = self.schedule.default
        self.info.configure(
            text=f"素材フォルダ: {self.schedule.folder or '(未設定)'}   |   "
                 f"既定ファイル: {d.file if d else '(未設定: 「既定ファイル...」で設定してください)'}"
                 f"   |   空き枠をドラッグして追加 / 枠をダブルクリックで編集")

    def _draw_drag(self) -> None:
        self.cv.delete("rb")
        if self._drag is None or self._drag_range is None:
            return
        d = self._drag[0]
        lo, hi = self._drag_range
        x0 = LEFT + d * self._colw()
        self.cv.create_rectangle(x0 + 2, lo / 60 * HOUR_H, x0 + self._colw() - 2,
                                 hi / 60 * HOUR_H, fill="#9ec5ff", outline="#2a6fd6",
                                 stipple="gray50", tags="rb")

    def _periodic(self) -> None:
        self.status.configure(text=self.ctl.status())
        if int(datetime.now().timestamp()) % 30 < 2:
            self.redraw()
        self.root.after(1500, self._periodic)

    # --- 座標 ---
    def _hit(self, ev) -> tuple[int, float, Entry | None] | None:
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        colw = self._colw()
        if x < LEFT or x >= LEFT + 7 * colw or y < 0 or y > 24 * HOUR_H:
            return None
        d = int((x - LEFT) // colw)
        m = y / HOUR_H * 60
        for x0, y0, x1, y1, e in self._rects:
            if x0 <= x < x1 and y0 <= y < y1:
                return d, m, e
        return d, m, None

    def _busy(self, d: int) -> list[tuple[int, int]]:
        return [(s, e) for s, e, _ in day_segments(self.schedule, d)]

    # --- マウス操作 ---
    def _press(self, ev) -> None:
        self._drag = self._drag_range = None
        h = self._hit(ev)
        if h is None or h[2] is not None:
            return  # 入っている枠は固定(ドラッグ移動・変更なし)
        d, m, _ = h
        a = snap(m, "floor")
        if is_free(self._busy(d), a):
            self._drag = (d, a)
            self._drag_range = clamp_range(self._busy(d), a, min(DAY, a + 60))
            self._moved = False
            self._draw_drag()

    def _motion(self, ev) -> None:
        if self._drag is None:
            return
        y = self.cv.canvasy(ev.y)
        cur = snap(max(0, min(24 * HOUR_H, y)) / HOUR_H * 60)
        self._moved = True
        self._drag_range = clamp_range(self._busy(self._drag[0]), self._drag[1], cur)
        self._draw_drag()

    def _release(self, ev) -> None:
        if self._drag is None or self._drag_range is None:
            return
        d, (lo, hi) = self._drag[0], self._drag_range
        self._drag = self._drag_range = None
        self.cv.delete("rb")
        if hi - lo >= 1:
            self.edit_entry(None, d, lo, hi)

    def _double(self, ev) -> None:
        h = self._hit(ev)
        if h and h[2] is not None:
            self._drag = None
            self.edit_entry(h[2], h[0], h[2].start, h[2].end)

    def _right(self, ev) -> None:
        h = self._hit(ev)
        if not h or h[2] is None:
            return
        e = h[2]
        self.menu.delete(0, "end")
        self.menu.add_command(label="編集", command=lambda: self.edit_entry(e, h[0], e.start, e.end))
        self.menu.add_command(label="削除", command=lambda: self.delete_entry(e))
        try:
            self.menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            self.menu.grab_release()  # Windows でメニューが残る/反応しない対策

    # --- 変更の反映 ---
    def _commit(self, new: Schedule) -> None:
        new.save(self.cfg_path)
        self.schedule = new
        self.ctl.set_schedule(new)
        self.redraw()

    def edit_entry(self, entry: Entry | None, day: int, start: int, end: int) -> None:
        dlg = EntryDialog(self.root, self.schedule, entry, day, start, end)
        self.root.wait_window(dlg)
        r = dlg.result
        if r is None:
            return
        if r == "delete":
            return self.delete_entry(entry)
        new = self.schedule.copy()
        try:
            new.update(r) if entry else new.add(r)
        except ScheduleError as e:  # 重複(OverlapError を含む)
            messagebox.showerror("登録できません", str(e), parent=self.root)
            return
        self._commit(new)

    def delete_entry(self, entry: Entry) -> None:
        if messagebox.askyesno("削除", f"「{os.path.basename(entry.file)}」の枠を削除しますか?"):
            new = self.schedule.copy()
            new.remove(entry.id)
            self._commit(new)

    def edit_default(self) -> None:
        dlg = DefaultDialog(self.root, self.schedule)
        self.root.wait_window(dlg)
        if dlg.result:
            new = self.schedule.copy()
            new.default = dlg.result
            self._commit(new)

    def pick_folder(self) -> None:
        p = filedialog.askdirectory(title="PowerPoint / 動画を置いているフォルダ",
                                    initialdir=self.schedule.folder or None)
        if p:
            new = self.schedule.copy()
            new.folder = os.path.normpath(p)
            self._commit(new)

    def toggle_autostart(self) -> None:
        try:
            autostart.set_enabled(self.auto.get())
        except Exception as e:
            self.auto.set(not self.auto.get())
            messagebox.showerror("自動起動", f"設定できませんでした: {e}")

    # --- ウィンドウ ---
    def hide(self) -> None:
        if self.has_tray:
            self.root.withdraw()
        else:
            self.root.iconify()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_clicked(self) -> None:
        if messagebox.askyesno("終了", "スケジュール再生も止まります。終了しますか?"):
            self.on_quit()
