"""一键启动产品：在控制台里运行产品自己的启动脚本，等它能访问后给出页面地址。

- 启动方式来自收件箱的 preview 字段（AI 声明），没有时从验收清单和产品文件夹里的 start.sh 推断。
- 只运行产品文件夹里的脚本（不经过 shell 拼接），只接受本机地址，用户点击才会运行。
- 每个产品最多一个预览进程；AI 开始运行、控制台退出时自动停止。
"""

import atexit
import os
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import executors as ex

READY_TIMEOUT = 300          # 第一次启动可能要装依赖
LOG_TAIL = 60

_lock = threading.Lock()
_procs = {}                  # pid -> Preview

_URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{2,5})?(?:/[^\s，。、“”\"'）)]*)?")
_SCRIPT_RE = re.compile(r"(?:^|[\s`“\"'])(\./)?([A-Za-z0-9_./-]*start[A-Za-z0-9_.-]*\.sh)\b")


def _local_url(url):
    try:
        u = urlparse(str(url or ""))
    except ValueError:
        return None
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1"):
        return None
    if u.port is not None and not (1 <= u.port <= 65535):
        return None
    return u.geturl()


def _script(pdir, rel):
    """只允许产品文件夹里的脚本文件。返回绝对路径或 None。"""
    rel = str(rel or "").strip()
    if not rel or rel.startswith("/") or ".." in rel.replace("\\", "/").split("/"):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", rel):
        return None
    p = os.path.realpath(os.path.join(pdir, rel))
    root = os.path.realpath(pdir)
    if not p.startswith(root + os.sep) or not os.path.isfile(p):
        return None
    return p


def spec(pdir, box):
    """这个产品怎么启动。返回 {command, url, source} 或 None。"""
    if not box:
        return None
    raw = box.get("preview") or {}
    if raw:
        cmd = str(raw.get("command") or "").strip()
        args = [str(a) for a in raw.get("args") or []][:10]
        if " " in cmd and not args:                       # "./start.sh --dev" 这类写法
            cmd, *args = cmd.split()
        script = _script(pdir, cmd[2:] if cmd.startswith("./") else cmd)
        url = _local_url(raw.get("url"))
        if script and url and all(re.fullmatch(r"[A-Za-z0-9_.:=/-]{1,80}", a) for a in args):
            return {"command": os.path.relpath(script, pdir), "args": args, "url": url, "source": "inbox"}
    # 推断：验收清单里提到 start.sh 和本机地址
    text = " ".join("%s %s" % (c.get("do", ""), c.get("expect", "")) for c in box.get("checklist") or [])
    m = _SCRIPT_RE.search(text)
    cand = [m.group(2)] if m else []
    cand += ["start.sh"]
    script = next((s for s in (_script(pdir, c) for c in cand) if s), None)
    if not script or ("start" not in text and not m):
        return None
    u = _URL_RE.search(text)
    url = _local_url(u.group(0) if u else "http://127.0.0.1:8000")
    return {"command": os.path.relpath(script, pdir), "args": [], "url": url, "source": "guess"} if url else None


class Preview:
    def __init__(self, pid, pdir, sp):
        self.pid, self.pdir, self.spec = pid, pdir, sp
        self.proc = None
        self.status = "idle"         # idle | starting | running | exited | stopped | failed
        self.started = None
        self.ready_at = None
        self.code = None
        self.message = ""
        self.log_path = os.path.join(pdir, "factory", "runs", "preview.log")

    def meta(self):
        return {"status": self.status, "command": "./" + self.spec["command"] + "".join(" " + a for a in self.spec["args"]),
                "url": self.spec["url"], "started": self.started, "code": self.code, "message": self.message,
                "log": tail(self.log_path)}


def tail(path, n=LOG_TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    lines = text.splitlines()[-n:]
    # 日志可能带上程序打印的密钥，按常见格式打码后再给页面
    out = []
    for line in lines:
        line = re.sub(r"((?:api[-_]?key|key|token|secret|password)[-_A-Za-z0-9]*\s*[=:]\s*)\S+", r"\1***", line, flags=re.I)
        line = re.sub(r"\b(sk|pk|rk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{4,}", r"\1-***", line)
        line = re.sub(r"(Bearer\s+)\S+", r"\1***", line, flags=re.I)
        out.append(line)
    return "\n".join(out)


def _reachable(url, timeout=1.5):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # 本机地址不走代理
    try:
        opener.open(url, timeout=timeout).close()
        return True
    except urllib.error.HTTPError:
        return True                     # 有 HTTP 响应就算起来了
    except (urllib.error.URLError, OSError, ValueError):
        return False


def status(pid, pdir, box):
    sp = spec(pdir, box)
    with _lock:
        pv = _procs.get(pid)
    if pv and pv.status in ("starting", "running"):
        return dict(pv.meta(), available=True)
    if not sp:
        return {"available": False}
    if pv and pv.spec == sp:
        return dict(pv.meta(), available=True)
    return dict(Preview(pid, pdir, sp).meta(), available=True, log="")


def start(pid, pdir, box):
    sp = spec(pdir, box)
    if not sp:
        raise ValueError("这个产品还没有提供启动方式。")
    with _lock:
        cur = _procs.get(pid)
        if cur and cur.status in ("starting", "running"):
            return cur.meta()
    if _reachable(sp["url"], timeout=0.8):
        raise ValueError("%s 已经有程序在运行。可能是之前在终端启动的，先关掉它，或直接打开这个地址。" % sp["url"])
    pv = Preview(pid, pdir, sp)
    os.makedirs(os.path.dirname(pv.log_path), exist_ok=True)
    script = os.path.join(pdir, sp["command"])
    cmd = ([script] if os.access(script, os.X_OK) else ["/bin/sh", script]) + sp["args"]
    env = {k: v for k, v in os.environ.items() if k not in ex._CRED_VARS}
    env["PATH"] = ex.search_path()
    log = open(pv.log_path, "w", encoding="utf-8")
    log.write("$ %s\n" % " ".join(["./" + sp["command"]] + sp["args"]))
    log.flush()
    try:
        pv.proc = subprocess.Popen(cmd, cwd=pdir, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=True)
    except OSError as e:
        log.close()
        raise ValueError("启动失败：%s" % e)
    log.close()
    pv.status, pv.started = "starting", time.strftime("%Y-%m-%dT%H:%M:%S")
    with _lock:
        _procs[pid] = pv
    threading.Thread(target=_watch, args=(pv,), daemon=True).start()
    return pv.meta()


def _watch(pv):
    deadline = time.time() + READY_TIMEOUT
    while pv.proc.poll() is None:
        if pv.status == "starting":
            if _reachable(pv.spec["url"]):
                pv.status, pv.ready_at = "running", time.time()
            elif time.time() > deadline:
                pv.message = "等了 %d 秒还打不开页面，已停止。看看下面的日志。" % READY_TIMEOUT
                _kill(pv)
                pv.status = "failed"
                return
        time.sleep(0.5)
    pv.code = pv.proc.returncode
    if pv.status != "stopped":
        pv.status = "exited" if pv.status == "running" else "failed"
        pv.message = "程序退出了（代码 %s）。看看下面的日志。" % pv.code


def _kill(pv):
    p = pv.proc
    if not p or p.poll() is not None:
        return
    for sig, wait in ((signal.SIGINT, 3), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        try:
            os.killpg(p.pid, sig)
        except (OSError, AttributeError):
            try:
                p.send_signal(sig)
            except OSError:
                return
        end = time.time() + wait
        while time.time() < end:
            if p.poll() is not None:
                return
            time.sleep(0.1)


def stop(pid, reason=""):
    with _lock:
        pv = _procs.get(pid)
    if not pv or pv.status not in ("starting", "running"):
        return False
    pv.status = "stopped"
    pv.message = reason
    _kill(pv)
    return True


def stop_all():
    with _lock:
        pids = list(_procs)
    for pid in pids:
        stop(pid)


atexit.register(stop_all)
