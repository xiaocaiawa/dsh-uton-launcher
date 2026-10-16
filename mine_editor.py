# -*- coding: utf-8 -*-
"""镐子位置调整器：拖滑块实时看效果，满意就点保存。"""

import io
import json
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import dsh_launcher as L

BG = "#eef1f5"
CARD = "#ffffff"
INK = "#26282b"
DIM = "#787d85"
FAINT = "#a3a8b0"
BLUE = "#1370b1"
OK = "#2e9e4f"
BAD = "#d64545"

ITEMS = [
    ("size", "镐子大小", 60.0, 320.0, 0.5),
    ("pick_dx", "镐子左右", 0.0, 1.0, 0.005),
    ("pick_dy", "镐子上下", -2.0, 8.0, 0.05),
    ("line_y", "蓝线高度", 0.2, 1.0, 0.005),
    ("line_w", "蓝线粗细", 0.2, 2.0, 0.02),
]

ORIG = dict(L.MINE_DEFAULT)


def fmt(v):
    return ("%.2f" % v) if abs(v) < 10 else ("%.0f" % v)


class Editor:
    def __init__(self, root):
        self.root = root
        root.title("镐子位置调整器")
        root.configure(bg=BG)
        root.geometry("780x580+420+130")
        root.minsize(700, 520)
        self.cfg = L.mine_config()

        head = tk.Frame(root, bg="#23262b", height=54)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="镐子位置调整器", bg="#23262b", fg="#ffffff",
                 font=(L.FONT, 13, "bold")).pack(side="left", padx=16)
        tk.Label(head, text="拖滑块 → 看预览 → 点保存", bg="#23262b",
                 fg="#9aa3ad", font=(L.FONT, 9)).pack(side="right", padx=16)

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        self.stage = tk.Frame(body, bg=L.TITLE_BG, height=280)
        self.stage.pack(fill="x")
        self.stage.pack_propagate(False)
        self.holder = tk.Frame(self.stage, bg=L.TITLE_BG)
        self.holder.place(relx=0.5, rely=0.5, anchor="center")

        panel = tk.Frame(body, bg=CARD)
        panel.pack(fill="x", pady=(12, 0))
        self.scales = {}
        for key, label, lo, hi, step in ITEMS:
            row = tk.Frame(panel, bg=CARD)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=label, bg=CARD, fg=INK, width=7, anchor="w",
                     font=(L.FONT, 10)).pack(side="left")
            val = tk.Label(row, text=fmt(float(self.cfg[key])), bg=CARD, fg=BLUE,
                           width=7, anchor="w", font=(L.MONO, 10))
            val.pack(side="right")
            sc = tk.Scale(row, from_=lo, to=hi, resolution=step, orient="horizontal",
                          bg=CARD, fg=INK, troughcolor=BG, highlightthickness=0, bd=0,
                          activebackground=BLUE, length=520, sliderrelief="flat",
                          font=(L.FONT, 8),
                          command=lambda v, k=key: self.on_move(k, v))
            sc.set(float(self.cfg[key]))
            sc.pack(side="left", fill="x", expand=True, padx=(6, 6))
            self.scales[key] = (sc, val)

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        tk.Button(btns, text="保存", command=self.save, bg=BLUE, fg="#ffffff",
                  activebackground="#0e5b90", activeforeground="#ffffff",
                  relief="flat", padx=22, pady=5,
                  font=(L.FONT, 10, "bold")).pack(side="left")
        tk.Button(btns, text="还原默认", command=self.reset, bg="#ffffff", fg=INK,
                  relief="flat", padx=16, pady=5,
                  font=(L.FONT, 10)).pack(side="left", padx=8)
        tk.Button(btns, text="重开预览", command=self.rebuild, bg="#ffffff", fg=INK,
                  relief="flat", padx=16, pady=5,
                  font=(L.FONT, 10)).pack(side="left")
        self.note = tk.Label(btns, text="改完点保存，启动器下次打开就生效",
                             bg=BG, fg=DIM, font=(L.FONT, 9))
        self.note.pack(side="right")

        self.anim = None
        self.rebuild()

    def rebuild(self):
        for w in self.holder.winfo_children():
            w.destroy()
        L.MINE_DEFAULT.update(self.cfg)
        self.anim = L.MineAnim(self.holder, bg=L.TITLE_BG)
        self.anim.pack()
        self.anim.start()

    def apply(self):
        a = self.anim
        if a is None:
            return
        cfg = dict(self.cfg)
        a.cfg = cfg
        a._lw = max(2, int(a.px * float(cfg["line_w"])))
        a._ly = int(a._ch * float(cfg["line_y"]))
        try:
            a.itemconfigure("line", width=a._lw)
            a.coords("line", a.px, a._ly, a._cw - a.px, a._ly)
        except tk.TclError:
            pass
        a._cx = int(a._cw * float(cfg["pick_dx"]))
        a._cy = int(a._ly + a.px * float(cfg["pick_dy"]))

    def on_move(self, key, v):
        try:
            val = float(v)
        except (TypeError, ValueError):
            return
        self.cfg[key] = val
        rc = self.scales.get(key)
        if rc:
            rc[1].configure(text=fmt(val))
        if key == "size":
            self.rebuild()
        else:
            self.apply()

    def save(self):
        try:
            io.open(L.MINE_CFG, "w", encoding="utf-8").write(
                json.dumps(self.cfg, ensure_ascii=False, indent=2))
            self.note.configure(text="已保存，启动器下次打开生效", fg=OK)
        except Exception as e:
            self.note.configure(text="保存失败：%s" % e, fg=BAD)

    def reset(self):
        self.cfg = dict(ORIG)
        for key, rc in self.scales.items():
            rc[0].set(float(self.cfg[key]))
            rc[1].configure(text=fmt(float(self.cfg[key])))
        self.note.configure(text="已还原成默认值，点保存才写入", fg=DIM)
        self.rebuild()


def main():
    root = tk.Tk()
    Editor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
