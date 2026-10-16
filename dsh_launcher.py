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

BLUE = "#1370b1"        # PCL 主题色
BLUE_D = "#0e5b90"      # 按下
BLUE_L = "#e9f4fc"      # 选中底
TITLE_BG = "#23262b"    # 标题栏 / 加载页底
TITLE_FG = "#ffffff"
NAV_BG = "#ffffff"
PAGE_BG = "#eef1f5"     # 内容区底
CARD = "#ffffff"
SHADOW = "#e6eaf0"      # 卡片投影
LINE = "#e6eaef"
INK = "#26282b"
DIM = "#787d85"
FAINT = "#a3a8b0"
OK = "#2e9e4f"
OK_LIGHT = "#8fd6a4"
WARN = "#d98324"
BAD = "#d64545"
TRACK = "#e6eaef"
FONT = "Microsoft YaHei UI"
MONO = "Consolas"


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


class Card(tk.Frame):
    """圆角白卡片（带一点投影）。内容放进 .body。"""

    def __init__(self, parent, title="", accent=BLUE, pad=22, radius=14):
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


class Btn(tk.Canvas):
    """圆角按钮。用 set_enabled / set_text / set_kind，别用 configure(state=...)。"""

    KINDS = {
        "plain":   ("#ffffff", INK, "#d8dee6", "#f2f5f9"),
        "main":    (BLUE, "#ffffff", BLUE, BLUE_D),
        "danger":  ("#fdeaea", "#b73a3a", "#f6d5d5", "#f9dede"),
        "ghost":   (CARD, BLUE, CARD, BLUE_L),
        "seg_off": (CARD, DIM, "#e2e7ee", "#f5f7fa"),
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
        if not self._enabled:
            fill, fg, outline = "#f4f6f8", "#b9bec6", "#eaeef3"
        elif self._kind != "seg_on":
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
        self.create_text(self._cw / 2.0, self._ch / 2.0 + d, text=self._text, fill=fg,
                         font=self._font_spec)

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
                self.after(24, lambda: frame(i + 1))

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
                self.after(14, lambda: frame(i + 1))

        frame(0)


class Badge(tk.Canvas):
    """胶囊标签。"""

    def __init__(self, parent, text="", bg=TITLE_BG, fill="#333333", fg="#cccccc",
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

    def __init__(self, parent, bg="#fafbfc", height=26):
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
        round_rect(self, 0, 0, w, h, h / 2.0, fill=BLUE_L, outline="#d5e6f6")
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
        super().__init__(master, bg=CARD, highlightbackground="#e3e8ef",
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
                self.after(14, lambda: frame(k + 1))

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
                self.after(13, lambda: frame(i + 1))

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
                self.after(13, lambda: step(i + 1))

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
        self.q = queue.Queue()
        self.cfg = C.load_config()
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

        root.title("PSL-ds启动器")
        root.configure(bg=PAGE_BG)
        root.minsize(980, 660)

        w, h = 1120, 780
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        h = min(h, sh - 90)
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))

        try:
            root.attributes("-alpha", 0.0)
        except Exception:
            pass

        self.build_main()
        self.build_loading()
        self.root.after(80, self.pump)
        self.root.after(200, self.start_init)
        self.root.after(60, lambda: self._fade_win(0.0))

    def _fade_win(self, a):
        """整窗淡入。"""
        a = min(1.0, a + 0.09)
        try:
            self.root.attributes("-alpha", a)
        except Exception:
            return
        if a < 1.0:
            self.root.after(16, lambda: self._fade_win(a))

    # ------------------------------------------------------------ 加载页
    def build_loading(self):
        """底部居中的小卡片 —— 不占整页，初始化完就收走。"""
        f = tk.Frame(self.root, bg=TITLE_BG, highlightbackground="#3a3f47",
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
        self.load_text = tk.Label(col, text="正在启动中...", bg=TITLE_BG, fg="#9aa0a8",
                                  font=(FONT, 10), anchor="w")
        self.load_text.pack(fill="x", pady=(3, 0))
        self.load_bar = Bar(col, bg=TITLE_BG, height=4, color=BLUE, track="#3a3f47")
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
        self.root.after(5000, self.tick)

    # ------------------------------------------------------------ 主界面骨架
    def build_main(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("L.TCombobox", fieldbackground="#fafafa", background=CARD,
                        bordercolor=LINE, arrowcolor=DIM, lightcolor=CARD, darkcolor=CARD,
                        padding=4)
        style.map("L.TCombobox", fieldbackground=[("readonly", "#fafafa")])
        style.configure("L.Treeview", rowheight=31, font=(FONT, 10), fieldbackground=CARD,
                        background=CARD, bordercolor=LINE, borderwidth=0)
        style.configure("L.Treeview.Heading", font=(FONT, 10, "bold"),
                        background="#f5f7fa", foreground=DIM, relief="flat", padding=6)
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
        tk.Label(left, text="", bg=TITLE_BG, fg="#8b9099",
                 font=(FONT, 10)).pack(side="left", padx=(14, 0), pady=20)
        right = tk.Frame(head, bg=TITLE_BG)
        right.pack(side="right", padx=20)
        self.peak_badge = Badge(right, "读取...", bg=TITLE_BG, fill="#333333", fg="#cccccc",
                                padx=15, pady=6, font=(FONT, 10, "bold"))
        self.peak_badge.pack(side="right", pady=16)
        self.peak_next = tk.Label(right, text="", bg=TITLE_BG, fg="#8b9099", font=(FONT, 10))
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
        bar = tk.Frame(self.shell, bg="#fafbfc", height=44)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=LINE, height=1).pack(fill="x")
        self.status_text = tk.Label(bar, text="就绪", bg="#fafbfc", fg=DIM, font=(FONT, 10),
                                    anchor="w")
        self.status_text.pack(side="left", padx=20)
        self.pill = Pill(bar, bg="#fafbfc", height=26)
        self.pill.pack(side="right", padx=20)

    # ------------------------------------------------------------ 三个页
    def build_pages(self, parent):
        self.cfg = C.load_settings()
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
        c.pack(fill="x", padx=20, pady=18)
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
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=18)
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
        c.pack(fill="x", padx=20, pady=18)
        body = c.body
        row1 = tk.Frame(body, bg=CARD)
        row1.pack(fill="x")
        tk.Label(row1, text="版本", bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="left")
        self.seg_pick = Segmented(row1, [("自动选（追最新）", "auto"), ("手动选", "manual")],
                                  self.cfg.get("pick_mode", "auto"), self.on_mode)
        self.seg_pick.pack(side="left", padx=(10, 24))
        tk.Label(row1, text="更新", bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="left")
        self.seg_upd = Segmented(row1, [("自动更新", "auto"), ("手动更新", "manual")],
                                 self.cfg.get("update_mode", "manual"), self.on_mode)
        self.seg_upd.pack(side="left", padx=(10, 24))
        tk.Label(row1, text="通道", bg=CARD, fg=FAINT, font=(FONT, 10)).pack(side="left")
        self.seg_chan = Segmented(row1, [("正式版", "latest"), ("含测试版", "alpha")],
                                  self.cfg.get("channel", "latest"), self.on_mode)
        self.seg_chan.pack(side="left", padx=(10, 0))
        row2 = tk.Frame(body, bg=CARD)
        row2.pack(fill="x", pady=(16, 0))
        self.ver_box = ttk.Combobox(row2, width=40, font=(FONT, 10), state="readonly",
                                    style="L.TCombobox")
        self.ver_box.pack(side="left", ipady=3)
        self.ver_box.bind("<<ComboboxSelected>>", self.on_pick)
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
        self.log = tk.Text(body, height=9, bg="#fafbfc", fg="#333333", relief="flat",
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
        c.pack(fill="x", padx=20, pady=18)
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
        c = Card(page, "设置")
        c.pack(fill="x", padx=20, pady=18)
        body = c.body

        def row(label):
            r = tk.Frame(body, bg=CARD)
            r.pack(fill="x")
            tk.Label(r, text=label, bg=CARD, fg=INK, font=(FONT, 11),
                     width=10, anchor="w").pack(side="left")
            return r

        def note(text):
            tk.Label(body, text=text, bg=CARD, fg=FAINT,
                     font=(FONT, 9)).pack(anchor="w", pady=(4, 16))

        r = row("下载源")
        self.seg_reg = Segmented(r, [("npmmirror 国内快", "npmmirror"), ("官方 npm", "npm")],
                                 self.cfg.get("registry", "npmmirror"),
                                 lambda v: self.on_setting("registry", v))
        self.seg_reg.pack(side="left", padx=(10, 0))
        note("下载 DSH 版本时从哪个源拉包")

        r = row("打开方式")
        self.seg_open = Segmented(r, [("本地浏览器", "browser"), ("单独窗口", "window"),
                                      ("APP 内运行", "app")],
                                  self.cfg.get("open_mode", "browser"),
                                  lambda v: self.on_setting("open_mode", v))
        self.seg_open.pack(side="left", padx=(10, 0))
        note("点「打开网页」时怎么打开")

        r = row("兼容模式")
        self.seg_compat = Segmented(r, [("关 动画全速", "off"), ("开 省性能", "on")],
                                    "on" if self.cfg.get("compat") else "off",
                                    lambda v: self.on_setting("compat", v == "on"))
        self.seg_compat.pack(side="left", padx=(10, 0))
        note("卡的时候打开：降低动画帧率、关掉镰子动画")

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
        good, err = C.save_settings(self.cfg)
        self.say(("设置 %s = %s" % (key, value)) if good
                 else ("设置保存失败：%s" % err))
        self.toast("设置已保存" if good else ("保存失败：%s" % err),
                   "ok" if good else "bad")

    def on_check_update(self):
        self.spawn(self._do_check_update, "update")

    def _do_check_update(self):
        self.q.put({"kind": "status", "text": "检查启动器更新…"})
        tag, sha, err = C.remote_tags()
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
        c.pack(fill="x", padx=20, pady=18)
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
        self.tree.tag_configure("odd", background="#fafbfd")
        self.tree.pack(fill="x", pady=(14, 12))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.detail = tk.Text(body, height=8, wrap="word", font=(FONT, 10), relief="flat",
                              bg="#fafbfc", fg=INK, padx=14, pady=11,
                              highlightthickness=1, highlightbackground=LINE, bd=0)
        self.detail.pack(fill="x")
        self.detail.configure(state="disabled")
        self.show_detail_lines(["(点上面任意一行，这里显示它的问题和警告)"])
        return page

    def on_nav(self, key):
        for k, it in self.nav_items.items():
            it.set_on(k == key)
        page = self.pages[key]
        page.lift()
        self._slide_in(page)
        self._ind_to(key)

    def _slide_in(self, page, x=34):
        """新页从右侧轻轻滑进来（旧页在下面被逐步盖住）。"""

        def step(v):
            if not page.winfo_exists():
                return
            v = 0.0 if v <= 1 else v * 0.68
            page.place_configure(x=v)
            if v > 0:
                self.root.after(13, lambda: step(v))

        step(x)

    def _ind_to(self, key, instant=False):
        """左侧那条蓝色指示条滑到当前项。"""
        it = self.nav_items.get(key)
        if it is None:
            return
        y = it.winfo_y()
        if y <= 0:
            y = 14 + list(self.nav_items).index(key) * 54
        if instant:
            self.nav_ind.place_configure(y=y)
            return

        def slide(cur, target):
            if not self.nav_ind.winfo_exists():
                return
            d = target - cur
            if abs(d) <= 1.5:
                self.nav_ind.place_configure(y=int(target))
                return
            cur = cur + d * 0.42
            self.nav_ind.place_configure(y=int(cur))
            self.root.after(12, lambda: slide(cur, target))

        slide(float(self.nav_ind.winfo_y()), float(y))

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
                    self.log.see("end")
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
                    self.show_report(m["rows"], m["err"])
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
        try:
            Toast(self.root, text, kind, ms)
        except Exception:
            pass

    def set_controls(self, name, idle_now):
        m = {"check": self.btn_check, "install": self.btn_install,
             "start": self.btn_start, "plugins": self.btn_recheck,
             "run": self.btn_run, "stop": self.btn_stop, "restart": self.btn_restart,
             "repair": self.btn_repair}
        btn = m.get(name)
        if btn is not None:
            btn.set_enabled(idle_now)
        self.update_service_buttons()

    def update_service_buttons(self):
        running = bool(self.last_status.get("running"))
        busy = bool(self.busy & {"start", "stop", "restart", "repair"})
        self.btn_start.set_enabled(running is False and not busy)
        self.btn_stop.set_enabled(bool(self.busy & {"start", "restart"}) or (running and not busy))
        self.btn_restart.set_enabled(running and not busy)

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
    def show_status(self, st):
        self.last_status = st
        if st["running"]:
            self.status_big.configure(text="运行中", fg=OK)
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
            self.status_big.configure(text="已停止", fg=BAD)
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
            self.peak_badge.set("无峰谷配置", fill="#333333", fg="#9a9a9a")
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

    def combo_values(self):
        vals = []
        remote_versions = (self.remote or {}).get("versions") or []
        tags = (self.remote or {}).get("tags") or {}
        for v in remote_versions[:25]:
            if v == tags.get("latest"):
                ch = "正式"
            elif v == tags.get("alpha"):
                ch = "测试"
            elif "-alpha" in v or "-beta" in v:
                ch = "测试"
            else:
                ch = "正式"
            vals.append("%s    [%s版%s]" % (v, ch, "已装" if v in self.local else "未装"))
        for v in C.sort_versions(self.local.keys()):
            if v not in remote_versions:
                vals.append("%s    [本地 · %s]" % (v, self.local[v]["source"]))
        return vals

    @staticmethod
    def _ver_of(item):
        return (item or "").strip().split()[0] if (item or "").strip() else ""

    def show_versions(self):
        self.ver_box.configure(values=self.combo_values())
        want, why = C.pick_version(self.cfg, self.local, self.remote)
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
        cur = self._ver_of(self.ver_box.get())
        target = want
        if self.seg_pick.get() == "manual" and self.cfg.get("selected"):
            target = self.cfg["selected"]
        if target and cur != target:
            for item in self.ver_box.cget("values"):
                if self._ver_of(item) == target:
                    self.ver_box.set(item)
                    break
        elif not cur and self.ver_box.cget("values"):
            self.ver_box.set(self.ver_box.cget("values")[0])

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
        self.cfg["pick_mode"] = self.seg_pick.get()
        self.cfg["update_mode"] = self.seg_upd.get()
        self.cfg["channel"] = self.seg_chan.get()
        C.save_config(self.cfg)
        self.show_versions()

    def on_pick(self, _evt):
        v = self._ver_of(self.ver_box.get())
        if v:
            self.cfg["selected"] = v
            if self.seg_pick.get() == "manual":
                C.save_config(self.cfg)
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

    def on_install(self):
        v = self._ver_of(self.ver_box.get())
        if not v:
            self.say("❌请选择版本")
            return
        self.cfg["selected"] = v
        C.save_config(self.cfg)

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
        cv = tk.Frame(self.root, bg=TITLE_BG, highlightbackground="#3a3f47",
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
        self.dl_bar = Bar(box, bg=TITLE_BG, height=6, color=BLUE, track="#3a3f47")
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
                self.root.after(14, lambda: slide(i + 1, steps))

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
                self.root.after(14, lambda: out(i + 1, steps))
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
        bar = Bar(box, bg=TITLE_BG, height=5, color=BLUE, track="#3a3f47")
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
        self.launch_cover("正在启动 DSH")

        def job():
            try:
                want, why = C.pick_version(self.cfg, self.local, self.remote)
                if not want:
                    self.say("挑不出可用版本：" + (why or "未知原因"))
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
                _, msg = C.start_server(bin_js)
                self.say(msg)
                self.wait_host()
                self.q.put({"kind": "started"})
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

    def show_report(self, rows, err):
        if err:
            self.say("❌修复失败：%s" % err)
            self.toast("修复失败：" + err, "bad")
            messagebox.showerror("修复 DSH", "修复失败：\n\n%s" % err, parent=self.root)
            return
        lines = []
        for name, desc, good in rows:
            lines.append("%s  %s：%s" % ("✅" if good else "⚠", name, desc))
        bad = [r for r in rows if not r[2]]
        head = "全部正常" if not bad else "%d 项要注意" % len(bad)
        self.say("修复结果：%s" % head)
        self.toast("修复完成：" + head, "ok" if not bad else "warn")
        messagebox.showinfo("修复 DSH · %s" % head, "\n".join(lines), parent=self.root)

    def on_restart(self):
        self.launch_cover("正在重启 DSH")

        def job():
            try:
                _, msg = C.stop_server()
                self.say(msg)
                want, why = C.pick_version(self.cfg, self.local, self.remote)
                if not want:
                    self.say("挑不出可用版本：" + (why or "未知原因"))
                    return
                bin_js, err = self.ensure_runnable(want)
                if not bin_js:
                    self.say(err)
                    return
                _, msg = C.start_server(bin_js)
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
