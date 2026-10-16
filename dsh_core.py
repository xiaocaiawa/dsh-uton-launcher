# -*- coding: utf-8 -*-
"""DSH 启动器 —— 核心逻辑（无界面）

管三件事：
  1. DSH 本体的版本：本地装了哪些、远端有哪些、选中哪个来跑
  2. 3080 上那个宿主进程：谁在跑、什么版本、怎么起、怎么停
  3. 峰谷时段：现在算高峰还是空闲（直接读 dsh-cost-meter 的账本配置，
     和计费插件用同一份窗口/假日表，不自己另编一套）

另外附带插件体检的检测逻辑（原程序 C:\\Users\\xiaocai\\dsh-plugin-check\\plugin_check.py）。
"""

import io
import json
import os
import re
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 路径与常量

HOME = os.path.expanduser("~")
DSH_HOME = os.path.join(HOME, ".dsh")
PROFILE_DIR = os.path.join(DSH_HOME, "profiles", "web")
PROFILE_PKG = os.path.join(PROFILE_DIR, "package.json")
PROFILE_NM = os.path.join(PROFILE_DIR, "node_modules")
LEDGER = os.path.join(DSH_HOME, "storages", "cost-meter", "ledger.json")

LAUNCHER_DIR = os.path.join(HOME, "dsh-launcher")
VERSIONS_DIR = os.path.join(LAUNCHER_DIR, "versions")
CONFIG_PATH = os.path.join(LAUNCHER_DIR, "config.json")

NPM_CACHE_NPX = os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm-cache", "_npx")

PORT = 3080
BASE_URL = "http://127.0.0.1:%d" % PORT
REGISTRY = "https://registry.npmmirror.com"
PKG = "@deepseek-ai/dsh"

NODE_CANDIDATES = [
    r"D:\NODEjsmiao\node.exe",
    os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "node.exe"),
]
NPM_CANDIDATES = [
    r"D:\NODEjsmiao\npm.cmd",
    os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "npm.cmd"),
]

CN_TZ = timezone(timedelta(hours=8))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


# ---------------------------------------------------------------- 小工具

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"__error__": str(e)}


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, ""
    except Exception as e:
        return False, str(e)


def find_first(cands):
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def find_node():
    return find_first(NODE_CANDIDATES)


def find_npm():
    return find_first(NPM_CANDIDATES)


def run(args, timeout=20, cwd=None):
    """跑一条命令，返回 (returncode, 输出文字)。不弹窗。"""
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd,
                           creationflags=NO_WINDOW)
        out = (p.stdout or b"") + (p.stderr or b"")
        try:
            text = out.decode("utf-8", errors="replace")
        except Exception:
            text = str(out)
        return p.returncode, text
    except subprocess.TimeoutExpired:
        return -1, "(超时 %ss)" % timeout
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------- 宿主进程

def listening_pids(port=PORT):
    """3080 上正在 LISTENING 的进程号集合。"""
    rc, out = run(["netstat", "-ano"], timeout=15)
    if rc != 0:
        return set()
    pids = set()
    needle = ":%d" % port
    for line in out.splitlines():
        s = line.strip()
        if "LISTENING" not in s.upper():
            continue
        parts = s.split()
        if len(parts) < 4:
            continue
        if not any(p.endswith(needle) for p in parts[1:3]):
            continue
        if parts[-1].isdigit():
            pids.add(int(parts[-1]))
    return pids


def pid_alive(pid):
    rc, out = run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], timeout=15)
    return rc == 0 and str(pid) in out


def pid_start_time(pid):
    """进程启动时刻（本地时间字符串），查不到返回空。"""
    rc, out = run(["wmic", "process", "where", "ProcessId=%d" % pid,
                   "get", "CreationDate", "/value"], timeout=20)
    m = re.search(r"CreationDate=(\d{14})", out)
    if not m:
        return ""
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").strftime("%m-%d %H:%M:%S")
    except Exception:
        return ""


def pid_cmdline(pid):
    rc, out = run(["wmic", "process", "where", "ProcessId=%d" % pid,
                   "get", "CommandLine", "/value"], timeout=20)
    for line in out.splitlines():
        if line.startswith("CommandLine="):
            return line[len("CommandLine="):].strip()
    return ""


