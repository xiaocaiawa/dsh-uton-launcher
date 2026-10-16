# -*- coding: utf-8 -*-
"""DSH HUD 桌面悬浮窗 —— 复刻 DSH 网页里那张状态卡，置顶、可拖动。

数据源（本机文件，不联网、不要 token）：
  ~/.dsh/storages/session_projcache/sessions/session-*.json
      record.rows 里每个字段都是 {ver, seq, val}：
        sessionStats     turns / steps / openStep / decodeTokens / decodeMs
        modelSelection   lastUsed.provider / model / reasoningEffort
        costUsage        totals.cost / model
        contextPressure  surfaceTokens / contextWindow
        turnOutline      turns[] 每轮的 prompt / response（用来画格子）
        subagentCatalog  head.values[] 子代理清单
        title            会话标题
        permissions      preset

用法：
    python dsh_float.py
    拖窗口任意位置移动；右键菜单换透明度 / 开关置顶 / 退出。
"""

import glob
import io
import json
import os
import tkinter as tk
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
SESS_DIR = os.path.join(HOME, ".dsh", "storages", "session_projcache", "sessions")
LEDGER = os.path.join(HOME, ".dsh", "storages", "cost-meter", "ledger.json")
REFRESH_MS = 2000

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

BG = "#1b1e23"
BG2 = "#23262b"
LINE = "#33383f"
INK = "#eef1f5"
DIM = "#8b929b"
FAINT = "#61686f"
ACCENT = "#1370b1"
PURPLE = "#8a63d2"
PURPLE_D = "#4b3a72"
PURPLE_G = "#6b7280"
OK = "#2e9e4f"
WARN = "#d98324"
BAD = "#d64545"
PEAK_BG = "#4a2f14"
PEAK_FG = "#f0a44a"
OFF_BG = "#173a24"
OFF_FG = "#5fd08a"


