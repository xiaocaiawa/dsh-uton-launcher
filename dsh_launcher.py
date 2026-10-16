# -*- coding: utf-8 -*-
"""DSH 启动器（PCL 风格界面）

布局：
  加载页  —— 彩虹圆环旋转 + 分步文字（PCL 那种启动仪式感）
  主界面  —— 深色标题栏 + 左侧竖排导航 + 右侧内容卡片 + 底部状态条
  三个页  —— 服务 / 版本与更新 / 插件体检

配色照 PCL2 的观感来：主题蓝 #1370b1、深色顶栏、白卡片、浅灰内容底。
线程纪律：后台线程只往 queue 里塞消息，绝不直接碰控件、也不调 after()。
"""

import io
import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsh_core as C

# ---------------------------------------------------------------- 配色与字体

def _system_dark():
    """Windows 的「应用使用浅色/深色主题」设置。"""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            v, _t = winreg.QueryValueEx(k, "AppsUseLightTheme")
        finally:
            winreg.CloseKey(k)
        return int(v) == 0
    except Exception:
        return False


def _theme_mode():
    try:
        pref = str(C.load_settings().get("theme", "light"))
    except Exception:
        pref = "light"
    if pref == "system":
        return "dark" if _system_dark() else "light"
    return "dark" if pref == "dark" else "light"


# 两套配色。所有颜色都从这里取 —— 想加深色只改这张表。
PALETTE = {
    "light": {
        "BLUE": "#1370b1", "BLUE_D": "#0e5b90", "BLUE_L": "#e9f4fc",
        "TITLE_BG": "#23262b", "NAV_BG": "#ffffff", "PAGE_BG": "#eef1f5",
        "CARD": "#ffffff", "SHADOW": "#e6eaf0", "LINE": "#e6eaef",
        "INK": "#26282b", "DIM": "#787d85", "FAINT": "#a3a8b0",
        "OK": "#2e9e4f", "OK_LIGHT": "#8fd6a4", "WARN": "#d98324", "BAD": "#d64545",
        "TRACK": "#e6eaef",
        "SOFT": "#fafbfc", "SOFT2": "#fafafa", "SOFT_ODD": "#fafbfd",
        "BTN": "#ffffff", "BTN_LINE": "#d8dee6", "BTN_HOVER": "#f2f5f9",
        "OFF_BG": "#f4f6f8", "OFF_FG": "#b9bec6", "OFF_LINE": "#eaeef3",
        "FIELD": "#fafafa",
        "DANGER_BG": "#fdeaea", "DANGER_FG": "#b73a3a",
        "DANGER_LINE": "#f6d5d5", "DANGER_HOVER": "#f9dede",
        "SEG_LINE": "#e2e7ee", "SEG_HOVER": "#f5f7fa",
        "PILL_EDGE": "#d5e6f6", "BADGE_BG": "#333333", "BADGE_FG": "#cccccc",
        "TOAST_EDGE": "#e3e8ef", "TOP_EDGE": "#3a3f47", "TOP_DIM": "#9aa0a8",
    },
    "dark": {
        "BLUE": "#4a9ede", "BLUE_D": "#3a86c0", "BLUE_L": "#1e3a52",
        "TITLE_BG": "#15181d", "NAV_BG": "#1c2027", "PAGE_BG": "#12151a",
        "CARD": "#20242b", "SHADOW": "#0d0f13", "LINE": "#2c323b",
        "INK": "#e7eaf0", "DIM": "#98a0ac", "FAINT": "#6c757f",
        "OK": "#4fbf72", "OK_LIGHT": "#7fd39b", "WARN": "#e0a04a", "BAD": "#e26060",
        "TRACK": "#2c323b",
        "SOFT": "#1a1e24", "SOFT2": "#1a1e24", "SOFT_ODD": "#1e222a",
        "BTN": "#2a3038", "BTN_LINE": "#3a424c", "BTN_HOVER": "#343c46",
        "OFF_BG": "#242931", "OFF_FG": "#5d666f", "OFF_LINE": "#2c323b",
        "FIELD": "#1a1e24",
        "DANGER_BG": "#3a2020", "DANGER_FG": "#e88b8b",
        "DANGER_LINE": "#4d2a2a", "DANGER_HOVER": "#472626",
        "SEG_LINE": "#343b45", "SEG_HOVER": "#2a3038",
        "PILL_EDGE": "#24435c", "BADGE_BG": "#333a44", "BADGE_FG": "#c8cdd5",
        "TOAST_EDGE": "#333a44", "TOP_EDGE": "#2e343d", "TOP_DIM": "#9aa3ad",
    },
}

THEME_MODE = _theme_mode()
_T = PALETTE[THEME_MODE]

# 强调色：把主题蓝换掉，整份 UI 的蓝一起换（重启生效）。
ACCENTS = [("蓝", "blue"), ("青", "cyan"), ("紫", "violet"), ("橙", "orange")]
ACCENT_HEX = {
    "light": {"blue": ("#1370b1", "#0e5b90", "#e9f4fc"),
              "cyan": ("#0d8ba6", "#0a6d83", "#e2f4f7"),
              "violet": ("#6b4fd8", "#563fae", "#efeafd"),
              "orange": ("#c96a15", "#a3540f", "#fdf0e2")},
    "dark": {"blue": ("#4a9ede", "#3a86c0", "#1e3a52"),
             "cyan": ("#4ec2d8", "#3ba0b4", "#153a42"),
             "violet": ("#9b86ef", "#7d68d6", "#2a2547"),
             "orange": ("#e0a04a", "#c08434", "#3d2f18")},
}


def _pref(key, default):
    try:
        return C.load_settings().get(key, default)
    except Exception:
        return default


ACCENT_MODE = str(_pref("accent", "blue"))
if ACCENT_MODE not in ACCENT_HEX[THEME_MODE]:
    ACCENT_MODE = "blue"
for _k, _v in zip(("BLUE", "BLUE_D", "BLUE_L"), ACCENT_HEX[THEME_MODE][ACCENT_MODE]):
    _T[_k] = _v

# 界面密度：紧凑就把卡片内边距和页间距收一收（重启生效）。
DENSITY = "compact" if str(_pref("density", "normal")) == "compact" else "normal"
CARD_PAD = 14 if DENSITY == "compact" else 22
PAGE_PAD = 12 if DENSITY == "compact" else 20
PAGE_GAP = 10 if DENSITY == "compact" else 18

BLUE = _T["BLUE"]            # 主题色
BLUE_D = _T["BLUE_D"]        # 按下
BLUE_L = _T["BLUE_L"]        # 选中底
TITLE_BG = _T["TITLE_BG"]    # 标题栏 / 加载页底
TITLE_FG = "#ffffff"
NAV_BG = _T["NAV_BG"]
PAGE_BG = _T["PAGE_BG"]      # 内容区底
CARD = _T["CARD"]
SHADOW = _T["SHADOW"]        # 卡片投影
LINE = _T["LINE"]
INK = _T["INK"]
DIM = _T["DIM"]
FAINT = _T["FAINT"]
OK = _T["OK"]
OK_LIGHT = _T["OK_LIGHT"]
WARN = _T["WARN"]
BAD = _T["BAD"]
TRACK = _T["TRACK"]
SOFT = _T["SOFT"]            # 次级底（状态条 / 日志框）
SOFT2 = _T["SOFT2"]
SOFT_ODD = _T["SOFT_ODD"]
BTN = _T["BTN"]              # plain 按钮底
BTN_LINE = _T["BTN_LINE"]
BTN_HOVER = _T["BTN_HOVER"]
OFF_BG, OFF_FG, OFF_LINE = _T["OFF_BG"], _T["OFF_FG"], _T["OFF_LINE"]
FIELD = _T["FIELD"]
DANGER_BG, DANGER_FG = _T["DANGER_BG"], _T["DANGER_FG"]
DANGER_LINE, DANGER_HOVER = _T["DANGER_LINE"], _T["DANGER_HOVER"]
SEG_LINE, SEG_HOVER = _T["SEG_LINE"], _T["SEG_HOVER"]
PILL_EDGE = _T["PILL_EDGE"]
BADGE_BG, BADGE_FG = _T["BADGE_BG"], _T["BADGE_FG"]
TOAST_EDGE = _T["TOAST_EDGE"]
TOP_EDGE, TOP_DIM = _T["TOP_EDGE"], _T["TOP_DIM"]
FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# ---------------------------------------------------------------- 动画引擎
# 所有动画的时长都过一遍 dur()，这样「动画速度」设置能一处管全部。

ANIM_SPEED = {"off": 0.0, "fast": 0.55, "normal": 1.0, "slow": 1.6}
_ANIM = 1.0


def set_anim(name):
    global _ANIM
    _ANIM = ANIM_SPEED.get(str(name), 1.0)
    return _ANIM


def anim_on():
    return _ANIM > 0


def dur(ms):
    """把设计时长换算成这一档速度下的实际毫秒。关闭动画时返回 0。"""
    if _ANIM <= 0:
        return 0
    return max(1, int(round(ms * _ANIM)))