def stop_server():
    """杀掉占着 3080 的进程。返回 (杀掉的 pid 列表, 说明文字)。"""
    pids = listening_pids()
    if not pids:
        return [], "3080 上没有进程在监听"
    killed = []
    for pid in sorted(pids):
        rc, out = run(["taskkill", "/F", "/PID", str(pid)], timeout=20)
        if rc == 0:
            killed.append(pid)
    return killed, "已结束：%s" % "、".join("PID %d" % p for p in killed) if killed else "结束失败"


def server_bin_of_cmdline(cmd):
    """从命令行里认出跑的是哪份 bin.js。"""
    m = re.search(r'"([^"]*@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js)"', cmd)
    if not m:
        m = re.search(r'(\S*@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js)', cmd)
    return m.group(1) if m else ""


POLLUTE_KEYS = ("TCL_LIBRARY", "TK_LIBRARY", "_MEIPASS", "_MEIPASS2")


def env_pollution(env=None):
    """列出环境里被 PyInstaller 污染、会连累子进程的变量名。"""
    env = os.environ if env is None else env
    bad = []
    for k in env:
        if k.startswith("_PYI_") or k in POLLUTE_KEYS:
            bad.append(k)
    return sorted(bad)


def clean_env():
    """干净的环境副本：剔掉 PyInstaller 残留。

    启动器自己是 PyInstaller 打包的，直接继承 os.environ 起宿主的话，
    宿主以及它派生的每个子进程都会带着 TCL_LIBRARY / TK_LIBRARY 指向
    已经删掉的 _MEI 目录 —— 任何 python GUI 子进程都会以
    "Can't find a usable init.tcl" 崩掉。所以起宿主前必须清掉。
    """
    env = dict(os.environ)
    for k in env_pollution(env):
        env.pop(k, None)
    return env


def clean_mei(log=None):
    """清理 %TEMP%\\_MEI* 残留（跳过正在用的那个）。返回 (清了几个, 释放字节)。"""
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    keep = os.environ.get("_PYI_APPLICATION_HOME_DIR", "")
    if not tmp or not os.path.isdir(tmp):
        return 0, 0
    n = 0
    freed = 0
    for name in os.listdir(tmp):
        if not name.startswith("_MEI"):
            continue
        p = os.path.join(tmp, name)
        if not os.path.isdir(p):
            continue
        if keep and norm_path(p) == norm_path(keep):
            continue
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    freed += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        shutil.rmtree(p, ignore_errors=True)
        if not os.path.isdir(p):
            n += 1
            if log:
                log("清掉残留：%s" % name)
    return n, freed


def repair(log=None):
    """一键体检并修能修的。返回 [(项目, 说明, 是否OK)]。"""
    def say(s):
        if log:
            log(s)

    out = []
    say("开始修复 DSH…")

    # 1 环境变量污染
    bad = env_pollution()
    if bad:
        say("环境变量有 PyInstaller 残留：%s" % "、".join(bad))
        out.append(("环境变量", "有残留（%s）· 重启宿主时自动剔除" % "、".join(bad), False))
    else:
        out.append(("环境变量", "干净", True))

    # 2 临时目录残留
    n, freed = clean_mei(log)
    if n:
        out.append(("临时残留", "清掉 %d 个 _MEI 目录，释放 %.1f MB" % (n, freed / 1048576.0), True))
    else:
        out.append(("临时残留", "没有可清的", True))

    # 3 端口上的进程
    pids = sorted(listening_pids())
    if not pids:
        out.append(("宿主进程", "3080 上没有进程", False))
    elif len(pids) == 1:
        out.append(("宿主进程", "PID %d 在监听 3080" % pids[0], True))
    else:
        killed = []
        for pid in sorted(pids)[:-1]:
            rc, _ = run(["taskkill", "/F", "/PID", str(pid)], timeout=20)
            if rc == 0:
                killed.append(pid)
        out.append(("宿主进程", "3080 上有 %d 个进程，结束了 %s" % (
            len(pids), "、".join("PID %d" % p for p in killed) or "0 个"), not killed))

    # 4 运行环境
    node = find_node()
    npm = find_npm()
    miss = []
    if not node:
        miss.append("node.exe")
    if not npm:
        miss.append("npm")
    for p, name in ((DSH_HOME, "~/.dsh"), (PROFILE_DIR, "profiles\\web"), (PROFILE_NM, "node_modules")):
        if not os.path.isdir(p):
            miss.append(name)
    if miss:
        out.append(("运行环境", "缺：%s" % "、".join(miss), False))
    else:
        out.append(("运行环境", "node、npm、profile、node_modules 都在", True))

    # 5 插件
    try:
        _note, plugins = scan_plugins()
        badp = [p["name"] for p in plugins if p["level"] != "ok"]
        if badp:
            out.append(("插件", "%d 个有问题：%s" % (len(badp), "、".join(badp[:6])), False))
        else:
            out.append(("插件", "%d 个全部正常" % len(plugins), True))
    except Exception as e:
        out.append(("插件", "体检失败：%s: %s" % (type(e).__name__, e), False))

    # 6 配置
    cfg = load_config()
    if isinstance(cfg, dict) and cfg:
        out.append(("配置文件", "读得动（%d 项）" % len(cfg), True))
    else:
        out.append(("配置文件", "读不出来，已重置", False))
        save_config(dict(DEFAULT_CONFIG))

    ok = sum(1 for _n, _d, good in out if good)
    say("修复完成：%d 项正常，%d 项要注意" % (ok, len(out) - ok))
    return out