def newest_session():
    """最近被写过的会话文件。"""
    try:
        files = glob.glob(os.path.join(SESS_DIR, "session-*.json"))
    except Exception:
        return None
    if not files:
        return None
    best = max(files, key=lambda f: os.path.getmtime(f))
    try:
        with io.open(best, encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except Exception:
        return None


def rows_of(data):
    if not data:
        return {}
    rec = data.get("record") or {}
    return rec.get("rows") or {}


def val(rows, key, default=None):
    item = rows.get(key)
    if not item:
        return default
    return item.get("val", default)


def human_ms(ms):
    ms = int(ms or 0)
    s = ms // 1000
    if s < 60:
        return "%d 秒" % s
    m, s = divmod(s, 60)
    if m < 60:
        return "%d 分 %d 秒" % (m, s)
    h, m = divmod(m, 60)
    return "%d 时 %d 分" % (h, m)


def human_tokens(n):
    n = float(n or 0)
    if n >= 1e9:
        return "%.2fB" % (n / 1e9)
    if n >= 1e6:
        return "%.2fM" % (n / 1e6)
    if n >= 1e3:
        return "%.1fK" % (n / 1e3)
    return "%d" % int(n)


def peak_state():
    try:
        with io.open(LEDGER, encoding="utf-8") as fh:
            cfg = (json.load(fh) or {}).get("config") or {}
    except Exception:
        return None, "无峰谷配置"
    if not cfg.get("peakEnabled", False):
        return False, "未启用峰谷"
    now = datetime.now(timezone.utc)
    local = datetime.now()
    if local.strftime("%Y-%m-%d") in (cfg.get("peakHolidays") or []) \
            or local.weekday() >= 5:
        return False, "空闲时段 半价"
    for w in cfg.get("peakWindows") or []:
        s, e = w.get("start"), w.get("end")
        if isinstance(s, int) and isinstance(e, int) and s <= now.hour < e:
            return True, "高峰时段 全价"
    return False, "空闲时段 半价"


class Float(tk.Tk):
    W = 300
    H = 268
    GRID = 26          # 一排画多少个格子

    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.configure(bg=BG)
        sw = self.winfo_screenwidth()
        self.geometry("%dx%d+%d+%d" % (self.W, self.H, sw - self.W - 40, 90))
        self._dx = self._dy = 0
        self._build()
        self._menu()
        self.refresh()
        self.after(REFRESH_MS, self._loop)

    # ---------------- 界面 ----------------
    def _build(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=14, pady=(11, 5))
        tk.Label(head, text="DSH", bg=BG, fg=ACCENT,
                 font=(FONT, 12, "bold")).pack(side="left")
        self.title_lb = tk.Label(head, text="", bg=BG, fg=DIM, font=(FONT, 9))
        self.title_lb.pack(side="left", padx=(7, 0), pady=(3, 0))
        close = tk.Label(head, text="\u00d7", bg=BG, fg=FAINT,
                         font=(FONT, 12), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.destroy())

        model = tk.Frame(self, bg=BG)
        model.pack(fill="x", padx=14)
        self.model_lb = tk.Label(model, text="—", bg=BG, fg=INK,
                                 font=(FONT, 13, "bold"), anchor="w")
        self.model_lb.pack(side="left")
        self.effort_lb = tk.Label(model, text="", bg=BG2, fg="#b9a6ea",
                                  font=(FONT, 9), padx=8, pady=1)
        self.effort_lb.pack(side="left", padx=(8, 0))

        self.badge = tk.Label(self, text="读取中", bg=PEAK_BG, fg=PEAK_FG,
                              font=(FONT, 9), padx=9, pady=1)
        self.badge.pack(anchor="w", padx=14, pady=(7, 0))

        self.l1 = tk.Label(self, text="", bg=BG, fg=INK, font=(FONT, 10),
                           anchor="w")
        self.l1.pack(fill="x", padx=14, pady=(8, 0))
        self.l2 = tk.Label(self, text="", bg=BG, fg=DIM, font=(FONT, 9),
                           anchor="w")
        self.l2.pack(fill="x", padx=14, pady=(3, 0))

        box = tk.Frame(self, bg=BG2)
        box.pack(fill="both", expand=True, padx=8, pady=(9, 8))
        inner = tk.Frame(box, bg=BG2)
        inner.pack(fill="x", padx=10, pady=(9, 4))
        self.grid_cv = tk.Canvas(inner, bg=BG2, height=26,
                                 highlightthickness=0, bd=0)
        self.grid_cv.pack(fill="x")
        self.ctx_lb = tk.Label(inner, text="", bg=BG2, fg=DIM, font=(FONT, 9),
                               anchor="w")
        self.ctx_lb.pack(fill="x", pady=(5, 0))
        self.cost_lb = tk.Label(inner, text="", bg=BG2, fg=DIM, font=(FONT, 9),
                                anchor="w")
        self.cost_lb.pack(fill="x", pady=(2, 0))

        self.foot = tk.Label(self, text="", bg=BG, fg=FAINT, font=(FONT, 8),
                             anchor="w")
        self.foot.pack(fill="x", padx=14, pady=(0, 9))

        for w in (self, head, model, self.badge, self.l1, self.l2, self.foot,
                  box, inner, self.grid_cv, self.ctx_lb, self.cost_lb,
                  self.title_lb, self.model_lb, self.effort_lb):
            w.bind("<Button-1>", self._press)
            w.bind("<B1-Motion>", self._drag)

    def _menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="刷新", command=self.refresh)
        op = tk.Menu(m, tearoff=0)
        for label, a in (("100%", 1.0), ("95%（默认）", 0.95), ("80%", 0.8),
                         ("60%", 0.6)):
            op.add_command(label=label,
                           command=lambda v=a: self.attributes("-alpha", v))
        m.add_cascade(label="透明度", menu=op)
        m.add_command(label="置顶开关",
                      command=lambda: self.attributes(
                          "-topmost", not self.attributes("-topmost")))
        m.add_separator()
        m.add_command(label="退出", command=self.destroy)
        self.menu = m
        for w in (self, self.badge, self.l1, self.l2, self.foot, self.title_lb):
            w.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))

    def _press(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        self.geometry("+%d+%d" % (e.x_root - self._dx, e.y_root - self._dy))

    # ---------------- 数据 ----------------
    def refresh(self):
        rows = rows_of(newest_session())
        if not rows:
            self.title_lb.configure(text="没找到会话")
            self.l1.configure(text="读不到 session_projcache")
            self.l2.configure(text=SESS_DIR)
            self.foot.configure(text="更新于 " + datetime.now().strftime("%H:%M:%S"))
            return

        stats = val(rows, "sessionStats") or {}
        sel = (val(rows, "modelSelection") or {}).get("lastUsed") or {}
        cost = val(rows, "costUsage") or {}
        press = val(rows, "contextPressure") or {}
        outline = (val(rows, "turnOutline") or {}).get("turns") or []
        catalog = val(rows, "subagentCatalog") or {}
        title = val(rows, "title") or ""
        perm = val(rows, "permissions") or {}

        model = sel.get("model") or cost.get("model") or "—"
        effort = sel.get("reasoningEffort") or ""
        self.model_lb.configure(text=str(model))
        self.effort_lb.configure(text=effort.upper() if effort else "")
        if not effort:
            self.effort_lb.pack_forget()
        self.title_lb.configure(text=str(title)[:16])

        is_peak, label = peak_state()
        self.badge.configure(text=label, bg=PEAK_BG if is_peak else OFF_BG,
                             fg=PEAK_FG if is_peak else OFF_FG)

        open_step = stats.get("openStep") or {}
        meta = val(rows, "sessionListMetadata") or {}
        start = open_step.get("startTime") or meta.get("lastPromptAt")
        if start:
            used = int(datetime.now().timestamp() * 1000) - int(start)
            cur = "本次 %s" % human_ms(used)
        else:
            cur = "本次 —"
        turns = stats.get("turns") or 0
        steps = stats.get("steps") or 0
        self.l1.configure(text="%s　·　本会话 %d 轮 %d 步" % (cur, turns, steps))

        subs = ((catalog.get("head") or {}).get("values")) or []
        dec_ms = stats.get("decodeMs") or 0
        dec_tok = stats.get("decodeTokens") or 0
        speed = (dec_tok / (dec_ms / 1000.0)) if dec_ms else 0
        pending = stats.get("pendingCalls") or {}
        pmap = {"danger-full-access": "完全权限",
                "workspace-write": "工作区可写",
                "read-only": "只读",
                "never": "不询问"}
        self.l2.configure(text="子代理 %d　·　%.1f tok/s　·　%s"
                               % (len(subs), speed,
                                  pmap.get(perm.get("preset"), perm.get("preset") or "—")))

        # 上下文压力
        used_t = press.get("pressureTokens") or press.get("surfaceTokens") or 0
        win = press.get("contextWindow") or 0
        pct = (used_t / win * 100.0) if win else 0
        self.ctx_lb.configure(text="上下文 %s / %s　%.0f%%"
                                   % (human_tokens(used_t), human_tokens(win), pct))

        # 花费（本次会话，已经按定价算过）
        total_cost = ((cost.get("totals") or {}).get("cost")) or 0
        self.cost_lb.configure(text="本会话 $%.4f" % total_cost)

        self._draw_grid(outline, open_step)

        self.foot.configure(text="%s　·　右键菜单"
                                 % datetime.now().strftime("%H:%M:%S"))

    def _draw_grid(self, turns, open_step):
        cv = self.grid_cv
        cv.delete("all")
        w = max(cv.winfo_width(), self.W - 60)
        n = self.GRID
        gap = 2
        cell = max(4, (w - gap * (n - 1)) // n)
        cur_turn = open_step.get("turn") or 0
        tail = turns[-n:]
        if not cur_turn and tail:
            cur_turn = tail[-1].get("turn")
        xs = []
        for i, t in enumerate(tail):
            x = i * (cell + gap)
            tn = t.get("turn")
            if tn == cur_turn:
                color = "#c9a5ff"
            else:
                color = PURPLE
            cv.create_rectangle(x, 4, x + cell, 4 + cell, fill=color,
                                outline=color)
            xs.append(x)
        # 还没铺满的部分留空槽
        for i in range(len(tail), n):
            x = i * (cell + gap)
            cv.create_rectangle(x, 4, x + cell, 4 + cell, fill=PURPLE_D,
                                outline=PURPLE_D)
        cv.configure(height=cell + 8)

    def _loop(self):
        try:
            self.refresh()
        except Exception:
            pass
        self.after(REFRESH_MS, self._loop)


def main():
    import sys
    app = Float()
    if "--selftest" in sys.argv:
        app.refresh()
        print("float ok")
        app.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
