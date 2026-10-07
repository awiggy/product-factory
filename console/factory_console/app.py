"""HTTP 服务：只监听本机，提供 JSON API 与静态页面。"""

import json
import mimetypes
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import STATIC_ROOT
from . import executors as ex
from . import gate
from . import products as pr
from . import runner
from . import secrets

ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


def _detail(pid):
    return pr.detail(pid, runner.active_meta(pid))


def _not_busy(pid):
    if runner.busy(pid):
        raise pr.UserError("AI 正在处理这个产品，等它完成后再操作。", 409)


# ------------------------------------------------------------------ 配置与执行器

def _public_config(cfg):
    cfg = dict(cfg)
    cfg.pop("products", None)
    cfg["executor_label"] = ex.label(cfg)
    return cfg


@route("GET", r"/api/config")
def get_config(h, q, body):
    return {"config": _public_config(pr.load_config()), "guides": pr.guides()}


@route("POST", r"/api/config")
def post_config(h, q, body):
    return {"config": _public_config(pr.update_config(body or {}))}


def _secret_account(body):
    kind = body.get("kind")
    if kind == "provider":
        pid = body.get("provider_id") or ""
        if pid not in ex.PROVIDER_IDS:
            raise pr.UserError("未知的模型厂商")
        return ex.provider_account(pid)
    if kind == "openai":
        return ex.OPENAI_ACCOUNT
    raise pr.UserError("未知的 Key 类型")


@route("GET", r"/api/executors")
def executors(h, q, body):
    cfg = pr.load_config()
    keys = {p["id"]: secrets.masked(ex.provider_account(p["id"])) for p in ex.PROVIDERS}
    return {"detected": ex.detect(cfg), "clis": ex.scan_clis(), "claude_models": ex.CLAUDE_MODELS,
            "pi_thinking": ex.PI_THINKING, "providers": ex.PROVIDERS, "provider_keys": keys,
            "openai_key": secrets.masked(ex.OPENAI_ACCOUNT), "secret_store": secrets.where(),
            "ready_problem": ex.ready_problem(cfg) if cfg.get("executor") in ex.AUTO_EXECUTORS else None}


@route("POST", r"/api/secrets")
def save_secret(h, q, body):
    acct = _secret_account(body)
    try:
        secrets.set_secret(acct, body.get("value") or "")
    except (ValueError, RuntimeError) as e:
        raise pr.UserError(str(e))
    return {"masked": secrets.masked(acct)}


@route("POST", r"/api/secrets/delete")
def delete_secret(h, q, body):
    secrets.delete_secret(_secret_account(body))
    return {"ok": True}


@route("POST", r"/api/executor/test")
def test_executor(h, q, body):
    return ex.test_connection(pr.load_config())


# ------------------------------------------------------------------ 产品

@route("GET", r"/api/products")
def list_products(h, q, body):
    out = []
    for item in pr.registry():
        try:
            s = pr.summary(item)
            s["busy"] = runner.busy(item["id"])
            try:
                d = _detail(item["id"])
                s["next_action"] = d["next_action"]
            except Exception:  # noqa: BLE001
                s["next_action"] = None
            out.append(s)
        except gate.GateError as e:
            out.append({"id": item["id"], "path": item["path"], "error": str(e)})
    return {"products": out}


@route("POST", r"/api/products")
def create_product(h, q, body):
    pid = pr.create_product(body.get("name"), body.get("idea"), body.get("notes", ""), body.get("path") or None)
    if body.get("autostart", True):
        try:
            runner.start(pid, "start")
        except pr.UserError:
            pass
    return {"id": pid}


@route("POST", r"/api/products/demo")
def create_demo(h, q, body):
    pid = pr.create_product("论文阅读助手（演示）",
                            "帮人读英文论文：上传 PDF 后得到中英对照和术语解释，术语能积累成个人词库。",
                            demo=True)
    return {"id": pid}


@route("POST", r"/api/products/import")
def import_product(h, q, body):
    return {"id": pr.import_product(body.get("path"))}


@route("GET", r"/api/products/(?P<pid>[0-9a-f]{10})")
def get_product(h, q, body, pid):
    return _detail(pid)


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/forget")
def forget(h, q, body, pid):
    _not_busy(pid)
    pr.forget_product(pid)
    return {"ok": True}


@route("GET", r"/api/products/(?P<pid>[0-9a-f]{10})/doc")
def get_doc(h, q, body, pid):
    rel = (q.get("path") or [""])[0]
    return {"path": rel, "text": pr.read_doc(pid, rel)}


# ------------------------------------------------------------------ 运行