def start_server(bin_js, node=None, hide=True):
    """在后台起 dsh web。hide=True 时不弹 CMD 窗口（日志走 launcher 自己记）。"""
    node = node or find_node()
    if not node:
        return None, "找不到 node.exe"
    if not os.path.isfile(bin_js):
        return None, "找不到入口文件：%s" % bin_js
    try:
        p = subprocess.Popen([node, bin_js, "web"], cwd=HOME,
                             creationflags=(NO_WINDOW if hide else NEW_CONSOLE))
        return p.pid, "已启动（PID %d）" % p.pid
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------- 版本

def ver_key(v):
    """可比大小的版本键；正式版 > 任何预发布版。"""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?$", str(v).strip())
    if not m:
        return ((0, 0, 0), (0, ()))
    main = tuple(int(x) for x in m.group(1, 2, 3))
    pre = m.group(4)
    if pre is None:
        return (main, (1, ()))
    parts = []
    for seg in pre.split("."):
        parts.append((0, int(seg)) if seg.isdigit() else (1, seg))
    return (main, (0, tuple(parts)))


def sort_versions(vs):
    return sorted(set(vs), key=ver_key, reverse=True)


def _version_from_dir(dsh_dir):
    """dsh 包目录 → (版本, bin.js 路径)。"""
    pj = read_json(os.path.join(dsh_dir, "package.json"))
    ver = pj.get("version")
    bin_js = os.path.join(dsh_dir, "lib", "bin.js")
    if not ver or not os.path.isfile(bin_js):
        return None
    return str(ver), bin_js


def installed_versions():
    """本地能直接跑的版本：{版本: {bin, dir, source}}。含自装目录与 npx 缓存。"""
    found = {}
    # npx 缓存先扫：宿主平时跑的就是这一份，同版本时以它为准（「版本来源」才显示得对）
    if os.path.isdir(NPM_CACHE_NPX):
        for name in os.listdir(NPM_CACHE_NPX):
            d = os.path.realpath(os.path.join(NPM_CACHE_NPX, name, "node_modules", "@deepseek-ai", "dsh"))
            got = _version_from_dir(d)
            if got:
                found[got[0]] = {"bin": got[1], "dir": d, "source": "npx 缓存"}
    # 启动器自己装的
    if os.path.isdir(VERSIONS_DIR):
        for name in os.listdir(VERSIONS_DIR):
            d = os.path.realpath(os.path.join(VERSIONS_DIR, name, "node_modules", "@deepseek-ai", "dsh"))
            got = _version_from_dir(d)
            if got and got[0] not in found:
                found[got[0]] = {"bin": got[1], "dir": d, "source": "启动器装在本地"}
    return found


def running_version():
    """当前 3080 宿主跑的是哪个版本（从命令行 + 包目录反查）。"""
    for pid in sorted(listening_pids()):
        cmd = pid_cmdline(pid)
        bin_js = server_bin_of_cmdline(cmd)
        if bin_js:
            d = os.path.realpath(os.path.dirname(os.path.dirname(bin_js)))
            got = _version_from_dir(d)
            return {"pid": pid, "version": got[0] if got else "?", "bin": bin_js, "dir": d}
        return {"pid": pid, "version": "?", "bin": "", "dir": ""}
    return None


