# -*- coding: utf-8 -*-
"""DSH 桌面悬浮窗 —— 置顶、可拖动，实时显示花费 / 调用 / 余额 / 峰谷 / 宿主状态。

数据全部来自本机文件，不联网、不需要 token：
  ~/.dsh/storages/cost-meter/ledger.json   —— 每日用量、余额、峰谷配置

用法：
    python dsh_float.py
    拖动窗口任意位置移动；右键菜单可以换透明度 / 切换置顶 / 退出。
"""

import io
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, ".dsh", "storages", "cost-meter", "ledger.json")
REFRESH_MS = 3000

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

BG = "#1d2025"
BG2 = "#262a30"
LINE = "#343941"
INK = "#eef1f5"
DIM = "#8a929c"
FAINT = "#656d77"
ACCENT = "#1370b1"
OK = "#2e9e4f"
WARN = "#d98324"
BAD = "#d64545"
PEAK_BG = "#4a2f14"
PEAK_FG = "#f0a44a"
OFF_BG = "#173a24"
OFF_FG = "#5fd08a"


def listen_pids(port=3080):
    """谁在监听这个端口（纯 netstat 解析，不依赖 psutil）。"""
    pids = set()
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             creationflags=flags, timeout=8).stdout.decode("gbk", "replace")
    except Exception:
        return pids
    key = ":%d " % port
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and key in parts[1] + " " \
                and parts[3].upper() == "LISTENING":
            if parts[4].isdigit():
                pids.add(int(parts[4]))
    return pids