@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/run")
def start_run(h, q, body, pid):
    return {"run": runner.start(pid, body.get("mode") or "continue")}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/run/stop")
def stop_run(h, q, body, pid):
    runner.stop(pid)
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/run/manual-done")
def manual_done(h, q, body, pid):
    return {"run": runner.manual_done(pid)}


@route("GET", r"/api/products/(?P<pid>[0-9a-f]{10})/runs/(?P<rid>[0-9A-Za-z-]+)")
def get_run(h, q, body, pid, rid):
    since = int((q.get("since") or ["0"])[0] or 0)
    return {"run": runner.get_run(pid, rid, since)}


# ------------------------------------------------------------------ 用户输入与审批

@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/answers")
def answers(h, q, body, pid):
    _not_busy(pid)
    pr.save_answers(pid, body.get("answers") or {})
    if body.get("continue", True):
        runner.start(pid, "continue")
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/actions")
def actions(h, q, body, pid):
    _not_busy(pid)
    pr.save_actions(pid, body.get("done") or [])
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/checklist")
def checklist(h, q, body, pid):
    _not_busy(pid)
    pr.save_checklist(pid, body.get("results") or {})
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/feedback")
def feedback(h, q, body, pid):
    _not_busy(pid)
    pr.add_feedback(pid, body.get("kind") or "revise", body.get("text"))
    if body.get("run", True):
        runner.start(pid, "continue")
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/approve")
def approve(h, q, body, pid):
    _not_busy(pid)
    pr.approve(pid, body.get("id"), body.get("quote"), body.get("scope"), bool(body.get("acknowledged")))
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/waive")
def waive(h, q, body, pid):
    _not_busy(pid)
    pr.waive(pid, body.get("reason"), body.get("quote"))
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/advance")
def advance(h, q, body, pid):
    _not_busy(pid)
    pr.advance(pid)
    if body.get("autostart"):
        try:
            runner.start(pid, "start")
        except pr.UserError:
            pass
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/skip")
def skip(h, q, body, pid):
    _not_busy(pid)
    pr.skip(pid, body.get("reason"))
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/blocker")
def blocker(h, q, body, pid):
    _not_busy(pid)
    pr.blocker(pid, body.get("add"), body.get("clear"), body.get("resolution"))
    return {"ok": True}


@route("POST", r"/api/products/(?P<pid>[0-9a-f]{10})/iterate")
def iterate(h, q, body, pid):
    _not_busy(pid)
    pr.iterate(pid, body.get("reason"))
    return {"ok": True}


# ------------------------------------------------------------------ 服务

class Handler(BaseHTTPRequestHandler):
    server_version = "ProductFactory/0.1"
    allowed_hosts = set()

    def log_message(self, fmt, *args):  # 安静
        pass

    def _send(self, code, payload, ctype="application/json; charset=utf-8", extra=None):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        return (self.headers.get("Host") or "") in self.allowed_hosts

    def _dispatch(self, method):
        if not self._host_ok():
            return self._send(403, {"error": "只允许从本机访问。"})
        url = urlparse(self.path)
        path = unquote(url.path)
        if not path.startswith("/api/"):
            if method != "GET":
                return self._send(405, {"error": "不支持"})
            return self._static(path)
        body = {}
        if method == "POST":
            if self.headers.get("X-Factory") != "1":
                return self._send(403, {"error": "缺少请求头。"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                return self._send(413, {"error": "请求太大。"})
            raw = self.rfile.read(n) if n else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._send(400, {"error": "请求格式不对。"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "请求格式不对。"})
        q = parse_qs(url.query)
        for m, rx, fn in ROUTES:
            if m != method:
                continue
            mt = rx.match(path)
            if mt:
                try:
                    return self._send(200, fn(self, q, body, **mt.groupdict()))
                except pr.UserError as e:
                    return self._send(e.status, {"error": str(e)})
                except gate.GateError as e:
                    return self._send(400, {"error": str(e)})
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    return self._send(500, {"error": "控制台内部错误：%s" % e})
        return self._send(404, {"error": "没有这个接口。"})

    def _static(self, path):
        if path in ("", "/") or not os.path.splitext(path)[1]:
            path = "/index.html"
        full = os.path.realpath(os.path.join(STATIC_ROOT, path.lstrip("/")))
        if not full.startswith(os.path.realpath(STATIC_ROOT) + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "找不到页面"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def make_server(host="127.0.0.1", port=8765):
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    srv = ThreadingHTTPServer((host, port), Handler)
    real_port = srv.server_address[1]
    Handler.allowed_hosts = {"127.0.0.1:%d" % real_port, "localhost:%d" % real_port}
    srv.daemon_threads = True
    return srv