def fetch_remote(timeout=15):
    """查镜像源上的版本清单。返回 (数据, 错误文字)。"""
    url = "%s/%s" % (REGISTRY, PKG.replace("/", "%2f"))
    try:
        req = urllib.request.Request(url, headers={"accept": "application/json",
                                                   "User-Agent": "dsh-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        versions = list((data.get("versions") or {}).keys())
        tags = data.get("dist-tags") or {}
        return {"versions": sort_versions(versions), "tags": tags}, ""
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def dir_size(path):
    """目录总字节数（拿不到的大小忽略）。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except Exception:
                pass
    return total


# 装一个版本大概这么大（用来算进度百分比；装完会按真实值校正）
INSTALL_EST_BYTES = 110 * 1024 * 1024


def npm_install(version, log, prog=None):
    """把某个版本装到 versions\\<版本>\\。

    log  : callable(str)          日志
    prog : callable(size, speed, eta)  下载进度（字节 / 字节每秒 / 已用时秒）
    """
    npm = find_npm()
    if not npm:
        return False, "找不到 npm.cmd"
    target = os.path.join(VERSIONS_DIR, version)
    os.makedirs(target, exist_ok=True)
    args = ["cmd", "/c", npm, "install", "--prefix", target,
            "%s@%s" % (PKG, version), "--registry", REGISTRY,
            "--no-audit", "--no-fund", "--loglevel", "info"]
    log("$ npm install %s@%s" % (PKG, version))
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=NO_WINDOW, cwd=target)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    t0 = time.time()
    last_t = t0
    last_b = 0
    if prog:
        prog(0, 0.0, 0.0)
    for raw in p.stdout:
        log(raw.decode("utf-8", errors="replace").rstrip())
        if prog:
            now = time.time()
            if now - last_t >= 0.7:
                size = dir_size(target)
                speed = (size - last_b) / max(0.001, now - last_t)
                prog(size, speed, now - t0)
                last_b, last_t = size, now
    p.wait()
    if prog:
        prog(dir_size(target), 0.0, time.time() - t0)
    if p.returncode != 0:
        return False, "npm 退出码 %s" % p.returncode
    got = _version_from_dir(os.path.join(target, "node_modules", "@deepseek-ai", "dsh"))
    if not got:
        return False, "装完了但没找到 dsh 包目录"
    return True, "已装好 %s" % got[0]


# ---------------------------------------------------------------- 峰谷时段

def ledger_config():
    j = read_json(LEDGER)
    return j.get("config") or {}


def _off_zone(dt_utc, holidays):
    """周末或配置的中国公众假期 → 返回 'holiday' / 'weekend'，否则 None。"""
    cn = dt_utc.astimezone(CN_TZ)
    if cn.strftime("%Y-%m-%d") in holidays:
        return "holiday"
    if cn.weekday() >= 5:
        return "weekend"
    return None


def _eff_ms(cfg):
    s = cfg.get("peakEffectiveAt")
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000.0
    except Exception:
        return None


def is_peak(dt_utc, cfg):
    """复刻 dsh-cost-meter 的 isPeakHour：窗口按 UTC 小时半开区间。"""
    windows = cfg.get("peakWindows") or []
    if not windows:
        return False
    holidays = set(cfg.get("peakHolidays") or [])
    if _off_zone(dt_utc, holidays) is not None:
        return False
    eff = _eff_ms(cfg)
    if eff is not None and dt_utc.timestamp() * 1000.0 < eff:
        return False
    hour = dt_utc.astimezone(timezone.utc).hour
    for w in windows:
        try:
            start, end = int(w.get("start")), int(w.get("end"))
        except Exception:
            continue
        if start < end:
            if start <= hour < end:
                return True
        elif hour >= start or hour < end:
            return True
    return False


def peak_state(now=None):
    """现在算高峰还是空闲 + 下一次切换时刻。"""
    cfg = ledger_config()
    now = now or datetime.now(timezone.utc)
    windows = cfg.get("peakWindows") or []
    holidays = set(cfg.get("peakHolidays") or [])
    zone = _off_zone(now, holidays)
    in_peak = is_peak(now, cfg)

    nxt = None
    if windows:
        day0 = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        cands = set()
        for day in range(0, 12):
            d = day0 + timedelta(days=day)
            cands.add(d + timedelta(hours=16))  # 北京时间次日 00:00
            for w in windows:
                try:
                    s, e = int(w.get("start")), int(w.get("end"))
                except Exception:
                    continue
                cands.add(d + timedelta(hours=s))
                cands.add(d + timedelta(hours=e))
        for c in sorted(cands):
            if c <= now:
                continue
            if is_peak(c, cfg) != in_peak:
                nxt = c
                break

    if in_peak:
        label = "高峰时段"
        note = "全价"
    elif zone == "holiday":
        label = "假期 · 空闲时段"
        note = "半价"
    elif zone == "weekend":
        label = "周末 · 空闲时段"
        note = "半价"
    else:
        label = "空闲时段"
        note = "半价"

    return {
        "in_peak": in_peak,
        "zone": zone,
        "label": label,
        "note": note,
        "windows": windows,
        "next": nxt,
        "next_cn": nxt.astimezone(CN_TZ) if nxt else None,
        "has_config": bool(windows),
    }


# ---------------------------------------------------------------- 插件体检

def link_target(path):
    """junction / symlink 的真实目标，否则 None。

    Windows 的 junction 用 os.path.islink() 判会返回 False，
    必须看 lstat 的 FILE_ATTRIBUTE_REPARSE_POINT 位。
    """
    try:
        st = os.lstat(path)
        if not (getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return None
        try:
            return os.readlink(path)
        except Exception:
            return os.path.realpath(path)
    except Exception:
        return None


def norm_path(p):
    s = str(p or "")
    if s.startswith("\\\\?\\"):
        s = s[4:]
    return os.path.normcase(os.path.normpath(s.replace("/", "\\")))


def clean_display(p):
    s = str(p or "")
    return s[4:] if s.startswith("\\\\?\\") else s


def read_disabled():
    """从 cordis.patch.yml 里读出被显式 disabled 的 id。"""
    txt = read_text(os.path.join(PROFILE_DIR, "cordis.patch.yml"))
    out = set()
    cur = None
    for line in txt.splitlines():
        s = line.strip()
        m = re.match(r"^-?\s*id:\s*([A-Za-z0-9_@/.\-]+)", s)
        if m:
            cur = m.group(1)
            continue
        if cur and re.match(r"^disabled:\s*true\b", s):
            out.add(cur)
    return out


def http_probe(url, timeout=3.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dsh-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, "HTTP %s" % e.code
    except Exception as e:
        return None, str(e)


def probe_host():
    code, extra = http_probe(BASE_URL + "/")
    if code == 200:
        return True, "宿主在 %s 上答应（首页 %s 字节）" % (BASE_URL, extra)
    if code == 401:
        return True, "宿主在 %s 上活着（首页要登录，返回 401）" % BASE_URL
    return False, "宿主没答应：%s" % extra


PROFILE_JSON = os.path.join(HOME, ".dsh", "profiles", "web", "package.json")


def load_profile():
    """读 profile 的 package.json（拿不到就 None）。"""
    try:
        with io.open(PROFILE_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def profile_bundles():
    """当前启用的 bundle 列表。"""
    d = load_profile() or {}
    return list(((d.get("dsh") or {}).get("profile") or {}).get("bundles") or [])


def _write_profile(d):
    try:
        shutil.copy2(PROFILE_JSON, PROFILE_JSON + ".bak")
        with io.open(PROFILE_JSON, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    except Exception as e:
        return False, str(e)
    return True, ""


def set_bundle(name, on):
    """启用 / 禁用插件：加进或移出 dsh.profile.bundles。改前自动备份 .bak。"""
    d = load_profile()
    if not d:
        return False, "读不到 profile/package.json"
    prof = dict((d.get("dsh") or {}).get("profile") or {})
    bundles = list(prof.get("bundles") or [])
    if on:
        if name in bundles:
            return True, ""
        if name not in (d.get("dependencies") or {}):
            return False, "%s 还没装" % name
        bundles.append(name)
    else:
        if name not in bundles:
            return True, ""
        bundles = [b for b in bundles if b != name]
    prof["bundles"] = bundles
    d.setdefault("dsh", {})["profile"] = prof
    return _write_profile(d)


def trusted_list():
    d = load_profile() or {}
    return list(d.get("trustedDependencies") or [])


def set_trusted(name, on):
    """信任 / 取消信任某个插件（写 trustedDependencies）。"""
    d = load_profile()
    if not d:
        return False, "读不到 profile/package.json"
    lst = list(d.get("trustedDependencies") or [])
    if on and name not in lst:
        lst.append(name)
    elif not on:
        lst = [x for x in lst if x != name]
    d["trustedDependencies"] = lst
    return _write_profile(d)


def scan_plugins(progress=None):
    """返回 (总览文字, [每插件的结果])。四层判据：声明 / 打包清单 / 文件到位 / 跑起来了。

    progress：可选回调 progress(第几个, 共几个, 插件名)，用来在界面上推进度。
    """
    pkg = read_json(PROFILE_PKG)
    if "__error__" in pkg:
        return "读不到 profile 的 package.json：%s" % pkg["__error__"], []

    deps = pkg.get("dependencies") or {}
    dsh = pkg.get("dsh") or {}
    prof = dsh.get("profile") or {}
    bundles = prof.get("bundles") or []
    disabled = read_disabled()
    host_ok, host_msg = probe_host()

    results = []
    names = sorted(deps.keys())
    total = len(names)
    for idx, name in enumerate(names, 1):
        if progress:
            try:
                progress(idx, total, name)
            except Exception:
                pass
        spec = str(deps[name])
        bad, warn, ok = [], [], []
        where = "--"

        in_bundles = name in bundles
        if name in disabled:
            bad.append("在 cordis.patch.yml 里被显式 disabled: true —— 关掉了")
        elif not in_bundles:
            bad.append("不在 dsh.profile.bundles 里 —— 宿主不会加载它")

        inst = os.path.join(PROFILE_NM, name)
        if not os.path.isdir(inst):
            bad.append("node_modules 里找不到，可能没装成")
        else:
            tgt = link_target(inst)
            if spec.startswith("link:"):
                where = clean_display(tgt) if tgt else spec[5:]
                if tgt and norm_path(tgt) != norm_path(spec[5:]):
                    warn.append("link 实际指向 %s，声明里写的是 %s" % (clean_display(tgt), spec[5:]))
                if not os.path.isdir(spec[5:]):
                    bad.append("link 目标目录不存在：%s" % spec[5:])
            else:
                where = clean_display(tgt) if tgt else inst
                if tgt:
                    warn.append("装的时候声明是版本号 %s，实际是指向 %s 的联接" % (spec, clean_display(tgt)))

            sub = read_json(os.path.join(inst, "package.json"))
            if "__error__" in sub:
                bad.append("插件自己的 package.json 读不了：%s" % sub["__error__"])
            else:
                d = sub.get("dsh") or {}
                has_client = isinstance(d.get("client"), dict)
                has_patch = "bundle" in d
                if has_client:
                    ok.append("有客户端半边 dsh.client")
                if has_patch:
                    ok.append("有宿主半边 dsh.bundle.patch")
                if not has_client and not has_patch:
                    warn.append("package.json 里既没有 dsh.client 也没有 dsh.bundle.patch，可能不是 DSH 插件")
                ver = sub.get("version")
                if ver:
                    ok.append("版本 " + str(ver))

        if host_ok:
            code, extra = http_probe("%s/%s/client.js" % (BASE_URL, name))
            if code == 200:
                ok.append("客户端脚本 /%s/client.js 取到 %s 字节" % (name, extra))
            elif code == 401:
                ok.append("宿主活着，但未登录（401），静态路由这层没测到")
            else:
                ok.append("静态路由探测：%s（客户端脚本的真实路径规律待确认，暂不判定）" % extra)
        else:
            ok.append("宿主没在跑，第 4 层（跑起来了）没测")

        if bad:
            level = "bad"
        elif warn:
            level = "warn"
        else:
            level = "ok"
        results.append({
            "name": name, "spec": spec, "where": where,
            "bundles": "在" if in_bundles else "不在",
            "level": level, "ok": ok, "warn": warn, "bad": bad,
        })

    ghost = [b for b in bundles if b not in deps and not str(b).startswith("@deepseek-ai/")]
    lines = ["profile：%s" % PROFILE_DIR,
             "依赖 %d 个，打包清单 %d 项" % (len(deps), len(bundles)),
             "宿主：%s" % host_msg]
    if ghost:
        lines.append("只在打包清单里、依赖里没有的：%s" % "、".join(ghost))
    return "\n".join(lines), results


# ---------------------------------------------------------------- 配置

APP_VER = "1.0.0"
REPO = "xiaocaiawa/dsh-uton-launcher"
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), "dsh-launcher", "settings.json")
DEFAULT_SETTINGS = {
    "registry": "npmmirror",
    "compat": False,
    "open_mode": "browser",
    "check_update": True,
    "topmost": True,
    "hide_cmd": True,
    "stop_on_exit": False,
    "keep_log": 500,
    "confirm_repair": True,
}


def load_settings():
    cfg = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass
    return cfg


def save_settings(cfg):
    try:
        d = os.path.dirname(SETTINGS_PATH)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True, ""
    except Exception as e:
        return False, str(e)


def find_browser():
    """找一个能用 --app 的 Chromium 系浏览器。"""
    cands = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def open_dsh(mode="browser", url=None):
    """按设置里的打开方式打开 DSH 页面，返回 (成功, 错误)。"""
    import webbrowser
    url = url or BASE_URL
    mode = mode or "browser"
    if mode == "browser":
        try:
            if webbrowser.open(url):
                return True, ""
        except Exception as e:
            return False, "%s: %s" % (type(e).__name__, e)
        return False, "系统里没有可用的默认浏览器"
    exe = find_browser()
    if not exe:
        return False, "没找到 Edge 或 Chrome"
    if mode == "window":
        args = [exe, "--app=" + url, "--window-size=1280,860", "--new-window"]
    else:
        args = [exe, "--app=" + url, "--window-size=430,880", "--new-window"]
    try:
        subprocess.Popen(args, creationflags=NO_WINDOW)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    return True, ""


def find_git():
    for p in (r"D:\Git\cmd\git.exe",
              r"C:\Program Files\Git\cmd\git.exe",
              os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Git\cmd\git.exe")):
        if p and os.path.isfile(p):
            return p
    return shutil.which("git")


def remote_tags(timeout=25):
    """git ls-remote 查远端标签，返回 (最新标签, main 的 sha, 错误)。"""
    git = find_git()
    if not git:
        return None, None, "没找到 git"
    code, text = run([git, "ls-remote", "--tags", "--heads",
                      "https://github.com/" + REPO], timeout=timeout)
    if code != 0:
        return None, None, (text.strip()[:200] or "git ls-remote 失败")
    tags, sha = [], None
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) != 2:
            continue
        h, ref = parts
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref[len("refs/tags/"):])
        elif ref == "refs/heads/main":
            sha = h
    if tags:
        tags.sort(key=lambda t: [int(x) for x in re.findall(r"\d+", t)] or [0])
    return (tags[-1] if tags else None), sha, None


DEFAULT_CONFIG = {
    "pick_mode": "auto",      # auto = 追最新正式版；manual = 用下面选的版本
    "update_mode": "manual",  # auto = 启动前自动装新版；manual = 只在点按钮时装
    "selected": "",
    "channel": "latest",      # latest = 只认正式版；alpha = 连预发布版一起认
    "last_check": 0,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    got = read_json(CONFIG_PATH)
    if isinstance(got, dict) and "__error__" not in got:
        cfg.update(got)
    return cfg


def save_config(cfg):
    return write_json(CONFIG_PATH, cfg)


def pick_version(cfg, local, remote):
    """按模式挑一个要跑的版本。返回 (版本号, 说明)。"""
    if cfg.get("pick_mode") == "manual":
        v = cfg.get("selected") or ""
        if v:
            return v, "手动选定 %s" % v
        return "", "手动模式但还没选版本"

    if not remote:
        # 没有远端信息就退回本地最新
        vs = sort_versions(local.keys())
        return (vs[0], "远端不可达，取本地最新 %s" % vs[0]) if vs else ("", "本地没有可用版本")

    if cfg.get("channel") == "alpha":
        pool = remote.get("versions") or []
        tag = (remote.get("tags") or {}).get("alpha") or ""
        if tag in pool:
            return tag, "自动追 alpha 通道 %s" % tag
    else:
        tag = (remote.get("tags") or {}).get("latest") or ""
        if tag:
            return tag, "自动追正式版 %s" % tag
    vs = remote.get("versions") or []
    return (vs[0], "取远端最新 %s" % vs[0]) if vs else ("", "远端没有版本信息")