def ease(t):
    """ease-out cubic：开头快、收尾慢（观感比线性顺）。"""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def blend(c1, c2, k):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def hsl_hex(h, s, l):
    """HSL → #rrggbb（画彩虹环用）。h 单位是度。"""
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2.0
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return "#%02x%02x%02x" % (int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    kw.setdefault("outline", kw.get("fill", ""))
    return cv.create_polygon(pts, smooth=True, **kw)


def mix(c1, c2, t):
    """两个 #rrggbb 之间插值：t=0 取 c1，t=1 取 c2。"""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- 自绘控件

def asset_path(name):
    """资源文件：打包成 onefile 后在 sys._MEIPASS，源码运行时在脚本旁边。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


class Scroll(tk.Frame):
    """竖向滚动容器 —— 内容塞进 .body，滚轮或右侧细条滚。"""

    def __init__(self, parent, bg=PAGE_BG):
        super().__init__(parent, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                            yscrollincrement=26)
        self.bar = tk.Canvas(self, bg=bg, width=9, highlightthickness=0, bd=0)
        self.body = tk.Frame(self.cv, bg=bg)
        self._win = self.cv.create_window((0, 0), window=self.body, anchor="nw")
        self.cv.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self._thumb = None
        self.body.bind("<Configure>", self._on_body)
        self.cv.bind("<Configure>", self._on_cv)
        self.bar.bind("<Button-1>", self._on_bar_click)

    def _on_body(self, _e=None):
        self.cv.configure(scrollregion=self.cv.bbox("all"))
        self._paint_bar()

    def _on_cv(self, ev):
        self.cv.itemconfigure(self._win, width=ev.width)
        self._paint_bar()

    def _paint_bar(self):
        self.bar.delete("all")
        h = self.bar.winfo_height()
        if h <= 4:
            return
        first, last = self.cv.yview()
        if last - first >= 0.999:
            return
        y1 = first * h
        y2 = max(last * h, y1 + 28)
        round_rect(self.bar, 2.5, y1, 6.5, y2, 2, fill=FAINT, outline=FAINT)

    def _on_bar_click(self, ev):
        h = max(1, self.bar.winfo_height())
        self.cv.yview_moveto(max(0.0, min(1.0, ev.y / float(h) - 0.08)))
        self._paint_bar()

    def scroll_by(self, units):
        first, last = self.cv.yview()
        if last - first >= 0.999:
            return False
        self.cv.yview_scroll(int(units), "units")
        self._paint_bar()
        return True


class Card(tk.Frame):
    """圆角白卡片（带一点投影）。内容放进 .body。"""

    def __init__(self, parent, title="", accent=BLUE, pad=CARD_PAD, radius=14):
        super().__init__(parent, bg=PAGE_BG)
        self._radius = radius
        self.canvas = tk.Canvas(self, bg=PAGE_BG, highlightthickness=0, bd=0, height=24)
        self.canvas.pack(fill="both", expand=True)
        self._inner = tk.Frame(self.canvas, bg=CARD)
        self._win = self.canvas.create_window(2, 2, window=self._inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas)
        self._inner.bind("<Configure>", self._on_inner)

        wrap = tk.Frame(self._inner, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.head = None
        if title:
            self.head = tk.Frame(wrap, bg=CARD)
            self.head.pack(fill="x", pady=(0, 15))
            bar = tk.Frame(self.head, bg=accent, width=4, height=16)
            bar.pack(side="left", padx=(0, 10))
            bar.pack_propagate(False)
            tk.Label(self.head, text=title, bg=CARD, fg=INK,
                     font=(FONT, 11, "bold")).pack(side="left")
        self.body = tk.Frame(wrap, bg=CARD)
        self.body.pack(fill="both", expand=True)

    def _on_canvas(self, ev):
        w, h = ev.width, ev.height
        self.canvas.delete("shape")
        round_rect(self.canvas, 3, 4, w - 2, h - 1, self._radius,
                   fill=SHADOW, outline=SHADOW, tags="shape")
        round_rect(self.canvas, 1, 1, w - 5, h - 5, self._radius,
                   fill=CARD, outline=LINE, width=1, tags="shape")
        self.canvas.tag_lower("shape")
        self.canvas.coords(self._win, 2, 2)
        self.canvas.itemconfigure(self._win, width=max(10, w - 8))

    def _on_inner(self, ev):
        self.canvas.configure(height=ev.height + 8)


class Ask(tk.Frame):
    """项目内确认框：居中一张小卡片，不用系统弹窗。"""

    def __init__(self, parent, title, text, on_ok, on_cancel=None,
                 ok_text="继续", cancel_text="取消"):
        super().__init__(parent, bg=CARD)
        self.on_ok = on_ok
        self.on_cancel = on_cancel
        self._done = False
        self.canvas = tk.Canvas(self, bg=PAGE_BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        inner = tk.Frame(self.canvas, bg=CARD)
        self._win = self.canvas.create_window((2, 2), window=inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self._paint(e.width, e.height))

        box = tk.Frame(inner, bg=CARD)
        box.pack(fill="both", expand=True, padx=24, pady=22)
        tk.Label(box, text=title, bg=CARD, fg=INK, font=(FONT, 12, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(box, text=text, bg=CARD, fg=DIM, font=(FONT, 10), anchor="w",
                 justify="left", wraplength=370).pack(fill="x", pady=(9, 0))
        bar = tk.Frame(box, bg=CARD)
        bar.pack(fill="x", side="bottom", pady=(16, 0))
        Btn(bar, ok_text, self._ok, "main", padx=18, pady=8).pack(side="right")
        Btn(bar, cancel_text, self._no, "plain", padx=16,
            pady=8).pack(side="right", padx=(0, 10))
        self.place(relx=0.5, rely=0.44, anchor="center", width=450, height=210)

    def _paint(self, w, h):
        self.canvas.delete("shape")
        round_rect(self.canvas, 3, 5, w - 2, h - 1, 16,
                   fill=SHADOW, outline=SHADOW, tags="shape")
        round_rect(self.canvas, 1, 1, w - 5, h - 5, 16,
                   fill=CARD, outline=LINE, width=1, tags="shape")
        self.canvas.tag_lower("shape")
        self.canvas.itemconfigure(self._win, width=max(10, w - 8))

    def _ok(self):
        self.close()
        if self.on_ok:
            self.on_ok()

    def _no(self):
        self.close()
        if self.on_cancel:
            self.on_cancel()

    def close(self):
        if self._done:
            return
        self._done = True
        try:
            self.destroy()
        except tk.TclError:
            pass


class Panel(tk.Frame):
    """项目内报告浮层：标题 + 正文 + 关掉。不用系统弹窗。"""

    W, H = 580, 446

    def __init__(self, parent, title, subtitle, lines, ok=True):
        super().__init__(parent, bg=CARD)
        self._done = False
        self.canvas = tk.Canvas(self, bg=PAGE_BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        inner = tk.Frame(self.canvas, bg=CARD)
        self._win = self.canvas.create_window((2, 2), window=inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self._paint(e.width, e.height))

        box = tk.Frame(inner, bg=CARD)
        box.pack(fill="both", expand=True, padx=22, pady=18)
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x")
        bar = tk.Frame(head, bg=(BLUE if ok else WARN), width=4, height=16)
        bar.pack(side="left", padx=(0, 10))
        bar.pack_propagate(False)
        tk.Label(head, text=title, bg=CARD, fg=INK, font=(FONT, 12, "bold"),
                 anchor="w").pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=CARD, fg=FAINT,
                     font=(FONT, 9)).pack(side="left", padx=(10, 0), pady=(3, 0))

        edge = tk.Frame(box, bg=LINE)
        edge.pack(fill="both", expand=True, pady=(12, 0))
        wrap = tk.Frame(edge, bg=FIELD)
        wrap.pack(fill="both", expand=True, padx=1, pady=1)
        self.txt = tk.Text(wrap, bg=FIELD, fg=INK, font=(FONT, 10), bd=0,
                           highlightthickness=0, wrap="word", padx=14, pady=12,
                           height=10, spacing1=1, spacing3=4,
                           selectbackground=BLUE_L, selectforeground=INK)
        self.txt.pack(fill="both", expand=True)
        self.txt.insert("1.0", "\n".join(lines) if lines else "（没有内容）")
        self.txt.configure(state="disabled")
        self.txt.bind("<MouseWheel>", self._wheel)

        foot = tk.Frame(box, bg=CARD)
        foot.pack(fill="x", pady=(14, 0))
        Btn(foot, "关掉", self.close, "main", padx=20, pady=8).pack(side="right")
        self.place(relx=0.5, rely=0.47, anchor="center", width=self.W, height=self.H)
        self.fade_in()

    def _wheel(self, ev):
        try:
            self.txt.yview_scroll(int(-ev.delta / 120.0), "units")
        except tk.TclError:
            pass

    def fade_in(self):
        """从下方 14px 滑上来（tk 没法给子控件做透明度，用位移代替）。"""
        if not anim_on():
            return
        span = dur(190)
        tick = 12

        def step(elapsed):
            if self._done or not self.winfo_exists():
                return
            k = 1.0 if span <= 0 else min(1.0, elapsed / float(span))
            self.place_configure(rely=0.47 + 0.03 * (1 - ease(k)))
            if k < 1.0:
                self.after(tick, lambda: step(elapsed + tick))

        step(0)

    def _paint(self, w, h):
        self.canvas.delete("shape")
        round_rect(self.canvas, 3, 5, w - 2, h - 1, 16,
                   fill=SHADOW, outline=SHADOW, tags="shape")
        round_rect(self.canvas, 1, 1, w - 5, h - 5, 16,
                   fill=CARD, outline=LINE, width=1, tags="shape")
        self.canvas.tag_lower("shape")
        self.canvas.itemconfigure(self._win, width=max(10, w - 8))

    def close(self):
        if self._done:
            return
        self._done = True
        try:
            self.destroy()
        except tk.TclError:
            pass


class Btn(tk.Canvas):
    """圆角按钮。用 set_enabled / set_text / set_kind，别用 configure(state=...)。"""

    KINDS = {
        "plain":   (BTN, INK, BTN_LINE, BTN_HOVER),
        "main":    (BLUE, "#ffffff", BLUE, BLUE_D),
        "danger":  (DANGER_BG, DANGER_FG, DANGER_LINE, DANGER_HOVER),
        "ghost":   (CARD, BLUE, CARD, BLUE_L),
        "seg_off": (CARD, DIM, SEG_LINE, SEG_HOVER),
        "seg_on":  (BLUE, "#ffffff", BLUE, BLUE),
    }

    def __init__(self, parent, text, cmd=None, kind="plain", bg=CARD,
                 font=(FONT, 10), padx=16, pady=8, width=None, radius=None):
        self._font_spec = font
        self._font = tkfont.Font(font=font)
        self._padx, self._pady = padx, pady
        self._bg = bg
        self._kind = kind
        self._text = text
        self._enabled = True
        self._hover = False
        self._busy = False
        self._busy_text = ""
        self._busy_kind = None
        self._busy_t = 0.0
        self._busy_i = 0
        self._cmd = cmd
        w = width or (self._font.measure(text) + padx * 2)
        h = self._font.metrics("linespace") + pady * 2
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._cw, self._ch = w, h
        self._radius = radius if radius is not None else min(7.0, h / 2.0)
        self._draw()
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    def _draw(self, t=None, press=False):
        fill, fg, outline, hover = self.KINDS[self._kind]
        if self._busy and self._busy_kind:
            fill, fg, outline, hover = self.KINDS[self._busy_kind]
        if not self._enabled and not self._busy:
            fill, fg, outline = OFF_BG, OFF_FG, OFF_LINE
        elif not self._busy and self._kind != "seg_on":
            if t is None:
                t = 1.0 if self._hover else 0.0
            if t > 0:
                fill = mix(fill, hover, t)
                outline = mix(outline, hover, t)
        d = 1.0 if press else 0.0
        if press:
            fill = mix(fill, "#000000", 0.13)
            outline = mix(outline, "#000000", 0.13)
        self.delete("all")
        if fill != self._bg or d:
            round_rect(self, d, d, self._cw - d, self._ch - d, self._radius,
                       fill=fill, outline=outline)
        txt = self._busy_text if self._busy else self._text
        self.create_text(self._cw / 2.0, self._ch / 2.0 + d, text=txt, fill=fg,
                         font=self._font_spec)
        if self._busy:
            seg = max(26.0, self._cw * 0.36)
            span = max(1.0, self._cw - seg - 10)
            x0 = 5 + span * self._busy_t
            self.create_rectangle(x0, self._ch - 4.0, x0 + seg, self._ch - 2.0,
                                  fill=mix(fg, fill, 0.3), outline="")

    def set_busy(self, on, text=None, kind=None):
        """忙碌态：保持亮色但点不动，文字可换，底下来回扫一条细进度。"""
        on = bool(on)
        if on == self._busy:
            if on and text and text != self._busy_text:
                self._busy_text = text
                self._draw()
            return
        if on:
            self._busy = True
            self._busy_text = text or self._text
            self._busy_kind = kind or self._kind
            self._busy_i = 0
            self._busy_t = 0.0
            self._enabled = False
            self.configure(cursor="arrow")
            self._draw()
            self._busy_tick()
        else:
            self._busy = False
            self._busy_text = ""
            self._busy_kind = None
            self._enabled = True
            self.configure(cursor="hand2")
            self._draw()

    def _busy_tick(self):
        if not self._busy:
            return
        self._busy_i = (self._busy_i + 1) % 40
        p = self._busy_i / 39.0
        self._busy_t = p * 2.0 if p < 0.5 else (1.0 - p) * 2.0
        try:
            self._draw()
        except tk.TclError:
            return
        self.after(dur(30), self._busy_tick)

    def _recalc(self):
        self._cw = self._font.measure(self._text) + self._padx * 2
        self._ch = self._font.metrics("linespace") + self._pady * 2
        self._radius = min(7.0, self._ch / 2.0)
        self.configure(width=self._cw, height=self._ch)
        self._draw()

    def set_text(self, text):
        if text != self._text:
            self._text = text
            self._recalc()

    def set_kind(self, kind):
        if kind != self._kind:
            self._kind = kind
            self._draw()

    def set_enabled(self, on):
        if bool(on) != self._enabled:
            self._enabled = bool(on)
            self.configure(cursor="hand2" if on else "arrow")
            self._draw()

    def _click(self, _evt):
        if not self._enabled:
            return
        self._press_anim()
        if self._cmd:
            self._cmd()

    def _press_anim(self):
        """按下时缩一点、压暗，再弹回来。"""
        self._tok = getattr(self, "_tok", 0) + 1
        tok = self._tok
        frames = (True, True, False, False)

        def frame(i):
            if tok != self._tok:
                return
            try:
                self._draw(t=(1.0 if self._hover else 0.0), press=frames[i])
            except tk.TclError:
                return
            if i < len(frames) - 1:
                self.after(dur(24), lambda: frame(i + 1))

        frame(0)

    def _enter(self, _evt):
        if self._hover or not self._enabled:
            return
        self._hover = True
        self._hover_anim(True)

    def _leave(self, _evt):
        if not self._hover:
            return
        self._hover = False
        self._hover_anim(False)

    def _hover_anim(self, on):
        """hover 渐变，6 帧走完，用令牌防止快速进出时打架。"""
        self._tok = getattr(self, "_tok", 0) + 1
        tok = self._tok

        def frame(i):
            if tok != self._tok:
                return
            try:
                self._draw(t=(i / 6.0) if on else (1 - i / 6.0))
            except tk.TclError:
                return
            if i < 6:
                self.after(dur(14), lambda: frame(i + 1))

        frame(0)


class Badge(tk.Canvas):
    """胶囊标签。"""

    def __init__(self, parent, text="", bg=TITLE_BG, fill=BADGE_BG, fg=BADGE_FG,
                 font=(FONT, 9, "bold"), padx=11, pady=4):
        self._font_spec = font
        self._font = tkfont.Font(font=font)
        self._padx, self._pady = padx, pady
        self._fill, self._fg = fill, fg
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.set(text, fill, fg)

    def set(self, text, fill=None, fg=None):
        if fill:
            self._fill = fill
        if fg:
            self._fg = fg
        w = self._font.measure(text) + self._padx * 2
        h = self._font.metrics("linespace") + self._pady * 2
        self.configure(width=w, height=h)
        self.delete("all")
        round_rect(self, 0, 0, w, h, h / 2.0, fill=self._fill, outline=self._fill)
        self.create_text(w / 2.0, h / 2.0, text=text, fill=self._fg, font=self._font_spec)


class Dot(tk.Canvas):
    """状态圆点，运行中会呼吸。"""

    def __init__(self, parent, bg=CARD, size=14, color=OK):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self._size = size
        self._core = self.create_oval(1, 1, size - 1, size - 1, fill=color, outline=color)
        self._job = None
        self._t = 0.0
        self.set_color(color)

    def set_color(self, color):
        self.itemconfigure(self._core, fill=color, outline=color)

    def start_pulse(self):
        if self._job is None:
            self._t = 0.0
            self._pulse()

    def stop_pulse(self, color):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.set_color(color)

    def _pulse(self):
        self._t += 0.09
        k = (math.sin(self._t) + 1.0) / 2.0
        self.set_color(blend(OK, OK_LIGHT, 0.25 + 0.75 * k))
        self._job = self.after(60, self._pulse)


class Pill(tk.Canvas):
    """状态条右边的提示胶囊：不确定进度时三个跳动的小点，确定进度时显示百分比。"""

    def __init__(self, parent, bg=SOFT, height=26):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0)
        self._h = height
        self._text = ""
        self._value = None
        self._phase = 0.0
        self._job = None
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        w = self.winfo_width()
        h = self._h
        self.delete("all")
        if w <= 6 or not self._text:
            return
        round_rect(self, 0, 0, w, h, h / 2.0, fill=BLUE_L, outline=PILL_EDGE)
        cy = h / 2.0
        if self._value is None:
            for i in range(3):
                a = 0.28 + 0.72 * max(0.0, math.cos(self._phase - i * 0.7))
                c = mix(BLUE_L, BLUE, a)
                cx = 15 + i * 9
                self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=c, outline=c)
            self.create_text(48, cy, text=self._text, anchor="w", fill=BLUE,
                             font=(FONT, 10))
        else:
            self.create_text(15, cy, text=self._text, anchor="w", fill=BLUE,
                             font=(FONT, 10))
            self.create_text(w - 13, cy, text="%d%%" % int(round(self._value * 100)),
                             anchor="e", fill=BLUE, font=(FONT, 10, "bold"))

    def _tick(self):
        self._phase += 0.22
        if self._phase > 6.2832:
            self._phase -= 6.2832
        self._draw()
        self._job = self.after(60, self._tick)

    def show(self, text, value=None):
        self._text = text or ""
        self._value = value
        f = tkfont.Font(family=FONT, size=10)
        need = f.measure(self._text) + (92 if value is None else 82)
        self.configure(width=max(150, min(need, 470)))
        if value is None and self._job is None:
            self._phase = 0.0
            self._tick()
        elif value is not None:
            self._stop()
        self._draw()

    def _stop(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def hide(self):
        self._stop()
        self._text = ""
        self.delete("all")


def human_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % int(n))
        n /= 1024.0


class Toast(tk.Frame):
    """窗口内右下角的提示条：滑进来、停一会儿、滑出去；多个会往上叠。"""

    KINDS = {"ok": (OK, "✓"), "warn": (WARN, "!"),
             "bad": (BAD, "×"), "info": (BLUE, "i")}
    _alive = []
    W = 330
    H = 56
    GAP = 8
    RIGHT = 22
    BOTTOM = 62

    def __init__(self, master, text, kind="info", ms=3200):
        if kind not in self.KINDS:
            kind = "info"
        color, glyph = self.KINDS[kind]
        super().__init__(master, bg=CARD, highlightbackground=TOAST_EDGE,
                         highlightthickness=1)
        self._closing = False
        tk.Frame(self, bg=color, width=4).pack(side="left", fill="y")
        box = tk.Frame(self, bg=CARD)
        box.pack(side="left", fill="both", expand=True, padx=(12, 10))
        ic = tk.Canvas(box, width=24, height=24, bg=CARD, highlightthickness=0, bd=0)
        ic.create_oval(0, 0, 23, 23, fill=color, outline=color)
        ic.create_text(12, 12, text=glyph, fill="#ffffff", font=(FONT, 9, "bold"))
        ic.pack(side="left")
        tk.Label(box, text=text, bg=CARD, fg=INK, font=(FONT, 10), anchor="w",
                 justify="left", wraplength=self.W - 92).pack(side="left", padx=(10, 0))
        Toast._alive.append(self)
        self._reflow()
        self._slide_in()
        self._deadline = self.after(ms, self.close)

    def _y_for(self, idx):
        return -(self.BOTTOM + (self.H + self.GAP) * (idx + 1))

    def _reflow(self):
        idx = Toast._alive.index(self)
        target = self._y_for(idx)
        if getattr(self, "_ty", None) is None:
            self._ty = target
        self.place(relx=1.0, rely=1.0, anchor="se", x=-self.RIGHT,
                   width=self.W, height=self.H, y=target)
        if not self._closing:
            self._ty = target

    def _slide_in(self, i=0, steps=8):
        start = self._ty + 26
        end = self._ty

        def frame(k):
            if self._closing or not self.winfo_exists():
                return
            kk = k / float(steps)
            kk = 1.0 - (1.0 - kk) ** 3
            self.place_configure(y=int(start + (end - start) * kk))
            if k < steps:
                self.after(dur(14), lambda: frame(k + 1))

        frame(0)

    def close(self):
        if self._closing:
            return
        self._closing = True
        try:
            self.after_cancel(self._deadline)
        except Exception:
            pass
        self._slide_out(6)

    def _slide_out(self, i):
        if i <= 0:
            self._destroy()
            return
        y = self._ty + (6 - i) * 7
        try:
            self.place_configure(y=y)
        except Exception:
            pass
        self.after(16, lambda: self._slide_out(i - 1))

    def _destroy(self):
        if self in Toast._alive:
            Toast._alive.remove(self)
        try:
            self.destroy()
        except Exception:
            pass
        for t in Toast._alive:
            t._reflow()
            t._slide_in()


class Bar(tk.Canvas):


    """细进度条：set_fraction 定量，start_marquee 流动光带，stop 停。"""

    def __init__(self, parent, bg=CARD, height=8, color=BLUE, track=TRACK):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0)
        self._h = height
        self._color = color
        self._track = track
        self._frac = 0.0
        self._mode = "idle"
        self._pos = 0.0
        self._job = None
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        w = self.winfo_width()
        h = self._h
        self.delete("all")
        if w <= 2:
            return
        round_rect(self, 0, 0, w, h, h / 2.0, fill=self._track, outline=self._track)
        if self._mode == "determinate":
            fw = max(0.0, min(1.0, self._frac)) * w
            if fw > 2:
                round_rect(self, 0, 0, fw, h, h / 2.0, fill=self._color, outline=self._color)
        elif self._mode == "marquee":
            seg = max(40.0, w * 0.28)
            x = self._pos * (w + seg) - seg
            x1, x2 = max(0.0, x), min(float(w), x + seg)
            if x2 - x1 > 2:
                round_rect(self, x1, 0, x2, h, h / 2.0, fill=self._color, outline=self._color)

    def _tick(self):
        self._pos += 0.018
        if self._pos > 1.0:
            self._pos = 0.0
        self._draw()
        self._job = self.after(33, self._tick)

    def start_marquee(self):
        self._mode = "marquee"
        if self._job is None:
            self._pos = 0.0
            self._tick()

    def set_fraction(self, f):
        """进度值平滑过渡过去（8 帧插值）。"""
        self._stop_anim()
        self._mode = "determinate"
        f = max(0.0, min(1.0, f))
        start = self._frac

        def step(i, steps=8):
            if self._mode != "determinate":
                return
            self._frac = start + (f - start) * i / steps
            self._draw()
            if i < steps:
                self._job = self.after(16, lambda: step(i + 1, steps))
            else:
                self._job = None

        step(0)

    def _stop_anim(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def stop(self):
        self._stop_anim()
        self._mode = "idle"
        self._draw()


class Segmented(tk.Canvas):
    """分段单选：选中块会滑过去（PCL 那种）。"""

    def __init__(self, parent, options, value, command=None, bg=CARD,
                 font=(FONT, 10), padx=15, pady=7, radius=7, gap=5):
        self._font_spec = font
        self._font = tkfont.Font(font=font)
        self._opts = [(str(lab), val) for lab, val in options]
        self._value = value
        self._command = command
        self._bg = bg
        self._gap = gap
        self._radius = radius
        self._seg_w = max(self._font.measure(lab) for lab, _v in self._opts) + padx * 2
        w = self._seg_w * len(self._opts) + gap * max(0, len(self._opts) - 1)
        h = self._font.metrics("linespace") + pady * 2
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._cw, self._ch = w, h
        self._tok = 0
        self._x = self._x_of(self._index())
        self._draw()
        self.bind("<Button-1>", self._click)

    def _x_of(self, i):
        return float(i * (self._seg_w + self._gap))

    def _index(self):
        for i, (_lab, v) in enumerate(self._opts):
            if v == self._value:
                return i
        return 0

    def _draw(self):
        self.delete("all")
        round_rect(self, self._x, 0, self._x + self._seg_w, self._ch, self._radius,
                   fill=BLUE, outline=BLUE)
        span = float(self._seg_w + self._gap)
        for i, (lab, _v) in enumerate(self._opts):
            x0 = self._x_of(i)
            k = max(0.0, min(1.0, 1.0 - abs(self._x - x0) / span))
            self.create_text(x0 + self._seg_w / 2.0, self._ch / 2.0, text=lab,
                             fill=mix(DIM, "#ffffff", k), font=self._font_spec)

    def _slide(self, x1, instant=False):
        x0 = self._x
        self._tok += 1
        tok = self._tok
        if instant or abs(x1 - x0) < 1.0:
            self._x = x1
            self._draw()
            return
        steps = 10

        def frame(i):
            if tok != self._tok:
                return
            k = i / float(steps)
            k = 1.0 - (1.0 - k) ** 3
            self._x = x0 + (x1 - x0) * k
            try:
                self._draw()
            except tk.TclError:
                return
            if i < steps:
                self.after(dur(13), lambda: frame(i + 1))

        frame(1)

    def _click(self, _evt):
        step = float(self._seg_w + self._gap)
        i = int(_evt.x // step)
        i = max(0, min(len(self._opts) - 1, i))
        self._pick(self._opts[i][1])

    def _pick(self, val):
        if val == self._value:
            return
        self._value = val
        self._slide(self._x_of(self._index()))
        if self._command:
            self._command(val)

    def get(self):
        return self._value

    def set(self, val):
        if val == self._value:
            return
        self._value = val
        self._slide(self._x_of(self._index()))

    def set_instant(self, val):
        self._value = val
        self._slide(self._x_of(self._index()), instant=True)


class Sweep(tk.Canvas):
    """一条来回扫的细线：待机时是普通分隔线，忙起来变成会跑的进度线。"""

    def __init__(self, parent, width=600, height=3, bg=CARD, color=BLUE):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self._cw, self._h, self._c = width, height, color
        self._t, self._on, self._i = 0.0, False, 0
        self.bind("<Configure>", self._resize)
        self._draw()

    def _resize(self, evt):
        self._cw = evt.width
        self._draw()

    def start(self, color=None):
        if color:
            self._c = color
        if self._on:
            return
        self._on, self._i = True, 0
        self._tick()

    def stop(self):
        self._on = False
        self._draw()

    def _tick(self):
        if not self._on:
            return
        self._i = (self._i + 1) % 40
        p = self._i / 39.0
        self._t = p * 2.0 if p < 0.5 else (1.0 - p) * 2.0
        try:
            self._draw()
        except tk.TclError:
            return
        self.after(dur(26), self._tick)

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._h
        self.create_rectangle(0, 0, w, h, fill=LINE, outline=LINE)
        if self._on:
            seg = max(70.0, w * 0.26)
            x0 = (w - seg) * self._t
            self.create_rectangle(x0, 0, x0 + seg, h, fill=self._c, outline=self._c)


class Select(tk.Canvas):
    """自绘下拉选择器 —— 替掉 ttk.Combobox，原生控件会破坏整体风格。

    items 元素是 (value, note, kind)：
      value 真正取值；note 是右侧小字；kind 决定 note 颜色
      （run=正在跑 / have=已装 / net=远端）。
    """

    H = 36
    ROW = 32
    MAXROWS = 9
    MAGIC = "#010203"

    def __init__(self, parent, items=None, value=None, cmd=None, bg=CARD,
                 width=470, radius=9, placeholder="还没挑版本"):
        self._items = list(items or [])
        self._value = value
        self._cmd = cmd
        self._bg = bg
        self._cw = width
        self._radius = radius
        self._ph = placeholder
        self._hover = False
        self._pop = None
        self._pop_cv = None
        self._off = 0
        self._hi = -1
        self._bold = tkfont.Font(font=(FONT, 11, "bold"))
        self._note = tkfont.Font(font=(FONT, 9))
        super().__init__(parent, width=width, height=self.H, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", lambda e: self.toggle())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Destroy>", lambda e: self.close())
        self._draw()

    # ---------------------------------------------------------------- 主框
    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._draw()

    def _open_now(self):
        return self._pop is not None

    def _show(self):
        for it in self._items:
            if it and it[0] == self._value:
                return (it[0], it[1] if len(it) > 1 else "",
                        it[2] if len(it) > 2 else "net")
        return (self._value or ""), "", "net"

    def _note_color(self, it):
        kind = it[2] if len(it) > 2 else "net"
        if kind == "run":
            return OK
        if kind == "have":
            return BLUE
        return FAINT

    def _draw(self):
        w, h = self._cw, self.H
        self.delete("all")
        base = mix(BTN, BTN_HOVER, 1.0 if (self._hover or self._open_now()) else 0.0)
        round_rect(self, .5, .5, w - .5, h - .5, self._radius, fill=base,
                   outline=BLUE if self._open_now() else LINE)
        v, note, kind = self._show()
        if v:
            self.create_text(15, h / 2.0, text=v, anchor="w", fill=INK,
                             font=(FONT, 11, "bold"))
            if note:
                self.create_text(15 + self._bold.measure(v) + 13, h / 2.0 + 1,
                                 text=note, anchor="w",
                                 fill=self._note_color((v, note, kind)),
                                 font=(FONT, 9))
        else:
            self.create_text(15, h / 2.0, text=self._ph, anchor="w", fill=FAINT,
                             font=(FONT, 10))
        cx, cy = w - 19, h / 2.0
        self.create_polygon(cx - 4, cy - 2.5, cx + 4, cy - 2.5, cx, cy + 2.5,
                            fill=DIM, outline=DIM)

    # ---------------------------------------------------------------- 弹出
    def toggle(self):
        if self._open_now():
            self.close()
        else:
            self.open()

    def open(self):
        if not self._items or self._pop is not None:
            return
        rows = min(len(self._items), self.MAXROWS)
        h = rows * self.ROW + 4
        w = self._cw
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.H + 4
        if y + h > self.winfo_screenheight() - 12:
            up = self.winfo_rooty() - h - 4
            if up > 12:
                y = up
        self._off, self._hi = 0, -1
        pop = tk.Toplevel(self)
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        try:
            pop.attributes("-transparentcolor", self.MAGIC)
        except tk.TclError:
            pass
        pop.configure(bg=self.MAGIC)
        pop.geometry("%dx%d+%d+%d" % (w, h, x, y))
        cv = tk.Canvas(pop, width=w, height=h, bg=self.MAGIC,
                       highlightthickness=0, bd=0, cursor="hand2")
        cv.pack()
        cv.bind("<Motion>", self._pop_motion)
        cv.bind("<Button-1>", self._pop_click)
        cv.bind("<MouseWheel>", self._pop_wheel)
        cv.bind("<Escape>", lambda e: self.close())
        self._pop, self._pop_cv = pop, cv
        self._draw_pop()
        pop.update_idletasks()
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        pop.bind_all("<Button-1>", self._global_click, add="+")
        self._draw()

    def _global_click(self, evt):
        w = evt.widget
        if w is self or (self._pop_cv is not None and w is self._pop_cv):
            return
        self.close()

    def _pop_index(self, y):
        i = self._off + int((y - 2) // self.ROW)
        if 0 <= i < len(self._items) and 2 <= y <= 2 + self.MAXROWS * self.ROW:
            return i
        return -1

    def _pop_motion(self, evt):
        i = self._pop_index(evt.y)
        if i != self._hi:
            self._hi = i
            self._draw_pop()

    def _pop_click(self, evt):
        i = self._pop_index(evt.y)
        if i >= 0:
            self._pick(self._items[i][0])
        else:
            self.close()

    def _pop_wheel(self, evt):
        n = len(self._items) - self.MAXROWS
        if n <= 0:
            return
        self._off = max(0, min(n, self._off - (1 if evt.delta < 0 else -1)))
        self._hi = -1
        self._draw_pop()

    def _draw_pop(self):
        cv = self._pop_cv
        if cv is None:
            return
        cv.delete("all")
        w = self._cw
        h = cv.winfo_reqheight()
        round_rect(cv, 1, 1, w - 1, h - 1, self._radius + 2, fill=CARD, outline=LINE)
        for n in range(self._off, min(len(self._items), self._off + self.MAXROWS)):
            it = self._items[n]
            y0 = 2 + (n - self._off) * self.ROW
            sel = it[0] == self._value
            if sel or n == self._hi:
                c = BLUE_L if sel else SOFT
                round_rect(cv, 8, y0 + 2, w - 8, y0 + self.ROW - 2, 6, fill=c, outline=c)
            if sel:
                cv.create_rectangle(3, y0 + 5, 6, y0 + self.ROW - 5, fill=BLUE, outline=BLUE)
            cv.create_text(20, y0 + self.ROW / 2.0, text=it[0], anchor="w", fill=INK,
                           font=(FONT, 10, "bold"))
            note = it[1] if len(it) > 1 else ""
            if note:
                cv.create_text(w - 20, y0 + self.ROW / 2.0, text=note, anchor="e",
                               fill=self._note_color(it), font=(FONT, 9))
        extra = len(self._items) - self.MAXROWS
        if extra > 0:
            bh = max(26.0, (h - 8) * self.MAXROWS / float(len(self._items)))
            by = 4 + (h - 8 - bh) * (self._off / float(extra))
            round_rect(cv, w - 7, by, w - 3, by + bh, 2, fill=FAINT, outline=FAINT)

    # ---------------------------------------------------------------- 取值
    def _pick(self, val):
        self._value = val
        self.close()
        if self._cmd:
            self._cmd(val)

    def close(self):
        if self._pop is None:
            return
        pop = self._pop
        self._pop, self._pop_cv = None, None
        try:
            pop.unbind_all("<Button-1>")
        except tk.TclError:
            pass
        try:
            pop.grab_release()
        except tk.TclError:
            pass
        try:
            pop.destroy()
        except tk.TclError:
            pass
        self._hi = -1
        self._draw()

    def get(self):
        return self._value

    def set(self, val):
        if val != self._value:
            self._value = val
            self._draw()

    def set_items(self, items, value=None):
        self._items = list(items or [])
        if value is not None:
            self._value = value
        if self._pop is not None:
            self.close()
        self._draw()


class Ring(tk.Canvas):
    """PCL 式彩虹圆环：一圈小弧，颜色随时间流转。"""

    def __init__(self, parent, size=150, thickness=13, bg=TITLE_BG, segs=64):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self._size, self._th, self._segs = size, thickness, segs
        self._phase = 0.0
        self._job = None
        pad = thickness / 2.0 + 2
        box = (pad, pad, size - pad, size - pad)
        step = 360.0 / segs
        self._items = [self.create_arc(box, start=i * step, extent=step * 1.25, style="arc",
                                       width=thickness, outline="#444444")
                       for i in range(segs)]
        self._paint()

    def _paint(self):
        step = 360.0 / self._segs
        for i, item in enumerate(self._items):
            hue = (self._phase + i * step) % 360.0
            self.itemconfigure(item, outline=hsl_hex(hue, 0.82, 0.55))

    def start(self):
        if self._job is None:
            self._tick()

    def _tick(self):
        self._phase = (self._phase + 6.0) % 360.0
        self._paint()
        self._job = self.after(40, self._tick)

    def stop(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None


MINE_CFG = os.path.join(os.path.expanduser("~"), "dsh-launcher", "mine.json")
MINE_DEFAULT = {"size": 168, "pick_dx": 0.19, "pick_dy": 2.2, "line_y": 0.82,
                "line_w": 0.5, "anchor": [65, 162]}


def mine_config():
    cfg = dict(MINE_DEFAULT)
    try:
        import json
        with io.open(MINE_CFG, encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict):
            for k, v in got.items():
                if k in cfg:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


class MineAnim(tk.Canvas):
    """Minecraft 风格的挖掘动画：镐子一下下敲在一条蓝线上，敲到时线亮一下。"""

    N = 16
    FRAMES = 14
    LINE = "#1370b1"
    LINE_HOT = "#63b5e8"

    def __init__(self, parent, size=None, bg=TITLE_BG):
        self.cfg = mine_config()
        if size is None:
            size = float(self.cfg["size"])
        self.px = max(2, int(size / (self.N + 2)))
        self._cw = self.px * (self.N + 2)
        self._ch = int(self.px * 21)
        tk.Canvas.__init__(self, parent, width=self._cw, height=self._ch,
                           bg=bg, highlightthickness=0)
        self._on = False
        self._phase = 0
        self._tok = 0
        self._imgs = []
        self._item = None
        self._keep = None
        self._lw = max(2, int(self.px * float(self.cfg["line_w"])))
        self._ly = int(self._ch * float(self.cfg["line_y"]))
        self.create_line(self.px, self._ly, self._cw - self.px, self._ly,
                         fill=self.LINE, width=self._lw, capstyle="round", tags="line")
        self._load_pick()
        self._pick_show(0)

    def _load_pick(self):
        for i in range(self.FRAMES):
            try:
                self._imgs.append(tk.PhotoImage(file=asset_path("pick_%02d.png" % i)))
            except Exception:
                self._imgs.append(None)
        ax, ay = self.cfg["anchor"]
        self._ax = int(ax)
        self._ay = int(ay)
        self._cx = int(self._cw * float(self.cfg["pick_dx"]))
        self._cy = int(self._ly + self.px * float(self.cfg["pick_dy"]))

    def _pick_show(self, i):
        if not self._imgs:
            return
        img = self._imgs[i % len(self._imgs)]
        if img is None:
            return
        x = self._cx - self._ax
        y = self._cy - self._ay
        try:
            if self._item is None:
                self._item = self.create_image(x, y, image=img, anchor="nw")
            else:
                self.itemconfigure(self._item, image=img)
                self.coords(self._item, x, y)
            self.tag_raise(self._item)
        except tk.TclError:
            return
        self._keep = img

    def _flash(self):
        try:
            self.itemconfigure("line", fill=self.LINE_HOT, width=self._lw + 2)
            self.after(120, self._unflash)
        except tk.TclError:
            pass

    def _unflash(self):
        try:
            self.itemconfigure("line", fill=self.LINE, width=self._lw)
        except tk.TclError:
            pass

    def start(self):
        self._on = True
        self._phase = 0
        self._tok += 1
        self._tick(self._tok)

    def stop(self):
        self._on = False
        self._tok += 1

    def _tick(self, tok):
        if not self._on or tok != self._tok:
            return
        try:
            if not self.winfo_exists():
                return
            i = self._phase
            self._pick_show(i)
            if i == 8:
                self._flash()
            self._phase = (i + 1) % self.FRAMES
            self.after(46, lambda: self._tick(tok))
        except tk.TclError:
            return


class NavItem(tk.Frame):
    """左侧导航的一项。选中与悬停都走渐变过渡。"""

    def __init__(self, parent, key, label, glyph, command):
        super().__init__(parent, bg=NAV_BG, height=54)
        self.pack_propagate(False)
        self.key = key
        self._cmd = command
        self._on = False
        self._hot = False
        self._t = 0.0
        self._tok = 0
        self.icon = tk.Label(self, text=glyph, bg=NAV_BG, fg=DIM, font=(FONT, 13),
                             width=2, anchor="center")
        self.icon.pack(side="left", padx=(20, 2))
        self.text = tk.Label(self, text=label, bg=NAV_BG, fg=INK, font=(FONT, 11), anchor="w")
        self.text.pack(side="left", fill="x", expand=True, padx=(4, 0))
        for w in (self, self.icon, self.text):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
        self.configure(cursor="hand2")

    def _click(self, _evt):
        if self._cmd:
            self._cmd(self.key)

    def _enter(self, _evt):
        self._hot = True
        self._glide(self._target())

    def _leave(self, _evt):
        self._hot = False
        self._glide(self._target())

    def _target(self):
        if self._on:
            return 1.0
        return 0.42 if self._hot else 0.0

    def _paint(self, t):
        self._t = t
        bg = mix(NAV_BG, BLUE, t)
        for w in (self, self.icon, self.text):
            w.configure(bg=bg)
        self.icon.configure(fg=mix(DIM, "#ffffff", t))
        self.text.configure(fg=mix(INK, "#ffffff", t))

    def _glide(self, to):
        self._tok += 1
        tok = self._tok
        start, steps = self._t, 7

        def step(i):
            if tok != self._tok:
                return
            try:
                self._paint(start + (to - start) * i / steps)
            except tk.TclError:
                return
            if i < steps:
                self.after(dur(13), lambda: step(i + 1))

        step(1)

    def set_on(self, on):
        self._on = bool(on)
        self.text.configure(font=(FONT, 11, "bold") if on else (FONT, 11))
        self._glide(self._target())


# ---------------------------------------------------------------- 主界面

class App:
    NAVS = [("service", "服务", "▶"), ("version", "版本与更新", "⬇"),
            ("plugins", "插件体检", "☰"), ("support", "支持与反馈", "★"),
            ("settings", "设置", "⚙")]

    def __init__(self, root):
        self.root = root
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.q = queue.Queue()
        self.vcfg = C.load_config()
        self.settings = C.load_settings()
        self.cfg = self.settings
        set_anim(self.settings.get("anim", "normal"))
        self.local = {}
        self.remote = None
        self.remote_err = ""
        self.busy = set()
        self.last_status = {}
        self.rows = []
        self._n = 0
        self._last_running = None
        self._last_msg = ""
        self._ready = False
        self.load_frame = None
        self.pages = {}
        self.peak = None
        self.cur_page = "service"
        self._safe_ok = False

        root.title("PSL-ds启动器")
        root.configure(bg=PAGE_BG)
        root.minsize(980, 660)

        w, h = 1120, 780
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        h = min(h, sh - 90)
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        self.restore_win_pos()

        try:
            root.attributes("-alpha", 0.0)
        except Exception:
            pass

        self.build_main()
        self.build_loading()
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.after(80, self.pump)
        self.root.after(200, self.start_init)
        self.root.after(60, lambda: self._fade_win(0.0))

    def _on_wheel(self, ev):
        """滚轮只滚动当前页的滚动容器（设置页）；有浮层时先让浮层用。"""
        for w in self.root.winfo_children():
            if isinstance(w, Panel):
                return
        sc = getattr(self, "scroll_settings", None)
        if sc is None or self.cur_page != "settings":
            return
        try:
            n = int(-ev.delta / 120.0 * 3) or (-3 if ev.delta > 0 else 3)
            sc.scroll_by(n)
        except Exception:
            pass

    def _fade_win(self, a):
        """整窗淡入（淡到「窗口透明度」设置的那个值）。"""
        top = max(0.55, min(1.0, float(self.settings.get("alpha", 100) or 100) / 100.0))
        a = min(top, a + 0.09)
        try:
            self.root.attributes("-alpha", a)
        except Exception:
            return
        if a < top:
            self.root.after(dur(16), lambda: self._fade_win(a))

    # ------------------------------------------------------------ 加载页
    def build_loading(self):
        """底部居中的小卡片 —— 不占整页，初始化完就收走。"""
        f = tk.Frame(self.root, bg=TITLE_BG, highlightbackground=TOP_EDGE,
                     highlightthickness=1)
        f.place(relx=0.5, rely=1.0, anchor="s", y=-24, width=380, height=92)
        self.load_frame = f
        row = tk.Frame(f, bg=TITLE_BG)
        row.pack(fill="both", expand=True, padx=14, pady=12)
        self.ring = MineAnim(row, size=66, bg=TITLE_BG)
        self.ring.pack(side="left")
        col = tk.Frame(row, bg=TITLE_BG)
        col.pack(side="left", fill="both", expand=True, padx=(14, 0))
        tk.Label(col, text="PSL-ds启动器", bg=TITLE_BG, fg="#ffffff",
                 font=(FONT, 12, "bold"), anchor="w").pack(fill="x")
        self.load_text = tk.Label(col, text="正在启动中...", bg=TITLE_BG, fg=TOP_DIM,
                                  font=(FONT, 10), anchor="w")
        self.load_text.pack(fill="x", pady=(3, 0))
        self.load_bar = Bar(col, bg=TITLE_BG, height=4, color=BLUE, track=TOP_EDGE)
        self.load_bar.pack(fill="x", pady=(8, 0))
        self.load_bar.start_marquee()
        self.ring.start()
        self._anim_t0 = time.time()

    def start_init(self):
        def job():
            steps = [("检查运行环境…", self._init_env),
                     ("读取本地版本…", self._init_local),
                     ("询问远端版本…", self._init_remote),
                     ("读取峰谷配置…", self._init_peak)]
            for text, fn in steps:
                self.q.put({"kind": "load", "text": text})
                try:
                    fn()
                except Exception as e:
                    self.say("初始化「%s」出错：%s" % (text, e))
            self.q.put({"kind": "load", "text": "准备界面"})
            self.q.put({"kind": "loaded"})
        threading.Thread(target=job, daemon=True).start()

    def _init_env(self):
        self.node = C.find_node()
        self.npm = C.find_npm()
        self.st = {"running": False, "pid": None, "version": "?", "source": "",
                   "started": "", "port": C.PORT, "bin": "", "cmd": ""}
        run = C.running_version()
        if run:
            self.st.update({"running": True, "pid": run["pid"], "version": run["version"],
                            "bin": run["bin"], "started": C.pid_start_time(run["pid"]),
                            "cmd": C.pid_cmdline(run["pid"])})

    def _init_local(self):
        self.local = C.installed_versions()
        for info in self.local.values():
            if self.st.get("bin") and os.path.normcase(info["dir"]) == os.path.normcase(
                    os.path.dirname(os.path.dirname(self.st["bin"]))):
                self.st["source"] = info["source"]

    def _init_remote(self):
        self.remote, self.remote_err = C.fetch_remote()

    def _init_peak(self):
        self.peak = C.peak_state()

    def finish_loading(self):
        if self.load_frame is not None:
            self.ring.stop()
            self.load_bar.stop()
            self.load_frame.destroy()
            self.load_frame = None
        self.root.configure(bg=PAGE_BG)
        if not self.pages:
            self.build_main()
        if getattr(self, "_cover", None) is not None:
            self._cover.lift()
        self._ready = True
        self.show_status(self.st)
        self.show_peak(self.peak)
        self.show_versions()
        self.on_plugin_check()
        try:
            self.root.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        except tk.TclError:
            pass
        if self.cfg.get("auto_start_dsh") and not self.st.get("running"):
            self.root.after(700, self.do_start)
        if self.cfg.get("check_update", True) and self.update_due():
            self.root.after(1500, self.on_check_update)
        self.root.after(5000, self.tick)

    def update_due(self):
        """按「查更新」频率决定这次打开要不要去问版本。"""
        freq = str(self.cfg.get("update_freq", "每次"))
        if freq in ("", "每次"):
            return True
        span = 86400 if freq == "每天" else 7 * 86400
        try:
            last = float(self.cfg.get("last_update_check") or 0)
        except (TypeError, ValueError):
            last = 0.0
        return (time.time() - last) >= span

    # ------------------------------------------------------------ 主界面骨架
    def build_main(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("L.TCombobox", fieldbackground=FIELD, background=CARD,
                        bordercolor=LINE, arrowcolor=DIM, lightcolor=CARD, darkcolor=CARD,
                        padding=4)
        style.map("L.TCombobox", fieldbackground=[("readonly", FIELD)])
        style.configure("L.Treeview", rowheight=31, font=(FONT, 10), fieldbackground=CARD,
                        background=CARD, bordercolor=LINE, borderwidth=0)
        style.configure("L.Treeview.Heading", font=(FONT, 10, "bold"),
                        background=SEG_HOVER, foreground=DIM, relief="flat", padding=6)
        style.map("L.Treeview", background=[("selected", BLUE_L)],
                  foreground=[("selected", INK)])

        self.shell = tk.Frame(self.root, bg=PAGE_BG)
        self.shell.place(x=0, y=0, relwidth=1, relheight=1)
        self.build_header()
        mid = tk.Frame(self.shell, bg=PAGE_BG)
        mid.pack(fill="both", expand=True)
        self.build_nav(mid)
        self.build_pages(mid)
        self.build_statusbar()
        self.shell.place_configure(y=16)
        self.root.after(20, lambda: self._settle(16))

    def _settle(self, y):
        """主界面轻轻往上落位。"""
        if y <= 0 or not self.shell.winfo_exists():
            self.shell.place_configure(y=0)
            return
        self.shell.place_configure(y=y)
        self.root.after(12, lambda: self._settle(max(0, y - 3)))

    def build_header(self):
        head = tk.Frame(self.shell, bg=TITLE_BG, height=62)
        head.pack(fill="x")
        head.pack_propagate(False)
        left = tk.Frame(head, bg=TITLE_BG)
        left.pack(side="left", padx=20)
        logo = tk.Canvas(left, width=30, height=30, bg=TITLE_BG, highlightthickness=0, bd=0)
        logo.pack(side="left", pady=16)
        round_rect(logo, 0, 0, 30, 30, 8, fill=BLUE, outline=BLUE)
        logo.create_text(15, 15, text="D", fill="#ffffff", font=(FONT, 14, "bold"))
        tk.Label(left, text="PSL-ds启动器", bg=TITLE_BG, fg=TITLE_FG,
                 font=(FONT, 15, "bold")).pack(side="left", padx=(12, 0), pady=17)
        tk.Label(left, text="", bg=TITLE_BG, fg=TOP_DIM,
                 font=(FONT, 10)).pack(side="left", padx=(14, 0), pady=20)
        right = tk.Frame(head, bg=TITLE_BG)
        right.pack(side="right", padx=20)
        self.peak_badge = Badge(right, "读取...", bg=TITLE_BG, fill=BADGE_BG, fg=BADGE_FG,
                                padx=15, pady=6, font=(FONT, 10, "bold"))
        self.peak_badge.pack(side="right", pady=16)
        self.peak_next = tk.Label(right, text="", bg=TITLE_BG, fg=TOP_DIM, font=(FONT, 10))
        self.peak_next.pack(side="right", padx=(0, 12), pady=20)
        tk.Frame(self.shell, bg=BLUE, height=2).pack(fill="x")

    def build_nav(self, parent):
        nav = tk.Frame(parent, bg=NAV_BG, width=186)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        self.nav_items = {}
        tk.Frame(nav, bg=NAV_BG, height=14).pack(fill="x")
        for key, label, glyph in self.NAVS:
            it = NavItem(nav, key, label, glyph, self.on_nav)
            it.pack(fill="x")
            self.nav_items[key] = it
        self.nav_ind = tk.Frame(nav, bg=BLUE, width=4)
        self.nav_ind.place(x=0, y=14, width=4, height=54)
        tk.Frame(parent, bg=LINE, width=1).pack(side="left", fill="y")

    def build_statusbar(self):
        bar = tk.Frame(self.shell, bg=SOFT, height=44)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=LINE, height=1).pack(fill="x")
        self.status_text = tk.Label(bar, text="就绪", bg=SOFT, fg=DIM, font=(FONT, 10),
                                    anchor="w")
        self.status_text.pack(side="left", padx=20)
        self.pill = Pill(bar, bg=SOFT, height=26)
        self.pill.pack(side="right", padx=20)

    # ------------------------------------------------------------ 三个页
    def build_pages(self, parent):
        self.cfg = getattr(self, "settings", None) or C.load_settings()
        self.content = tk.Frame(parent, bg=PAGE_BG)
        self.content.pack(side="left", fill="both", expand=True)
        self.pages = {"service": self.page_service(),
                      "version": self.page_version(),
                      "plugins": self.page_plugins(),
                      "support": self.page_support(),
                      "settings": self.page_settings()}
        for p in self.pages.values():
            p.place(x=0, y=0, relwidth=1, relheight=1)
        self.pages["service"].lift()
        self.on_nav("service")
        self.root.after(150, lambda: self._ind_to("service", instant=True))

    def page_service(self):
        page = tk.Frame(self.content, bg=PAGE_BG)
        c = Card(page, "宿主服务")
        c.pack(fill="x", padx=PAGE_PAD, pady=PAGE_GAP)
        body = c.body
        top = tk.Frame(body, bg=CARD)
        top.pack(fill="x")
        line = tk.Frame(top, bg=CARD)
        line.pack(side="left")
        self.dot = Dot(line, bg=CARD, size=16, color=FAINT)
        self.dot.pack(side="left", padx=(0, 9), pady=(5, 0))
        self.status_big = tk.Label(line, text="检查中…", bg=CARD, fg=DIM,
                                   font=(FONT, 20, "bold"))
        self.status_big.pack(side="left")
        btns = tk.Frame(top, bg=CARD)
        btns.pack(side="right", anchor="n")
        self.btn_start = Btn(btns, "启动", self.on_start, "main", pady=8)
        self.btn_stop = Btn(btns, "停止", self.on_stop, "danger", pady=8)
        self.btn_restart = Btn(btns, "重启", self.on_restart, "plain", pady=8)
        self.btn_repair = Btn(btns, "修复DSH", self.on_repair, "plain", pady=8)
        for b in (self.btn_start, self.btn_stop, self.btn_restart, self.btn_repair):
            b.pack(side="left", padx=6)
        self.status_sub = tk.Label(body, text="", bg=CARD, fg=DIM, font=(FONT, 10),
                                   anchor="w", justify="left")
        self.status_sub.pack(anchor="w", pady=(10, 0))
        self.sweep = Sweep(body)
        self.sweep.pack(fill="x", pady=18)
        tk.Label(body, text="明细", bg=CARD, fg=FAINT, font=(FONT, 10, "bold")).pack(anchor="w")
        grid = tk.Frame(body, bg=CARD)
        grid.pack(fill="x", pady=(10, 0))
        grid.grid_columnconfigure(1, weight=1)
        self.detail_rows = {}
        for i, (key, label) in enumerate((("pid", "进程号"), ("port", "监听端口"),
                                          ("version", "运行版本"), ("source", "版本来源"),
                                          ("started", "启动于"), ("bin", "入口文件"),
                                          ("cmd", "命令行"))):
            tk.Label(grid, text=label, bg=CARD, fg=FAINT, font=(FONT, 10), width=9,
                     anchor="w").grid(row=i, column=0, sticky="w", pady=4)
            lab = tk.Label(grid, text="—", bg=CARD, fg=INK, font=(FONT, 10), anchor="w",
                           justify="left", wraplength=830)
            lab.grid(row=i, column=1, sticky="w", pady=3)
            self.detail_rows[key] = lab
        return page

    def page_version(self):
        page = tk.Frame(self.content, bg=PAGE_BG)
        c = Card(page, "版本与更新")
        c.pack(fill="x", padx=PAGE_PAD, pady=PAGE_GAP)
        body = c.body
        row1 = tk.Frame(body, bg=CARD)
        row1.pack(fill="x")
        tk.Label(row1, text="版本", bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="left")
        self.seg_pick = Segmented(row1, [("自动选（追最新）", "auto"), ("手动选", "manual")],
                                  self.vcfg.get("pick_mode", "auto"), self.on_mode)
        self.seg_pick.pack(side="left", padx=(10, 24))
        tk.Label(row1, text="更新", bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="left")
        self.seg_upd = Segmented(row1, [("自动更新", "auto"), ("手动更新", "manual")],
                                 self.vcfg.get("update_mode", "manual"), self.on_mode)
        self.seg_upd.pack(side="left", padx=(10, 24))
        tk.Label(row1, text="通道", bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="left")
        self.seg_chan = Segmented(row1, [("正式版", "latest"), ("含测试版", "alpha")],
                                  self.vcfg.get("channel", "latest"), self.on_mode)
        self.seg_chan.pack(side="left", padx=(10, 0))
        row2 = tk.Frame(body, bg=CARD)
        row2.pack(fill="x", pady=(16, 0))
        self.ver_box = Select(row2, [], None, self.on_pick, width=428)
        self.ver_box.pack(side="left")
        self.btn_check = Btn(row2, "检测更新", self.on_check, "plain")
        self.btn_install = Btn(row2, "安装 / 更新", self.on_install, "main")
        self.btn_run = Btn(row2, "用这个版本启动", self.on_start, "plain")
        for b in (self.btn_check, self.btn_install, self.btn_run):
            b.pack(side="left", padx=(10, 0))
        self.ver_hint = tk.Label(body, text="", bg=CARD, fg=DIM, font=(FONT, 10),
                                 anchor="w", justify="left", wraplength=950)
        self.ver_hint.pack(fill="x", pady=(14, 0))
        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", pady=(18, 0))
        tk.Label(head, text="操作记录", bg=CARD, fg=FAINT,
                 font=(FONT, 10, "bold")).pack(side="left")
        self.btn_clearlog = Btn(head, "清空", self.on_clear_log, "ghost", padx=12, pady=4,
                                font=(FONT, 10))
        self.btn_clearlog.pack(side="right")
        self.log = tk.Text(body, height=9, bg=SOFT, fg=INK, relief="flat",
                           font=(FONT, 10), wrap="word", insertbackground=INK,
                           padx=14, pady=11, highlightthickness=1, highlightbackground=LINE,
                           bd=0)
        self.log.pack(fill="x", pady=(8, 0))
        self.log.configure(state="normal")
        self.log.insert("end", "-\n")
        self.log.configure(state="disabled")
        return page

    def _avatar(self, parent, fname, name, role, pad=0):
        box = tk.Frame(parent, bg=CARD)
        box.pack(side="left", padx=(0, pad))
        img = None
        try:
            img = tk.PhotoImage(file=asset_path(fname))
        except Exception:
            img = None
        cv = tk.Canvas(box, width=88, height=88, bg=CARD, highlightthickness=0)
        cv.pack()
        if img is not None:
            cv.create_image(44, 44, image=img)
            cv.image = img
        else:
            cv.create_oval(3, 3, 85, 85, fill=BLUE_L, outline=BLUE)
            cv.create_text(44, 44, text=name[:1], fill=BLUE, font=(FONT, 26, "bold"))
        tk.Label(box, text=name, bg=CARD, fg=INK,
                 font=(FONT, 12, "bold")).pack(pady=(9, 0))
        tk.Label(box, text=role, bg=CARD, fg=FAINT, font=(FONT, 9)).pack()
        return box

    def page_support(self):
        page = tk.Frame(self.content, bg=PAGE_BG)
        c = Card(page, "支持与 bug 反馈")
        c.pack(fill="x", padx=PAGE_PAD, pady=PAGE_GAP)
        body = c.body
        tk.Label(body, text="想支持我？想反馈 bug？", bg=CARD, fg=INK,
                 font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=16)

        who = tk.Frame(body, bg=CARD)
        who.pack(fill="x")
        self._avatar(who, "author.png", "是一只小菜awa", "作者", pad=44)
        self._avatar(who, "helper.png", "deepseek", "协作者")

        row1 = tk.Frame(body, bg=CARD)
        row1.pack(fill="x", pady=(24, 0))
        Btn(row1, "⭐ 给个 Star", self.on_star, "main", padx=18, pady=8).pack(side="left")
        Btn(row1, "复制 QQ 群号", self.on_copy_qq, "plain", padx=18,
            pady=8).pack(side="left", padx=(12, 0))

        row2 = tk.Frame(body, bg=CARD)
        row2.pack(fill="x", pady=(12, 0))
        Btn(row2, "投稿 / 反馈 bug", self.on_bug, "plain", padx=18,
            pady=8).pack(side="left")
        Btn(row2, "去 B 站投个币", self.on_bili, "plain", padx=18,
            pady=8).pack(side="left", padx=(12, 0))

        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=18)
        for k, v in (("粉丝群", "QQ 1061055039"),
                     ("邮箱", "1917131844@qq.com"),
                     ("仓库", "github.com/xiaocaiawa"),
                     ("B 站", "space.bilibili.com/3546893783140938")):
            line = tk.Frame(body, bg=CARD)
            line.pack(fill="x", pady=2)
            tk.Label(line, text=k, bg=CARD, fg=FAINT, font=(FONT, 10), width=7,
                     anchor="w").pack(side="left")
            tk.Label(line, text=v, bg=CARD, fg=INK, font=(FONT, 10),
                     anchor="w").pack(side="left")
        return page

    def on_star(self):
        webbrowser.open("https://github.com/xiaocaiawa")
        self.say("已打开仓库页，点个 Star 吧")

    def on_bug(self):
        webbrowser.open("https://github.com/xiaocaiawa/dsh-phone/issues")
        self.say("已打开反馈页")

    def on_bili(self):
        webbrowser.open("https://space.bilibili.com/3546893783140938")
        self.say("已打开 B 站主页")

    def on_copy_qq(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append("1061055039")
            self.say("群号 1061055039 已复制到剪贴板")
            self.toast("QQ 群号 1061055039 已复制", "ok")
        except Exception as e:
            self.say("复制失败：%s" % e)
            self.toast("复制失败：%s" % e, "bad")

    def page_settings(self):
        page = tk.Frame(self.content, bg=PAGE_BG)
        sc = Scroll(page, bg=PAGE_BG)
        sc.pack(fill="both", expand=True)
        self.scroll_settings = sc

        def group(title):
            c = Card(sc.body, title)
            c.pack(fill="x", padx=PAGE_PAD, pady=(PAGE_GAP - 2, 0))
            b = c.body

            def row(label):
                r = tk.Frame(b, bg=CARD)
                r.pack(fill="x")
                tk.Label(r, text=label, bg=CARD, fg=INK, font=(FONT, 11),
                         width=10, anchor="w").pack(side="left")
                return r

            def note(text):
                tk.Label(b, text=text, bg=CARD, fg=FAINT, font=(FONT, 9),
                         anchor="w", justify="left", wraplength=640).pack(anchor="w",
                                                                          pady=(4, 16))
            return row, note

        # ------------------------------------------------ 外观
        row, note = group("外观")

        r = row("主题")
        self.seg_theme = Segmented(r, [("浅色", "light"), ("深色", "dark"),
                                       ("跟随系统", "system")],
                                   self.cfg.get("theme", "light"),
                                   lambda v: self.on_setting("theme", v))
        self.seg_theme.pack(side="left", padx=(10, 0))
        Btn(r, "立即重启", self.on_relaunch, "plain", padx=12,
            pady=6).pack(side="left", padx=(14, 0))
        note("界面配色。深色模式要重启启动器才完全生效（启动时读一次）")

        r = row("动画")
        self.seg_anim = Segmented(r, [("关", "off"), ("快", "fast"),
                                      ("标准", "normal"), ("慢", "slow")],
                                  self.cfg.get("anim", "normal"),
                                  lambda v: self.on_setting("anim", v))
        self.seg_anim.pack(side="left", padx=(10, 0))
        note("导航滑动、进度胶囊、卡片切换的过渡速度（立即生效）")

        r = row("窗口透明")
        self.seg_alpha = Segmented(r, [("100%", 100), ("96%", 96),
                                       ("92%", 92), ("85%", 85)],
                                   int(self.cfg.get("alpha", 100)),
                                   lambda v: self.on_setting("alpha", int(v)))
        self.seg_alpha.pack(side="left", padx=(10, 0))
        note("调低能隐约看到后面的桌面（立即生效，仅 Windows）")

        r = row("窗口置顶")
        self.seg_top = Segmented(r, [("关", "off"), ("开 总在最前", "on")],
                                 "on" if self.cfg.get("topmost", True) else "off",
                                 lambda v: self.on_setting("topmost", v == "on"))
        self.seg_top.pack(side="left", padx=(10, 0))
        note("关掉以后启动器可以被别的窗口盖住")

        r = row("兼容模式")
        self.seg_compat = Segmented(r, [("关 动画全速", "off"), ("开 省性能", "on")],
                                    "on" if self.cfg.get("compat") else "off",
                                    lambda v: self.on_setting("compat", v == "on"))
        self.seg_compat.pack(side="left", padx=(10, 0))
        note("卡的时候打开：降低动画帧率、关掉镐子动画")

        r = row("强调色")
        self.seg_accent = Segmented(r, ACCENTS, self.cfg.get("accent", "blue"),
                                    lambda v: self.on_setting("accent", v))
        self.seg_accent.pack(side="left", padx=(10, 0))
        note("整个界面的主题色：按钮、选中项、进度胶囊一起换（重启启动器后生效）")

        r = row("界面密度")
        self.seg_dens = Segmented(r, [("宽松", "normal"), ("紧凑", "compact")],
                                  self.cfg.get("density", "normal"),
                                  lambda v: self.on_setting("density", v))
        self.seg_dens.pack(side="left", padx=(10, 0))
        note("紧凑会把卡片内边距和页间距收紧，一屏多看几行（重启启动器后生效）")

        r = row("记住位置")
        self.seg_pos = Segmented(r, [("每次居中", "off"), ("记住位置", "on")],
                                 "on" if self.cfg.get("remember_pos", True) else "off",
                                 lambda v: self.on_setting("remember_pos", v == "on"))
        self.seg_pos.pack(side="left", padx=(10, 0))
        Btn(r, "忘掉", self.on_forget_pos, "plain", padx=12,
            pady=6).pack(side="left", padx=(14, 0))
        note("关掉启动器时把窗口的位置和大小记进设置，下次原样打开")

        # ------------------------------------------------ 下载
        row, note = group("下载与安装")

        r = row("下载源")
        self.seg_reg = Segmented(r, [("npmmirror 国内快", "npmmirror"), ("官方 npm", "npm")],
                                 self.cfg.get("registry", "npmmirror"),
                                 lambda v: self.on_setting("registry", v))
        self.seg_reg.pack(side="left", padx=(10, 0))
        note("下载 DSH 版本时从哪个源拉包")

        r = row("下载位置")
        self.dl_text = tk.Label(r, text="…", bg=CARD, fg=FAINT, font=(FONT, 10))
        self.dl_text.pack(side="left")
        self.refresh_dl_text()
        Btn(r, "选择…", self.on_pick_dir, "plain", padx=12,
            pady=6).pack(side="left", padx=(12, 0))
        Btn(r, "默认", self.on_dl_default, "plain", padx=12,
            pady=6).pack(side="left", padx=(8, 0))
        Btn(r, "打开", self.on_open_dl_dir, "plain", padx=12,
            pady=6).pack(side="left", padx=(8, 0))
        note("DSH 版本装到哪个文件夹（默认 ~/dsh-launcher/versions）")

        r = row("下载前")
        self.seg_askdl = Segmented(r, [("直接下", "off"), ("先问我位置", "on")],
                                   "on" if self.cfg.get("ask_dl_dir") else "off",
                                   lambda v: self.on_setting("ask_dl_dir", v == "on"))
        self.seg_askdl.pack(side="left", padx=(10, 0))
        note("开 = 每次装新版本之前都弹一次目录选择，避免默认存到 C 盘")

        r = row("装之前")
        self.seg_cknode = Segmented(r, [("不检测", "off"), ("检测 Node.js", "on")],
                                    "on" if self.cfg.get("check_node") else "off",
                                    lambda v: self.on_setting("check_node", v == "on"))
        self.seg_cknode.pack(side="left", padx=(10, 0))
        Btn(r, "现在检测", self.on_check_node, "plain", padx=12,
            pady=6).pack(side="left", padx=(14, 0))
        self.node_text = tk.Label(r, text="", bg=CARD, fg=DIM, font=(FONT, 10))
        self.node_text.pack(side="left", padx=(12, 0))
        note("没有 Node.js 就装不了 DSH —— 开的话会在下载前先拦一道")

        # ------------------------------------------------ 行为
        row, note = group("使用习惯")

        r = row("打开方式")
        self.seg_open = Segmented(r, [("本地浏览器", "browser"), ("单独窗口", "window"),
                                      ("APP 内运行", "app")],
                                  self.cfg.get("open_mode", "browser"),
                                  lambda v: self.on_setting("open_mode", v))
        self.seg_open.pack(side="left", padx=(10, 0))
        Btn(r, "立即打开", self.on_open_dsh, "main", padx=14,
            pady=6).pack(side="left", padx=(16, 0))
        note("本地浏览器 = 用默认浏览器；单独窗口 = Edge/Chrome 的无地址栏窗口；"
             "APP 内运行 = 窄窗口，像手机那样贴在屏幕右下角")

        r = row("隐藏 CMD")
        self.seg_hide = Segmented(r, [("关 显示黑窗", "off"), ("开 后台跑", "on")],
                                  "on" if self.cfg.get("hide_cmd", True) else "off",
                                  lambda v: self.on_setting("hide_cmd", v == "on"))
        self.seg_hide.pack(side="left", padx=(10, 0))
        note("开 = 启动 DSH 时不弹那个黑色命令行窗口")

        r = row("退出时")
        self.seg_exit = Segmented(r, [("留着 DSH 跑", "off"), ("停掉 DSH", "on")],
                                  "on" if self.cfg.get("stop_on_exit") else "off",
                                  lambda v: self.on_setting("stop_on_exit", v == "on"))
        self.seg_exit.pack(side="left", padx=(10, 0))
        note("关掉启动器时，要不要把 DSH 宿主也一起停掉")

        r = row("启动时")
        self.seg_chk = Segmented(r, [("关", "off"), ("查更新", "on")],
                                 "on" if self.cfg.get("check_update", True) else "off",
                                 lambda v: self.on_setting("check_update", v == "on"))
        self.seg_chk.pack(side="left", padx=(10, 0))
        note("启动器一打开就去仓库问有没有新版本（走 git，不用梯子）")

        r = row("查更新")
        self.seg_updfreq = Segmented(r, [("每次", "每次"), ("每天", "每天"), ("每周", "每周")],
                                     self.cfg.get("update_freq", "每次"),
                                     lambda v: self.on_setting("update_freq", v))
        self.seg_updfreq.pack(side="left", padx=(10, 0))
        Btn(r, "立刻查", self.on_check_update, "plain", padx=12,
            pady=6).pack(side="left", padx=(14, 0))
        note("上面那个开关打开时，按这个频率去问版本，其余时间跳过")

        r = row("提示通知")
        self.seg_toast = Segmented(r, [("关", "off"), ("右下角冒一下", "on")],
                                   "on" if self.cfg.get("toast", True) else "off",
                                   lambda v: self.on_setting("toast", v == "on"))
        self.seg_toast.pack(side="left", padx=(10, 0))
        note("操作成功 / 失败时右下角弹出的那个小胶囊，关掉就只剩底部状态栏")

        r = row("启动完")
        self.seg_autoopen = Segmented(r, [("什么都不做", "off"), ("自动打开 DSH", "on")],
                                      "on" if self.cfg.get("open_after_start") else "off",
                                      lambda v: self.on_setting("open_after_start", v == "on"))
        self.seg_autoopen.pack(side="left", padx=(10, 0))
        note("DSH 起来之后，按上面的「打开方式」自动把它打开")

        r = row("打开启动器")
        self.seg_autodsh = Segmented(r, [("只看看", "off"), ("没跑就拉起 DSH", "on")],
                                     "on" if self.cfg.get("auto_start_dsh") else "off",
                                     lambda v: self.on_setting("auto_start_dsh", v == "on"))
        self.seg_autodsh.pack(side="left", padx=(10, 0))
        note("开 = 启动器一打开，发现 DSH 没在跑就顺手启动它")

        r = row("日志行数")
        self.seg_log = Segmented(r, [("200 行", 200), ("500 行", 500), ("2000 行", 2000)],
                                 int(self.cfg.get("keep_log", 500)),
                                 lambda v: self.on_setting("keep_log", int(v)))
        self.seg_log.pack(side="left", padx=(10, 0))
        note("操作记录留多少行，多了自动丢最旧的")

        r = row("日志跟随")
        self.seg_follow = Segmented(r, [("关", "off"), ("自动滚到底", "on")],
                                    "on" if self.cfg.get("log_autoscroll", True) else "off",
                                    lambda v: self.on_setting("log_autoscroll", v == "on"))
        self.seg_follow.pack(side="left", padx=(10, 0))
        note("新日志进来时自动滚到最下面")

        r = row("开机自启")
        st, val = C.autostart_state()
        self.seg_boot = Segmented(r, [("关", "off"), ("开机就跑", "on")],
                                  "on" if st else "off",
                                  lambda v: self.on_setting("autostart", v == "on"))
        self.seg_boot.pack(side="left", padx=(10, 0))
        self.boot_text = tk.Label(r, text=("已登记" if st else "没登记"), bg=CARD,
                                  fg=DIM, font=(FONT, 10))
        self.boot_text.pack(side="left", padx=(12, 0))
        note("写进 Windows 的开机启动项（HKCU\\...\\Run），随时可以关掉")

        r = row("安全模式")
        self.seg_safe = Segmented(r, [("普通", "off"), ("安全模式", "on")],
                                  "on" if self.cfg.get("safe_mode") else "off",
                                  lambda v: self.on_setting("safe_mode", v == "on"))
        self.seg_safe.pack(side="left", padx=(10, 0))
        Btn(r, "看现状", self.on_safe_report, "plain", padx=12,
            pady=6).pack(side="left", padx=(14, 0))
        note("开 = 每次启动 DSH 之前连问三次「真的要动吗」，并跳过自动更新 / 自动修复")

        # ------------------------------------------------ 工具
        row, note = group("工具与诊断")

        r = row("错误分析")
        Btn(r, "分析一下", self.on_error_analysis, "main", padx=14,
            pady=6).pack(side="left", padx=(10, 0))
        Btn(r, "清空记录", self.on_clear_crash, "plain", padx=12,
            pady=6).pack(side="left", padx=(8, 0))
        note("翻 crash.log 和最近的失败日志，对号入座给出原因和处理办法")

        r = row("配置文件")
        Btn(r, "打开配置目录", self.on_open_cfg, "plain", padx=14,
            pady=6).pack(side="left", padx=(10, 0))
        Btn(r, "恢复默认设置", self.on_reset_settings, "danger", padx=14,
            pady=6).pack(side="left", padx=(10, 0))
        note("设置存在 ~/dsh-launcher/settings.json，动画参数在 mine.json")

        r = row("启动器更新")
        tk.Label(r, text="当前 v" + C.APP_VER, bg=CARD, fg=DIM,
                 font=(FONT, 10)).pack(side="left", padx=(10, 0))
        Btn(r, "检查更新", self.on_check_update, "plain", padx=14,
            pady=6).pack(side="left", padx=(16, 0))
        self.upd_text = tk.Label(r, text="", bg=CARD, fg=DIM, font=(FONT, 10))
        self.upd_text.pack(side="left", padx=(12, 0))
        note("走 git 查仓库的版本标签（不用梯子）")

        return page

    def show_update(self, text, ok=True):
        try:
            self.upd_text.configure(text=text, fg=(DIM if ok else BAD))
        except tk.TclError:
            return
        self.say(text)

    def on_setting(self, key, value):
        self.cfg[key] = value
        if key == "topmost":
            try:
                self.root.attributes("-topmost", bool(value))
            except tk.TclError:
                pass
        elif key == "alpha":
            self.apply_alpha(value)
        elif key == "anim":
            set_anim(value)
        elif key == "theme":
            self.toast("配色已记下，重启启动器后整体生效", "ok", 4200)
        elif key == "autostart":
            good, msg = C.set_autostart(bool(value))
            if not good:
                self.cfg["autostart"] = False
                self._set_seg("seg_boot", "off")
                self._set_label("boot_text", "改不了")
                C.save_settings(self.cfg)
                self.toast(msg, "bad", 5000)
                self.say("开机自启设置失败：%s" % msg)
                return
            self._set_label("boot_text", "已登记" if value else "没登记")
            self.toast(msg, "ok")
        elif key == "download_dir":
            C.apply_settings_to_paths(self.cfg)
            self.refresh_dl_text()
        elif key == "registry":
            C.apply_settings_to_paths(self.cfg)
        elif key == "safe_mode":
            self.toast("安全模式已开：启动 DSH 前会连问三遍" if value
                       else "已关掉安全模式", "ok" if value else "info")
        elif key in ("accent", "density"):
            self.toast("配色/密度已记下，重启启动器后整体生效", "ok", 4200)
        elif key == "remember_pos" and not value:
            self.cfg["win_pos"] = ""
            self.toast("已忘掉窗口位置，下次打开重新居中", "info")
        good, err = C.save_settings(self.cfg)
        self.say(("设置 %s = %s" % (key, value)) if good
                 else ("设置保存失败：%s" % err))
        if key not in ("theme", "safe_mode", "autostart", "accent", "density"):
            self.toast("设置已保存" if good else ("保存失败：%s" % err),
                       "ok" if good else "bad")

    def on_forget_pos(self):
        self.cfg["win_pos"] = ""
        self.cfg["remember_pos"] = False
        self._set_seg("seg_pos", "off")
        C.save_settings(self.cfg)
        self.toast("已忘掉窗口位置", "ok")

    def save_win_pos(self):
        if not self.cfg.get("remember_pos", True):
            return
        try:
            self.root.update_idletasks()
            geo = "%dx%d+%d+%d" % (self.root.winfo_width(), self.root.winfo_height(),
                                   self.root.winfo_x(), self.root.winfo_y())
        except tk.TclError:
            return
        if geo != self.cfg.get("win_pos"):
            self.cfg["win_pos"] = geo
            C.save_settings(self.cfg)

    def restore_win_pos(self):
        geo = str(self.cfg.get("win_pos") or "")
        if not self.cfg.get("remember_pos", True) or not geo:
            return False
        if not re.match(r"^\d+x\d+\+-?\d+\+-?\d+$", geo):
            return False
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w, h, x, y = (int(v) for v in re.split(r"[x+]", geo) if v != "")
        except Exception:
            return False
        # 屏幕换过 / 分辨率变过就放弃记忆，别把窗口扔到看不见的地方
        if x < -40 or y < -20 or x > sw - 120 or y > sh - 80:
            return False
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        return True

    def _set_label(self, attr, text):
        w = getattr(self, attr, None)
        try:
            if w is not None and w.winfo_exists():
                w.configure(text=text)
        except tk.TclError:
            pass

    def _set_seg(self, attr, value):
        s = getattr(self, attr, None)
        try:
            if s is not None:
                s.set(value)
        except Exception:
            pass

    def apply_alpha(self, val):
        try:
            top = max(0.55, min(1.0, float(val) / 100.0))
            self.root.attributes("-alpha", top)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 面板 / 确认框
    def show_panel(self, title, subtitle, lines, ok=True):
        """项目内报告浮层（不用系统弹窗）。"""
        try:
            for w in self.root.winfo_children():
                if isinstance(w, Panel):
                    w.close()
            Panel(self.root, title, subtitle, lines, ok)
        except Exception as e:
            self.toast("弹窗失败：%s" % e, "bad")

    def confirm_steps(self, steps, on_ok):
        """依次弹确认框，全点「继续」才执行 on_ok。"""
        seq = list(steps)

        def step(i):
            if i >= len(seq):
                on_ok()
                return
            title, text = seq[i]
            Ask(self.root, title, text, on_ok=lambda: step(i + 1),
                on_cancel=lambda: self.toast("已取消，什么都没动", "info"),
                ok_text=("继续" if i < len(seq) - 1 else "就这样做"),
                cancel_text="取消")

        step(0)

    # ------------------------------------------------------------ 设置页按钮
    def on_relaunch(self):
        """重启启动器本身。"""
        try:
            if getattr(sys, "frozen", False):
                args = [sys.executable]
            else:
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                py = pyw if os.path.isfile(pyw) else sys.executable
                args = [py, os.path.abspath(sys.argv[0])]
            subprocess.Popen(args, close_fds=True)
        except Exception as e:
            self.toast("重启失败：%s" % e, "bad")
            return
        self.say("正在重启启动器…")
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def refresh_dl_text(self):
        d = self.cfg.get("download_dir") or C.DEFAULT_VERSIONS_DIR
        self._set_label("dl_text", C.clean_display(d))

    def on_pick_dir(self):
        try:
            from tkinter import filedialog
            d = filedialog.askdirectory(
                title="DSH 版本装到哪",
                initialdir=self.cfg.get("download_dir") or C.DEFAULT_VERSIONS_DIR,
                parent=self.root)
        except Exception as e:
            self.toast("打不开目录选择：%s" % e, "bad")
            return
        if not d:
            return
        self.on_setting("download_dir", d)
        self._set_label("dl_text", C.clean_display(d))
        self.toast("下载位置改好了", "ok")

    def on_dl_default(self):
        self.on_setting("download_dir", "")
        self._set_label("dl_text", C.clean_display(C.DEFAULT_VERSIONS_DIR))
        self.toast("已改回默认位置", "ok")

    def on_open_dl_dir(self):
        d = self.cfg.get("download_dir") or C.DEFAULT_VERSIONS_DIR
        try:
            if not os.path.isdir(d):
                os.makedirs(d)
            os.startfile(d)
            self.say("已打开 " + d)
        except Exception as e:
            self.toast("打开失败：%s" % e, "bad")

    def on_check_node(self):
        if "cknode" in self.busy:
            return

        def job():
            self.say("检测 Node.js / npm…")
            ok, rows = C.check_node()
            self.q.put({"kind": "report", "rows": rows, "err": "",
                        "title": "Node.js 检测",
                        "sub": "一切就绪" if ok else "有项目没通过"})
        self.spawn(job, "cknode")

    def on_error_analysis(self):
        if "analyse" in self.busy:
            return

        def job():
            self.say("翻错误记录…")
            hits = C.analyze_errors()
            log = C.read_crash_log()
            if not hits:
                lines = ["没找到已知错误。", ""]
                if log.strip():
                    lines.append("crash.log 里还有 %d 个字，但都不在已知错误表里。" % len(log))
                    lines.append("把下面这段发给作者看看：")
                    lines.append("")
                    lines.extend(log.strip().splitlines()[-12:])
                else:
                    lines.append("crash.log 是空的 —— 启动器最近没崩过。")
                    lines.append("如果 DSH 起不来，可以先去「服务」页点「修复DSH」。")
                self.q.put({"kind": "report", "rows": [], "err": "",
                            "title": "错误分析", "sub": "没发现问题",
                            "plain": lines})
                return
            rows = []
            for _needle, why, fix, raw in hits:
                desc = fix + ("　← " + raw if raw else "")
                rows.append((why, desc, False))
            self.q.put({"kind": "report", "rows": rows, "err": "",
                        "title": "错误分析", "sub": "%d 条" % len(hits)})
        self.spawn(job, "analyse")

    def on_clear_crash(self):
        good, err = C.clear_crash_log()
        if good:
            self.say("已清空 crash.log")
            self.toast("崩溃记录已清空", "ok")
        else:
            self.say("清空失败：%s" % err)
            self.toast("清不掉：%s" % err, "bad")

    def on_safe_report(self):
        if "saferep" in self.busy:
            return

        def job():
            self.say("看看安全模式会碰到哪些地方…")
            rows = [(name, desc, True) for name, desc in C.safe_mode_report()]
            self.q.put({"kind": "report", "rows": rows, "err": "",
                        "title": "安全模式现状", "sub": "只看不改"})
        self.spawn(job, "saferep")

    def on_close(self):
        self.save_win_pos()
        if self.cfg.get("stop_on_exit") and (self.last_status or {}).get("running"):
            try:
                C.stop_server()
            except Exception:
                pass
        self.root.destroy()

    def on_open_cfg(self):
        d = os.path.dirname(C.SETTINGS_PATH)
        try:
            if not os.path.isdir(d):
                os.makedirs(d)
            os.startfile(d)
            self.say("已打开 " + d)
        except Exception as e:
            self.toast("打开目录失败：%s" % e, "bad")

    def on_reset_settings(self):
        self.cfg = dict(C.DEFAULT_SETTINGS)
        C.save_settings(self.cfg)
        C.apply_settings_to_paths(self.cfg)
        set_anim(self.cfg.get("anim", "normal"))
        self.apply_alpha(self.cfg.get("alpha", 100))
        self.refresh_dl_text()
        try:
            self.root.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        except tk.TclError:
            pass
        for seg, key, on_val in ((getattr(self, "seg_top", None), "topmost", True),
                                 (getattr(self, "seg_hide", None), "hide_cmd", True),
                                 (getattr(self, "seg_log", None), "keep_log", 500),
                                 (getattr(self, "seg_exit", None), "stop_on_exit", False),
                                 (getattr(self, "seg_chk", None), "check_update", True),
                                 (getattr(self, "seg_reg", None), "registry", "npmmirror"),
                                 (getattr(self, "seg_open", None), "open_mode", "browser"),
                                 (getattr(self, "seg_compat", None), "compat", False),
                                 (getattr(self, "seg_theme", None), "theme", "light"),
                                 (getattr(self, "seg_anim", None), "anim", "normal"),
                                 (getattr(self, "seg_alpha", None), "alpha", 100),
                                 (getattr(self, "seg_askdl", None), "ask_dl_dir", False),
                                 (getattr(self, "seg_cknode", None), "check_node", True),
                                 (getattr(self, "seg_follow", None), "log_autoscroll", True),
                                 (getattr(self, "seg_boot", None), "autostart", False),
                                 (getattr(self, "seg_safe", None), "safe_mode", False)):
            if seg is None:
                continue
            v = self.cfg.get(key, on_val)
            seg.set("on" if (isinstance(v, bool) and v) else ("off" if isinstance(v, bool) else v))
        self._set_label("boot_text", "已登记" if C.autostart_state()[0] else "没登记")
        self.toast("设置已恢复默认", "ok")
        self.say("设置已恢复默认")

    def on_open_dsh(self):
        mode = self.cfg.get("open_mode", "browser")
        good, err = C.open_dsh(mode)
        if good:
            self.say("已打开 " + C.BASE_URL)
        else:
            self.say("打开失败：" + err)
            self.toast("打开失败：" + err, "bad")

    def open_now(self):
        """按当前「打开方式」把 DSH 打开（后台线程也能调）。"""
        mode = self.cfg.get("open_mode", "browser")
        good, err = C.open_dsh(mode)
        if not good:
            self.q.put({"kind": "toast", "text": "打开失败：" + err, "level": "bad"})

    def on_check_update(self):
        self.spawn(self._do_check_update, "update")

    def _do_check_update(self):
        self.prog("检查启动器更新…")
        tag, sha, err = C.remote_tags()
        self.prog(None, None)
        self.cfg["last_update_check"] = time.time()
        C.save_settings(self.cfg)
        if err:
            self.q.put({"kind": "update", "text": "查不到：%s" % err, "ok": False})
            return
        cur = C.APP_VER
        if tag and tag.lstrip("vV") != cur:
            self.q.put({"kind": "update", "text": "有新版本 %s（当前 v%s）" % (tag, cur), "ok": True})
        elif tag:
            self.q.put({"kind": "update", "text": "已是最新（v%s）" % cur, "ok": True})
        else:
            self.q.put({"kind": "update", "text": "仓库里还没有版本标签", "ok": True})

    def page_plugins(self):
        page = tk.Frame(self.content, bg=PAGE_BG)
        c = Card(page, "插件体检")
        c.pack(fill="x", padx=PAGE_PAD, pady=PAGE_GAP)
        body = c.body
        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x")
        sums = tk.Frame(head, bg=CARD)
        sums.pack(side="left")
        self.sum_ok = tk.Label(sums, text="等待检测…", bg=CARD, fg=DIM, font=(FONT, 12, "bold"))
        self.sum_ok.pack(side="left")
        self.sum_warn = tk.Label(sums, text="", bg=CARD, fg=WARN, font=(FONT, 12, "bold"))
        self.sum_warn.pack(side="left", padx=(16, 0))
        self.sum_bad = tk.Label(sums, text="", bg=CARD, fg=BAD, font=(FONT, 12, "bold"))
        self.sum_bad.pack(side="left", padx=(16, 0))
        self.sum_note = tk.Label(sums, text="", bg=CARD, fg=FAINT, font=(FONT, 10))
        self.sum_note.pack(side="left", padx=(16, 0))
        self.btn_recheck = Btn(head, "重新检测", self.on_plugin_check, "plain", padx=14, pady=6,
                               font=(FONT, 10))
        self.btn_recheck.pack(side="right")
        self.btn_trust = Btn(head, "信任 / 取消", self.on_trust_plugin, "plain", padx=14, pady=6,
                             font=(FONT, 10))
        self.btn_trust.pack(side="right", padx=(8, 0))
        self.btn_toggle = Btn(head, "启用 / 禁用", self.on_toggle_plugin, "plain", padx=14, pady=6,
                              font=(FONT, 10))
        self.btn_toggle.pack(side="right", padx=(8, 0))
        tk.Label(head, text="",
                 bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="right", padx=(0, 16))
        cols = ("name", "level", "bundles", "spec", "where")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=12,
                                 style="L.Treeview")
        for col, txt, wdt, anc in (("name", "插件", 170, "w"), ("level", "结论", 75, "w"),
                                   ("bundles", "在打包清单", 85, "w"),
                                   ("spec", "声明", 175, "w"), ("where", "实际位置", 330, "w")):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=wdt, anchor=anc)
        for tag, col in (("ok", OK), ("warn", WARN), ("bad", BAD)):
            self.tree.tag_configure(tag, foreground=col)
        self.tree.tag_configure("odd", background=SOFT_ODD)
        self.tree.pack(fill="x", pady=(14, 12))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.detail = tk.Text(body, height=8, wrap="word", font=(FONT, 10), relief="flat",
                              bg=SOFT, fg=INK, padx=14, pady=11,
                              highlightthickness=1, highlightbackground=LINE, bd=0)
        self.detail.pack(fill="x")
        self.detail.configure(state="disabled")
        self.show_detail_lines(["(点上面任意一行，这里显示它的问题和警告)"])
        return page

    def on_nav(self, key):
        self.cur_page = key
        for k, it in self.nav_items.items():
            it.set_on(k == key)
        page = self.pages[key]
        page.lift()
        self._slide_in(page)
        self._ind_to(key)

    def _slide_in(self, page, x=30):
        """新页从右侧滑进来：位移按 ease-out 收敛（整段时长受「动画」设置控制）。"""
        if not anim_on():
            page.place_configure(x=0)
            return
        span = dur(230)
        tick = 12

        def step(elapsed):
            if not page.winfo_exists():
                return
            k = 1.0 if span <= 0 else min(1.0, elapsed / float(span))
            page.place_configure(x=int(round(x * (1 - ease(k)))))
            if k < 1.0:
                self.root.after(tick, lambda: step(elapsed + tick))

        step(0)

    def _ind_to(self, key, instant=False):
        """左侧那条蓝色指示条滑到当前项（同样是 ease-out）。"""
        it = self.nav_items.get(key)
        if it is None:
            return
        y = it.winfo_y()
        if y <= 0:
            y = 14 + list(self.nav_items).index(key) * 54
        y0 = float(self.nav_ind.winfo_y())
        if instant or not anim_on():
            self.nav_ind.place_configure(y=int(y))
            return
        span = dur(200)
        tick = 12

        def slide(elapsed):
            if not self.nav_ind.winfo_exists():
                return
            k = 1.0 if span <= 0 else min(1.0, elapsed / float(span))
            self.nav_ind.place_configure(y=int(round(y0 + (y - y0) * ease(k))))
            if k < 1.0:
                self.root.after(tick, lambda: slide(elapsed + tick))

        slide(0)

    # ------------------------------------------------------------ 线程/消息
    def say(self, text):
        self.q.put({"kind": "log", "text": text})

    def prog(self, text, value=None):
        self.q.put({"kind": "prog", "text": text, "value": value})

    def pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                k = m.get("kind")
                if k == "load":
                    if self.load_text is not None and self.load_text.winfo_exists():
                        self.load_text.configure(text=m["text"])
                elif k == "loaded":
                    self._wait_and_finish()
                elif k == "log":
                    if not self._ready:
                        continue
                    ts = datetime.now().strftime("%H:%M:%S")
                    self.log.configure(state="normal")
                    self.log.insert("end", "%s  %s\n" % (ts, m["text"]))
                    if self.cfg.get("log_autoscroll", True):
                        self.log.see("end")
                    keep = int(self.cfg.get("keep_log", 500) or 500)
                    total = int(self.log.index("end-1c").split(".")[0])
                    if total > keep + 80:
                        self.log.delete("1.0", "%d.0" % (total - keep))
                    self.log.configure(state="disabled")
                    if m["text"] and not m["text"].startswith("  "):
                        self._last_msg = m["text"]
                        self.update_status_text()
                        if getattr(self, "_cover", None) is not None:
                            self.cover_text(m["text"])
                elif k == "status":
                    self.show_status(m["status"])
                elif k == "peak":
                    self.show_peak(m["peak"])
                elif k == "versions":
                    self.local = m["local"]
                    self.remote = m["remote"]
                    self.remote_err = m["err"]
                    self.show_versions()
                elif k == "prog":
                    self.show_prog(m["text"], m.get("value"))
                elif k == "busy":
                    self.set_controls(m["name"], m["on"])
                elif k == "plugins":
                    self.show_plugins(m["summary"], m["rows"], m["err"])
                elif k == "update":
                    self.show_update(m["text"], m.get("ok", True))
                elif k == "dl_on":
                    self.download_cover(m["version"])
                elif k == "dl":
                    self.dl_progress(m["size"], m["speed"], m["elapsed"])
                elif k == "dl_off":
                    self.dl_close()
                elif k == "plugin_toggled":
                    self.toast("%s 已%s（重启 DSH 生效）" % (m["name"], "启用" if m["on"] else "禁用"),
                               "ok", 5000)
                    self.root.after(600, self.on_plugin_check)
                elif k == "plugin_trusted":
                    self.toast("%s 已%s信任" % (m["name"], "" if m["on"] else "取消"), "ok", 4200)
                elif k == "toast":
                    self.toast(m["text"], m.get("level", "info"))
                elif k == "report":
                    self.show_report(m["rows"], m["err"], m.get("title", "修复 DSH"),
                                     m.get("sub", ""), m.get("plain"))
                elif k == "cover_text":
                    self.cover_text(m["text"])
                elif k == "cover_off":
                    self.close_cover()
                elif k == "started":
                    self.refresh_status()
                    if not m.get("quiet"):
                        self.toast("DSH 已经起来了", "ok")
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def _wait_and_finish(self):
        """保证加载动画至少放 1.6 秒，别一闪而过。"""
        left = 1.6 - (time.time() - getattr(self, "_anim_t0", 0))
        if left > 0:
            self.root.after(int(left * 1000), self.finish_loading)
        else:
            self.finish_loading()

    def update_status_text(self):
        msg = self._last_msg or "就绪"
        if len(msg) > 70:
            msg = msg[:70] + "…"
        self.status_text.configure(text=msg)

    def show_prog(self, text, value):
        if text is None:
            self.pill.hide()
            self.update_status_text()
            return
        self.pill.show(text, None if value is None else float(value))
        self.status_text.configure(text=text)

    def toast(self, text, kind="info", ms=3200):
        """右下角浮一条提示。"""
        if not self.cfg.get("toast", True):
            return
        try:
            Toast(self.root, text, kind, ms)
        except Exception:
            pass

    def set_controls(self, name, idle_now):
        m = {"check": self.btn_check, "install": self.btn_install,
             "plugins": self.btn_recheck,
             "run": self.btn_run}
        btn = m.get(name)
        if btn is not None:
            btn.set_enabled(idle_now)
        self.update_service_buttons()

    def update_service_buttons(self):
        running = bool(self.last_status.get("running"))
        busy = bool(self.busy & {"start", "stop", "restart", "repair"})
        starting = "start" in self.busy
        stopping = "stop" in self.busy
        restarting = "restart" in self.busy
        repairing = "repair" in self.busy
        self.btn_start.set_busy(starting, "启动中…")
        self.btn_stop.set_busy(stopping, "停止中…")
        self.btn_restart.set_busy(restarting, "重启中…")
        self.btn_repair.set_busy(repairing, "修复中…")
        if not starting:
            self.btn_start.set_enabled(running is False and not busy)
        if not stopping:
            self.btn_stop.set_enabled(running and not busy)
        if not restarting:
            self.btn_restart.set_enabled(running and not busy)
        if not repairing:
            self.btn_repair.set_enabled(not busy)
        if hasattr(self, "sweep"):
            if starting or restarting:
                self.sweep.start(BLUE)
            elif stopping:
                self.sweep.start(DANGER_FG)
            elif repairing:
                self.sweep.start(WARN)
            else:
                self.sweep.stop()

    # ------------------------------------------------------------ 后台任务
    def spawn(self, fn, name=None):
        if name in self.busy:
            return
        if name in ("start", "restart"):
            self._cancel = False
        if name:
            self.busy.add(name)
            self.q.put({"kind": "busy", "name": name, "on": False})

        def wrap():
            try:
                fn()
            except Exception as e:
                self.say("内部错误：%s: %s" % (type(e).__name__, e))
            finally:
                if name:
                    self.busy.discard(name)
                    self.q.put({"kind": "busy", "name": name, "on": True})
        threading.Thread(target=wrap, daemon=True).start()

    def refresh_status(self):
        def job():
            st = {"running": False, "pid": None, "version": "?", "source": "",
                  "started": "", "port": C.PORT, "bin": "", "cmd": ""}
            run = C.running_version()
            if run:
                st.update({"running": True, "pid": run["pid"], "version": run["version"],
                           "bin": run["bin"], "started": C.pid_start_time(run["pid"]),
                           "cmd": C.pid_cmdline(run["pid"])})
                for info in self.local.values():
                    if os.path.normcase(info["dir"]) == os.path.normcase(run["dir"]):
                        st["source"] = info["source"]
            self.st = st
            self.q.put({"kind": "status", "status": st})
        self.spawn(job, "status")

    def refresh_peak(self):
        def job():
            self.q.put({"kind": "peak", "peak": C.peak_state()})
        self.spawn(job, "peak")

    def refresh_versions(self):
        def job():
            local = C.installed_versions()
            remote, err = C.fetch_remote()
            self.q.put({"kind": "versions", "local": local, "remote": remote, "err": err})
        self.spawn(job, "versions")

    def tick(self):
        self._n += 1
        self.refresh_status()
        if self._n % 12 == 0:
            self.refresh_peak()
        up = bool(getattr(self, "st", {}).get("running"))
        if getattr(self, "_was_up", None) is True and not up:
            self.toast("DSH 服务停了 —— 点「启动」重新拉起来", "warn", 7000)
        self._was_up = up
        self.root.after(5000, self.tick)

    def plugin_check_job(self):
        def job():
            def prog(i, n, name):
                self.prog("检查... %d/%d：%s" % (i, n, name), i / float(n))
            try:
                self.prog("检测插件…", 0.0)
                summary, rows = C.scan_plugins(progress=prog)
                self.q.put({"kind": "plugins", "summary": summary, "rows": rows, "err": ""})
            except Exception as e:
                self.q.put({"kind": "plugins", "summary": "", "rows": [],
                            "err": "%s: %s" % (type(e).__name__, e)})
            finally:
                self.prog(None)
        self.spawn(job, "plugins")

    # ------------------------------------------------------------ 显示
    def _big_text(self, text, color):
        """状态大字：文字变了才动，颜色从旧色滑到新色。"""
        if self.status_big.cget("text") == text:
            try:
                self.status_big.configure(fg=color)
            except tk.TclError:
                pass
            return
        old = str(self.status_big.cget("fg")) or DIM
        try:
            self.status_big.configure(text=text)
        except tk.TclError:
            return
        self._big_tok = getattr(self, "_big_tok", 0) + 1
        tok = self._big_tok
        steps = 9

        def frame(i):
            if tok != self._big_tok:
                return
            try:
                self.status_big.configure(fg=mix(old, color, i / float(steps)))
            except tk.TclError:
                return
            if i < steps:
                self.status_big.after(dur(18), lambda: frame(i + 1))

        frame(0)

    def show_status(self, st):
        self.last_status = st
        held = (bool(self.busy & {"start", "restart"}) and not st["running"]) or \
               ("stop" in self.busy and st["running"])
        if held:
            self.detail_rows["port"].configure(text=str(st["port"]))
            self._last_running = st["running"]
            self.update_service_buttons()
            return
        if st["running"]:
            self._big_text("运行中", OK)
            src = "（%s）" % st["source"] if st["source"] else ""
            self.status_sub.configure(
                text="PID %s · 端口 %d · 版本 %s%s · 启动于 %s"
                     % (st["pid"], st["port"], st["version"], src, st["started"] or "?"))
            self.detail_rows["pid"].configure(text=str(st["pid"]))
            self.detail_rows["version"].configure(text=st["version"])
            self.detail_rows["source"].configure(text=st["source"] or "—")
            self.detail_rows["started"].configure(text=st["started"] or "—")
            self.detail_rows["bin"].configure(text=st["bin"] or "—")
            self.detail_rows["cmd"].configure(text=st["cmd"] or "—")
            if self._last_running is not True:
                self.dot.start_pulse()
        else:
            self._big_text("已停止", BAD)
            self.status_sub.configure(text="端口 %d 无进程" % st["port"])
            for key in ("pid", "version", "source", "started", "bin", "cmd"):
                self.detail_rows[key].configure(text="—")
            if self._last_running is not False:
                self.dot.stop_pulse(BAD)
        self.detail_rows["port"].configure(text=str(st["port"]))
        self._last_running = st["running"]
        self.update_service_buttons()

    def show_peak(self, p):
        if not p["has_config"]:
            self.peak_badge.set("无峰谷配置", fill=BADGE_BG, fg=FAINT)
            self.peak_next.configure(text="")
            return
        text = "%s 当前 %s" % (p["label"], p["note"])
        if p["in_peak"]:
            self.peak_badge.set(text, fill="#4a2a10", fg="#f0b06a")
        else:
            self.peak_badge.set(text, fill="#123a20", fg="#8fd6a4")
        if p["next_cn"]:
            self.peak_next.configure(text="下次切换 %s" % p["next_cn"].strftime("%m-%d %H:%M"))
        else:
            self.peak_next.configure(text="")

    def version_items(self):
        """给 Select 用的 (版本号, 右侧小字, 颜色种类) 列表。"""
        running = (self.last_status or {}).get("version") if (self.last_status or {}).get("running") else None
        remote_versions = (self.remote or {}).get("versions") or []
        tags = (self.remote or {}).get("tags") or {}
        items = []
        for v in remote_versions[:25]:
            if v == tags.get("latest"):
                ch = "正式"
            elif v == tags.get("alpha"):
                ch = "测试"
            elif "-alpha" in v or "-beta" in v:
                ch = "测试"
            else:
                ch = "正式"
            if v == running:
                items.append((v, "%s · 正在跑" % ch, "run"))
            elif v in self.local:
                items.append((v, "%s · 已装" % ch, "have"))
            else:
                items.append((v, "%s · 未装" % ch, "net"))
        for v in C.sort_versions(self.local.keys()):
            if v not in remote_versions:
                items.append((v, "本地 · %s" % self.local[v]["source"],
                              "run" if v == running else "have"))
        return items

    @staticmethod
    def _ver_of(item):
        return (item or "").strip().split()[0] if (item or "").strip() else ""

    def show_versions(self):
        items = self.version_items()
        want, why = C.pick_version(self.vcfg, self.local, self.remote)
        running = (self.last_status or {}).get("version") if self.last_status.get("running") else None
        parts = []
        if self.remote:
            tags = self.remote.get("tags") or {}
            parts.append("远端　正式版 %s　测试版 %s" % (tags.get("latest", "?"),
                                                       tags.get("alpha", "?")))
        else:
            parts.append("远端查不到：%s" % (self.remote_err or "未知原因"))
        if running:
            if want and want != running:
                parts.append("当前跑 %s　→　目标 %s（%s）%s"
                             % (running, want, why,
                                "" if want in self.local else "，本地还没装，点「安装 / 更新」"))
            elif want:
                parts.append("版本%s" % running)
            else:
                parts.append("当前跑 %s" % running)
        elif want:
            parts.append("目标 %s（%s）%s" % (want, why, "" if want in self.local else "，本地还没装"))
        else:
            parts.append(why or "还没挑出版本")
        if self.local:
            parts.append("本地可用%s" % "、".join(C.sort_versions(self.local.keys())))
        self.ver_hint.configure(text="\n".join(parts))
        target = want
        if self.seg_pick.get() == "manual" and self.vcfg.get("selected"):
            target = self.vcfg["selected"]
        cur = self.ver_box.get()
        names = [it[0] for it in items]
        if target and cur != target and target in names:
            self.ver_box.set_items(items, target)
        elif cur not in names:
            self.ver_box.set_items(items, names[0] if names else None)
        else:
            self.ver_box.set_items(items)

    def show_plugins(self, summary, rows, err):
        self.rows = rows
        for i in self.tree.get_children():
            self.tree.delete(i)
        if err:
            self.sum_ok.configure(text="检测失败：" + err, fg=BAD)
            self.sum_warn.configure(text="")
            self.sum_bad.configure(text="")
            self.sum_note.configure(text="")
            self.toast("体检失败：" + err, "bad")
            return
        for n, r in enumerate(rows):
            label = {"ok": "正常", "warn": "有警告", "bad": "有问题"}[r["level"]]
            tags = (r["level"], "odd") if n % 2 else (r["level"],)
            self.tree.insert("", "end",
                             values=(r["name"], label, ("✔" if r["bundles"] == "在" else "×"), r["spec"], r["where"]),
                             tags=tags)
        n_bad = sum(1 for r in rows if r["level"] == "bad")
        n_warn = sum(1 for r in rows if r["level"] == "warn")
        n_ok = len(rows) - n_bad - n_warn
        self.sum_ok.configure(text="正常 %d" % n_ok, fg=OK)
        self.sum_warn.configure(text="有警告 %d" % n_warn)
        self.sum_bad.configure(text="有问题 %d" % n_bad)
        self.sum_note.configure(text="共 %d 个插件" % len(rows))
        self.show_detail_lines(summary.splitlines())
        self.toast("体检完成：正常 %d，警告 %d，有问题 %d" % (n_ok, n_warn, n_bad),
                   "bad" if n_bad else ("warn" if n_warn else "ok"))

    def show_detail_lines(self, lines):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    def on_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.rows):
            return
        r = self.rows[idx]
        lines = ["%s    %s" % (r["name"], r["spec"]), "位置：%s" % r["where"], ""]
        for title, items in (("有问题", r["bad"]), ("警告", r["warn"]), ("通过", r["ok"])):
            if items:
                lines.append("【%s】" % title)
                lines.extend("  · " + s for s in items)
                lines.append("")
        self.show_detail_lines(lines)

    # ------------------------------------------------------------ 交互
    def on_mode(self, _val=None):
        self.vcfg["pick_mode"] = self.seg_pick.get()
        self.vcfg["update_mode"] = self.seg_upd.get()
        self.vcfg["channel"] = self.seg_chan.get()
        C.save_config(self.vcfg)
        self.show_versions()

    def on_pick(self, val=None):
        v = val or self.ver_box.get()
        v = self._ver_of(v)
        if v:
            self.vcfg["selected"] = v
            if self.seg_pick.get() == "manual":
                C.save_config(self.vcfg)
        self.show_versions()

    def on_clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def on_open(self):
        webbrowser.open(C.BASE_URL)

    def on_check(self):
        def job():
            self.prog("远端版本查询中…")
            try:
                remote, err = C.fetch_remote()
                local = C.installed_versions()
                self.q.put({"kind": "versions", "local": local, "remote": remote, "err": err})
                if err:
                    self.say("❌检测失败：%s" % err)
                else:
                    tags = remote.get("tags") or {}
                    self.say("远端　正式版 %s　测试版 %s　共 %d 个版本"
                             % (tags.get("latest", "?"), tags.get("alpha", "?"),
                                len(remote.get("versions") or [])))
            finally:
                self.prog(None)
        self.spawn(job, "check")

    def _selected_plugin(self):
        sel = self.tree.selection()
        if not sel:
            self.toast("先在表格里选一个插件", "warn")
            return None
        return self.tree.item(sel[0], "values")[0]

    def on_toggle_plugin(self):
        name = self._selected_plugin()
        if not name:
            return
        on = name not in C.profile_bundles()

        def job():
            ok, err = C.set_bundle(name, on)
            if ok:
                self.q.put({"kind": "plugin_toggled", "name": name, "on": on})
            else:
                self.q.put({"kind": "toast", "text": "改不动：%s" % err, "level": "bad"})

        self.spawn(job, "plug")

    def on_trust_plugin(self):
        name = self._selected_plugin()
        if not name:
            return
        on = name not in C.trusted_list()

        def job():
            ok, err = C.set_trusted(name, on)
            if ok:
                self.q.put({"kind": "plugin_trusted", "name": name, "on": on})
            else:
                self.q.put({"kind": "toast", "text": "改不动：%s" % err, "level": "bad"})

        self.spawn(job, "plug")

    def on_plugin_check(self):
        self.plugin_check_job()

    def pre_install_checks(self):
        """装之前的两道关：先看 Node.js，再（可选）问一次下载位置。"""
        if self.cfg.get("check_node", True):
            self.say("先看看 Node.js 在不在…")
            self.root.update_idletasks()
            ok, rows = C.check_node()
            if not ok:
                self.say("❌ 没找到 Node.js / npm —— 装不了 DSH。")
                self.show_report(rows, "", "Node.js 检测", "缺了关键东西")
                return False
        if self.cfg.get("ask_dl_dir"):
            try:
                from tkinter import filedialog
                d = filedialog.askdirectory(
                    title="这次装到哪个文件夹？",
                    initialdir=self.cfg.get("download_dir") or C.DEFAULT_VERSIONS_DIR,
                    parent=self.root)
            except Exception as e:
                self.toast("打不开目录选择：%s" % e, "bad")
                return False
            if not d:
                self.toast("已取消，没有开始下载", "info")
                self.say("已取消下载")
                return False
            self.cfg["download_dir"] = d
            C.apply_settings_to_paths(self.cfg)
            C.save_settings(self.cfg)
            self.refresh_dl_text()
            self.say("这次装到 " + C.clean_display(d))
        return True

    def on_install(self):
        v = self._ver_of(self.ver_box.get())
        if not v:
            self.say("❌请选择版本")
            return
        if not self.pre_install_checks():
            return
        self.vcfg["selected"] = v
        C.save_config(self.vcfg)

        def job():
            self.say("开始安装 %s…" % v)
            self.q.put({"kind": "dl_on", "version": v})
            n = [0]

            def lg(s):
                if "http fetch" in s:
                    n[0] += 1
                    self.say("  已获取 %d 包" % n[0])
                elif "added" in s and "packages" in s:
                    self.say("  " + s)

            try:
                ok, msg = C.npm_install(v, lg, self._dl_prog)
            finally:
                self.q.put({"kind": "dl_off"})
            self.say(("完成：" if ok else "失败：") + msg)
            local = C.installed_versions()
            remote, err = C.fetch_remote()
            self.q.put({"kind": "versions", "local": local, "remote": remote, "err": err})
            self.q.put({"kind": "toast",
                        "text": ("%s 装好了" % v) if ok else ("装 %s 失败：%s" % (v, msg)),
                        "level": "ok" if ok else "bad"})
        self.spawn(job, "install")

    def _dl_prog(self, size, speed, elapsed):
        self.q.put({"kind": "dl", "size": size, "speed": speed, "elapsed": elapsed})

    def download_cover(self, version):
        """下载小卡片：贴在中下方，不盖住页面。"""
        self.dl_close(instant=True)
        W, H = 420, 118
        cv = tk.Frame(self.root, bg=TITLE_BG, highlightbackground=TOP_EDGE,
                      highlightthickness=1)
        y0 = -24
        cv.place(relx=0.5, rely=1.0, anchor="s", y=y0 + H + 30, width=W, height=H)
        box = tk.Frame(cv, bg=TITLE_BG)
        box.pack(fill="both", expand=True, padx=14, pady=11)
        top = tk.Frame(box, bg=TITLE_BG)
        top.pack(fill="x")
        tk.Label(top, text="正在下载 DSH", bg=TITLE_BG, fg="#f2f4f7",
                 font=(FONT, 11, "bold")).pack(side="left")
        tk.Label(top, text=version, bg=TITLE_BG, fg=BLUE,
                 font=(MONO, 10)).pack(side="left", padx=(8, 0))
        self.dl_pct = tk.Label(top, text="0%", bg=TITLE_BG, fg="#ffffff",
                               font=(FONT, 13, "bold"))
        self.dl_pct.pack(side="right")
        self.dl_bar = Bar(box, bg=TITLE_BG, height=6, color=BLUE, track=TOP_EDGE)
        self.dl_bar.pack(fill="x", pady=(9, 0))
        self.dl_bar.set_fraction(0.0)
        self.dl_info = tk.Label(box, text="正在连接…", bg=TITLE_BG, fg="#9aa3ad",
                                font=(FONT, 9), anchor="w")
        self.dl_info.pack(fill="x", pady=(7, 0))
        self.dl_cover = cv
        self._dl_t0 = time.time()
        self._dl_ver = version

        def slide(i=0, steps=9):
            if getattr(self, "dl_cover", None) is not cv:
                return
            k = i / float(steps)
            k = 1.0 - (1.0 - k) ** 3
            cv.place_configure(y=int(y0 + H + 30 - (H + 30) * k))
            if i < steps:
                self.root.after(dur(14), lambda: slide(i + 1, steps))

        slide()

    def dl_progress(self, size, speed, elapsed):
        cv = getattr(self, "dl_cover", None)
        if cv is None:
            return
        est = C.INSTALL_EST_BYTES
        frac = min(1.0, size / float(est)) if est else 0.0
        self.dl_pct.configure(text="%d%%" % int(frac * 100))
        self.dl_bar.set_fraction(frac)
        left = (est - size) / speed if speed > 1 else 0
        info = "已下载 %s　·　%s/s　·　已用 %s" % (
            human_bytes(size), human_bytes(speed), human_ms(int(elapsed * 1000)))
        if left > 1 and frac < 1.0:
            info += "　·　约剩 %s" % human_ms(int(left * 1000))
        self.dl_info.configure(text=info)

    def dl_close(self, instant=False):
        cv = getattr(self, "dl_cover", None)
        if cv is None:
            return
        self.dl_cover = None
        if instant:
            try:
                cv.destroy()
            except Exception:
                pass
            return
        h = max(cv.winfo_height(), 100) + 30

        def out(i=0, steps=7):
            k = i / float(steps)
            try:
                cv.place_configure(y=int(h * (k ** 2)))
            except Exception:
                return
            if i < steps:
                self.root.after(dur(14), lambda: out(i + 1, steps))
            else:
                try:
                    cv.destroy()
                except Exception:
                    pass

        out()

    def ensure_runnable(self, version):
        info = self.local.get(version)
        if info:
            return info["bin"], ""
        if self.seg_upd.get() == "auto":
            self.say("本地没有 %s，按自动更新设置先装上…" % version)
            self.prog("正在下载 %s…" % version)
            ok, msg = C.npm_install(version, lambda s: self.say("  " + s))
            self.say(("完成：" if ok else "失败：") + msg)
            self.prog(None)
            self.local = C.installed_versions()
            info = self.local.get(version)
            if info:
                return info["bin"], ""
            return "", msg
        return "", "本地没有 %s，而更新方式是「手动更新」，请先点「安装 / 更新」" % version

    def host_alive(self):
        """3080 上的宿主有没有应答（首页要登录，401 也算活着）。"""
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen("http://127.0.0.1:3080/", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            return False

    def launch_cover(self, title="正在启动 DSH"):
        return
        """PCL 式启动页：深色整页从下方升起来，宿主就绪后收回去。"""
        if getattr(self, "_cover", None) is not None:
            return
        h = self.root.winfo_height() or 780
        cv = tk.Frame(self.root, bg=TITLE_BG)
        cv.place(x=0, y=h, relwidth=1, height=h)
        box = tk.Frame(cv, bg=TITLE_BG)
        box.place(relx=0.5, rely=0.5, anchor="center")
        ring = MineAnim(box, size=150)
        ring.pack()
        tk.Label(box, text=title, bg=TITLE_BG, fg="#f2f4f7",
                 font=(FONT, 17, "bold")).pack(pady=(20, 8))
        lab = tk.Label(box, text="正在准备…", bg=TITLE_BG, fg="#9aa3ad", font=(FONT, 10))
        lab.pack()
        bar = Bar(box, bg=TITLE_BG, height=5, color=BLUE, track=TOP_EDGE)
        bar.configure(width=300)
        bar.pack(pady=(18, 0))
        cv.lift()
        self._cover = cv
        self._cover_t0 = time.time()
        self._cover_text = lab
        self._cover_bar = bar
        self._cover_ring = ring
        ring.start()
        bar.start_marquee()
        steps = 9

        def frame(i):
            if not cv.winfo_exists():
                return
            k = i / float(steps)
            k = 1.0 - (1.0 - k) ** 3
            try:
                cv.place_configure(y=int(h * (1.0 - k)))
            except tk.TclError:
                return
            if i < steps:
                self.root.after(14, lambda: frame(i + 1))

        frame(0)

    def cover_text(self, text):
        lab = getattr(self, "_cover_text", None)
        try:
            if lab is not None and lab.winfo_exists():
                lab.configure(text=text)
        except tk.TclError:
            pass

    def close_cover(self):
        cv = getattr(self, "_cover", None)
        if cv is None:
            return
        left = 1.4 - (time.time() - getattr(self, "_cover_t0", 0.0))
        if left > 0:
            self.root.after(int(left * 1000), self.close_cover)
            return
        self._cover = None
        h = self.root.winfo_height() or 780
        try:
            y0 = cv.winfo_y()
        except tk.TclError:
            return
        steps = 8

        def frame(i):
            if not cv.winfo_exists():
                return
            k = (i / float(steps)) ** 2
            try:
                cv.place_configure(y=int(y0 + (h - y0) * k))
            except tk.TclError:
                return
            if i < steps:
                self.root.after(13, lambda: frame(i + 1))
            else:
                try:
                    self._cover_ring.stop()
                except Exception:
                    pass
                try:
                    cv.destroy()
                except tk.TclError:
                    pass

        frame(0)

    def wait_host(self, limit=20):
        """等宿主在 3080 上应答，最多 limit 秒。"""
        self.say("等待宿主在 3080 上应答…")
        for _ in range(int(limit / 0.4)):
            time.sleep(0.4)
            if getattr(self, "_cancel", False):
                self.say("已取消等待")
                return False
            if self.host_alive():
                return True
        self.say("❌ 20 秒没等到宿主应答：CMD 窗口可能被关掉了，或端口被别的东西占着。点「修复DSH」看看。")
        return False

    def on_start(self):
        self.do_start()

    def do_start(self, kill_first=False):
        if self.cfg.get("safe_mode") and not self._safe_ok:
            self.confirm_steps([
                ("安全模式 · 第 1 关",
                 "这次不会自动下载 / 更新 DSH 版本 —— 只用你本地已经装好的那个。"),
                ("安全模式 · 第 2 关",
                 "不会改动插件清单（profile/package.json），也不会自动修复任何东西。"),
                ("安全模式 · 第 3 关",
                 "起不来就去「设置 → 错误分析」看原因。现在启动？"),
            ], lambda: self._start_bypass(kill_first))
            return
        self._do_start(kill_first)

    def _start_bypass(self, kill_first):
        """三层确认都过了 —— 只放行这一次，不改设置。"""
        self._safe_ok = True
        try:
            self._do_start(kill_first)
        finally:
            self._safe_ok = False

    def _do_start(self, kill_first=False):
        self._big_text("正在启动…", BLUE)
        self.sweep.start(BLUE)
        self.launch_cover("正在启动 DSH")

        def job():
            try:
                want, why = C.pick_version(self.vcfg, self.local, self.remote)
                if not want:
                    self.say("挑不出可用版本：" + (why or "未知原因"))
                    return
                if self.cfg.get("safe_mode") and want not in self.local:
                    self.say("安全模式：%s 本地还没有。先关掉安全模式，或在「版本与更新」装好它。"
                             % want)
                    return
                pids = C.listening_pids()
                if pids and not kill_first:
                    run = C.running_version() or {}
                    self.say("3080 上已有 PID %s 在跑（版本 %s）"
                             % ("、".join(str(p) for p in pids), run.get("version", "?")))
                    return
                bin_js, err = self.ensure_runnable(want)
                if not bin_js:
                    self.say(err)
                    return
                self.say("✅启动完成！")
                _, msg = C.start_server(bin_js, hide=bool(self.cfg.get("hide_cmd", True)))
                self.say(msg)
                self.wait_host()
                self.q.put({"kind": "started"})
                if self.cfg.get("open_after_start"):
                    self.q.put({"kind": "toast", "text": "DSH 起来了，正在打开…"})
                    self.open_now()
            finally:
                self.q.put({"kind": "cover_off"})

        self.spawn(job, "start")

    def on_stop(self):
        if self.busy & {"start", "restart"}:
            self._cancel = True
            self.say("已请求停止等待，稍等…")
            return

        def job():
            _, msg = C.stop_server()
            self.say(msg)
            self.q.put({"kind": "started"})
        self._big_text("正在停止…", BAD)
        self.sweep.start(DANGER_FG)
        self.spawn(job, "stop")

    # ------------------------------------------------------------ 修复
    def on_repair(self):
        self.spawn(self._do_repair, "repair")

    def _do_repair(self):
        self.prog("修复中…", None)
        try:
            rows = C.repair(log=lambda s: self.say(s))
            self.q.put({"kind": "report", "rows": rows, "err": ""})
        except Exception as e:
            self.q.put({"kind": "report", "rows": [],
                        "err": "%s: %s" % (type(e).__name__, e)})

    def show_report(self, rows, err, title="修复 DSH", sub="", plain=None):
        if err:
            self.say("❌%s失败：%s" % (title, err))
            self.toast("%s失败：%s" % (title, err), "bad")
            self.show_panel(title + " · 出问题了", sub, [str(err)], ok=False)
            return
        if plain:
            self.say("%s：%s" % (title, sub or ""))
            self.toast("%s · %s" % (title, sub) if sub else title, "warn")
            self.show_panel(title + (" · " + sub if sub else ""), "", plain, ok=False)
            return
        lines = []
        for name, desc, good in rows:
            lines.append("%s  %s：%s" % ("✅" if good else "⚠", name, desc))
        bad = [r for r in rows if not r[2]]
        head = "全部正常" if not bad else "%d 项要注意" % len(bad)
        self.say("%s结果：%s" % (title, head))
        self.toast("%s：%s" % (title, head), "ok" if not bad else "warn")
        if title.startswith("Node.js"):
            self._set_label("node_text", "正常" if not bad else "有问题")
        self.show_panel(title + " · " + head, sub, lines, ok=not bad)

    def on_restart(self):
        self._big_text("正在重启…", BLUE)
        self.sweep.start(BLUE)
        self.launch_cover("正在重启 DSH")

        def job():
            try:
                _, msg = C.stop_server()
                self.say(msg)
                want, why = C.pick_version(self.vcfg, self.local, self.remote)
                if not want:
                    self.say("挑不出可用版本：" + (why or "未知原因"))
                    return
                bin_js, err = self.ensure_runnable(want)
                if not bin_js:
                    self.say(err)
                    return
                _, msg = C.start_server(bin_js, hide=bool(self.cfg.get("hide_cmd", True)))
                self.say("用 %s 重新启动（%s）· %s" % (want, why, msg))
                self.wait_host()
                self.q.put({"kind": "started"})
            finally:
                self.q.put({"kind": "cover_off"})
        self.spawn(job, "restart")


def selftest():
    """不弹窗口，把关键判断写进 selftest.log（打包成无控制台 exe 后 print 无效）。"""
    from datetime import timezone
    lines = []

    def p(*a):
        lines.append(" ".join(str(x) for x in a))

    p("node:", C.find_node())
    p("npm :", C.find_npm())
    p("3080:", C.listening_pids(), "运行版本：", C.running_version())
    p("本地版本：", C.installed_versions())
    remote, err = C.fetch_remote()
    if err:
        p("远端查询失败：", err)
    else:
        p("远端 latest=%s alpha=%s 共 %d 个"
          % (remote["tags"].get("latest"), remote["tags"].get("alpha"), len(remote["versions"])))
        p("排序前 5：", remote["versions"][:5])
    st = C.peak_state()
    p("峰谷：", st["label"], st["note"], "| 窗口", st["windows"], "| 下次切换（北京）", st["next_cn"])
    p("UTC 现在：", datetime.now(timezone.utc))
    seen = []
    summary, rows = C.scan_plugins(progress=lambda i, n, name: seen.append("%d/%d" % (i, n)))
    bad = [r["name"] for r in rows if r["level"] == "bad"]
    warn = [r["name"] for r in rows if r["level"] == "warn"]
    p("插件：共 %d，有问题 %s，有警告 %s" % (len(rows), bad or "无", warn or "无"))
    p("进度回调收到 %d 次，最后一次 %s" % (len(seen), seen[-1] if seen else "无"))
    p(summary)

    text = "\n".join(lines)
    try:
        print(text)
    except Exception:
        pass
    try:
        os.makedirs(C.LAUNCHER_DIR, exist_ok=True)
        with open(os.path.join(C.LAUNCHER_DIR, "selftest.log"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    return text


def log_crash():
    """万一开窗就崩（无控制台看不见报错），把栈写进 crash.log。"""
    import traceback
    try:
        with open(os.path.join(C.LAUNCHER_DIR, "crash.log"), "a", encoding="utf-8") as f:
            f.write("%s\n%s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                  traceback.format_exc()))
    except Exception:
        pass


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        try:
            root = tk.Tk()
            App(root)
            root.mainloop()
        except Exception:
            log_crash()
            raise