def read_ledger():
    try:
        with io.open(LEDGER, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def peak_state(now=None):
    """返回 (是不是高峰, 标签)。规则同 dsh-cost-meter：周末和中国公众假期全天空闲。"""
    d = read_ledger()
    if not d:
        return None, "无峰谷配置"
    cfg = d.get("config") or {}
    if not cfg.get("peakEnabled", False):
        return False, "未启用峰谷"
    now = now or datetime.now(timezone.utc)
    days = cfg.get("peakHolidays") or []
    local = datetime.now()
    today = local.strftime("%Y-%m-%d")
    if today in days or local.weekday() >= 5:
        return False, "空闲时段 半价"
    h = now.hour
    for w in cfg.get("peakWindows") or []:
        s, e = w.get("start"), w.get("end")
        if isinstance(s, int) and isinstance(e, int) and s <= h < e:
            return True, "高峰时段 全价"
    return False, "空闲时段 半价"


def today_row(d):
    t = datetime.now().strftime("%Y-%m-%d")
    return (d.get("days") or {}).get(t) or {}


def human(n):
    n = float(n or 0)
    if n >= 1e9:
        return "%.2fB" % (n / 1e9)
    if n >= 1e6:
        return "%.2fM" % (n / 1e6)
    if n >= 1e3:
        return "%.1fK" % (n / 1e3)
    return "%d" % int(n)


class Row(tk.Frame):
    def __init__(self, master, label, value, color=INK, mono=True, size=11):
        super().__init__(master, bg=BG2)
        tk.Label(self, text=label, bg=BG2, fg=DIM, font=(FONT, 9), anchor="w",
                 width=8).pack(side="left")
        self.val = tk.Label(self, text=value, bg=BG2, fg=color,
                            font=(MONO if mono else FONT, size, "bold"), anchor="e")
        self.val.pack(side="right")

    def set(self, value, color=None):
        self.val.configure(text=value)
        if color:
            self.val.configure(fg=color)


class Float(tk.Tk):
    W = 268

    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.94)
        self.configure(bg=BG)
        w, h = self.W, 262
        sw = self.winfo_screenwidth()
        self.geometry("%dx%d+%d+%d" % (w, h, sw - w - 40, 90))
        self._dx = self._dy = 0
        self._build()
        self._menu()
        self.refresh()
        self.after(REFRESH_MS, self.loop)

    # ---------- 界面 ----------
    def _build(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(head, text="DSH", bg=BG, fg=INK, font=(FONT, 13, "bold")).pack(side="left")
        tk.Label(head, text="桌面悬浮窗", bg=BG, fg=FAINT,
                 font=(FONT, 8)).pack(side="left", padx=(6, 0), pady=(4, 0))
        close = tk.Label(head, text="\u00d7", bg=BG, fg=FAINT, font=(FONT, 12),
                         cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.destroy())

        self.badge = tk.Label(self, text="读取中", bg=PEAK_BG, fg=PEAK_FG,
                              font=(FONT, 9), padx=10, pady=2)
        self.badge.pack(anchor="w", padx=14)

        self.sub = tk.Label(self, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w")
        self.sub.pack(fill="x", padx=14, pady=(6, 8))

        tk.Frame(self, bg=LINE, height=1).pack(fill="x", padx=14)

        body = tk.Frame(self, bg=BG2)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        pad = tk.Frame(body, bg=BG2)
        pad.pack(fill="both", expand=True, padx=10, pady=8)
        self.r_cost = Row(pad, "今日花费", "—")
        self.r_cost.pack(fill="x", pady=2)
        self.r_calls = Row(pad, "今日调用", "—")
        self.r_calls.pack(fill="x", pady=2)
        self.r_tok = Row(pad, "今日 token", "—")
        self.r_tok.pack(fill="x", pady=2)
        self.r_bal = Row(pad, "余额", "—")
        self.r_bal.pack(fill="x", pady=2)

        self.foot = tk.Label(self, text="—", bg=BG, fg=FAINT, font=(FONT, 8), anchor="w")
        self.foot.pack(fill="x", padx=14, pady=(0, 10))

        for w in (self, head, self.badge, self.sub, self.foot):
            w.bind("<Button-1>", self._press)
            w.bind("<B1-Motion>", self._drag)
        for w in (body, pad):
            w.bind("<Button-1>", self._press)
            w.bind("<B1-Motion>", self._drag)

    def _menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="刷新", command=self.refresh)
        op = tk.Menu(m, tearoff=0)
        for label, a in (("100%", 1.0), ("94%（默认）", 0.94), ("80%", 0.8), ("60%", 0.6)):
            op.add_command(label=label,
                           command=lambda v=a: self.attributes("-alpha", v))
        m.add_cascade(label="透明度", menu=op)
        m.add_command(label="置顶开关",
                      command=lambda: self.attributes("-topmost",
                                                      not self.attributes("-topmost")))
        m.add_separator()
        m.add_command(label="退出", command=self.destroy)
        self.menu = m
        for w in (self, self.badge, self.sub, self.foot):
            w.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))

    # ---------- 拖动 ----------
    def _press(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        self.geometry("+%d+%d" % (e.x_root - self._dx, e.y_root - self._dy))

    # ---------- 数据 ----------
    def refresh(self):
        d = read_ledger()
        if not d:
            self.badge.configure(text="读不到账本", bg=PEAK_BG, fg=PEAK_FG)
            self.sub.configure(text=LEDGER)
            for r in (self.r_cost, self.r_calls, self.r_tok, self.r_bal):
                r.set("—", DIM)
            self.foot.configure(text="更新于 " + datetime.now().strftime("%H:%M:%S"))
            return

        cfg = d.get("config") or {}
        rate = float(cfg.get("exchangeRate") or 1.0)
        sym = cfg.get("symbol") or "¥"

        is_peak, label = peak_state()
        if is_peak:
            self.badge.configure(text=label, bg=PEAK_BG, fg=PEAK_FG)
        else:
            self.badge.configure(text=label, bg=OFF_BG, fg=OFF_FG)

        pids = listen_pids()
        ver = os.environ.get("DSH_FLOAT_VER", "")
        if pids:
            self.sub.configure(text="宿主运行中 · 端口 3080 · PID %d%s"
                                    % (sorted(pids)[0], ("  ·  " + ver) if ver else ""))
        else:
            self.sub.configure(text="宿主没在跑 · 端口 3080 空着")

        row = today_row(d)
        cost = float(row.get("cost") or 0.0) * rate
        self.r_cost.set("%s %.4f" % (sym, cost), INK)
        self.r_calls.set("%d 次" % int(row.get("calls") or 0))
        toks = float(row.get("input") or 0) + float(row.get("output") or 0) \
            + float(row.get("cacheRead") or 0)
        self.r_tok.set(human(toks) + "  缓存%s" % human(row.get("cacheRead") or 0))

        ref = d.get("balanceRef") or {}
        if ref:
            total = float(ref.get("total") or 0.0)
            used = float(ref.get("ledgerCost") or 0.0)
            left = total - used
            color = OK if left > 1 else (WARN if left > 0.3 else BAD)
            self.r_bal.set("%s %.2f / %.2f" % (sym, left, total), color)
        else:
            self.r_bal.set("未设置", DIM)

        self.foot.configure(text="更新于 " + datetime.now().strftime("%H:%M:%S")
                                 + "　·　右键菜单")

    def loop(self):
        try:
            self.refresh()
        except Exception:
            pass
        self.after(REFRESH_MS, self.loop)


def main():
    app = Float()
    if "--selftest" in sys.argv:
        app.refresh()
        print("float ok")
        app.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
