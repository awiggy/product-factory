"""AI 执行器：Claude Code（官方账号或第三方兼容 API）、Codex（ChatGPT 账号或 OpenAI API Key）、pi。

负责：扫描本机 AI 命令行工具、检测安装与登录、列出可选模型、按阶段权限拼命令、
注入凭据环境变量、把事件流翻译成界面上的进度。
"""

import glob
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import SKILLS_ROOT
from . import gate
from . import secrets

# 第三方模型厂商（Anthropic 兼容接口）。地址与型号来自课程资料的整理，以厂商文档为准。
PROVIDERS = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/anthropic",
     "models": ["deepseek-v4-pro", "deepseek-v4-flash"], "site": "https://platform.deepseek.com"},
    {"id": "kimi-cn", "name": "Kimi（国内）", "base_url": "https://api.moonshot.cn/anthropic",
     "models": ["kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"], "site": "https://platform.moonshot.cn"},
    {"id": "kimi", "name": "Kimi（国际）", "base_url": "https://api.moonshot.ai/anthropic",
     "models": ["kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"], "site": "https://platform.kimi.ai"},
    {"id": "glm-cn", "name": "智谱 GLM（国内）", "base_url": "https://open.bigmodel.cn/api/anthropic",
     "models": ["glm-5.2"], "site": "https://open.bigmodel.cn"},
    {"id": "glm", "name": "Z.ai GLM（国际）", "base_url": "https://api.z.ai/api/anthropic",
     "models": ["glm-5.2"], "site": "https://z.ai"},
    {"id": "minimax-cn", "name": "MiniMax（国内）", "base_url": "https://api.minimaxi.com/anthropic",
     "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"], "site": "https://platform.minimax.io"},
    {"id": "minimax", "name": "MiniMax（国际）", "base_url": "https://api.minimax.io/anthropic",
     "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"], "site": "https://www.minimax.io"},
    {"id": "custom", "name": "自定义（Anthropic 兼容接口）", "base_url": "", "models": [], "site": ""},
]
PROVIDER_IDS = {p["id"] for p in PROVIDERS}

# 能自动执行的执行器（其余是 demo 与 manual）
AUTO_EXECUTORS = ("claude", "codex", "pi")

# Claude Code 可选模型。别名始终指向该系列的最新版本；固定版本不会自动升级。
CLAUDE_MODELS = [
    {"value": "opus", "label": "opus（最新 Opus，能力最强）"},
    {"value": "sonnet", "label": "sonnet（最新 Sonnet，均衡）"},
    {"value": "haiku", "label": "haiku（最新 Haiku，最快最省）"},
    {"value": "opusplan", "label": "opusplan（规划用 Opus，执行用 Sonnet）"},
    {"value": "claude-fable-5-1", "label": "claude-fable-5-1（固定版本，需账号开通）"},
    {"value": "claude-opus-5-5", "label": "claude-opus-5-5（固定版本）"},
    {"value": "claude-sonnet-5-5", "label": "claude-sonnet-5-5（固定版本）"},
    {"value": "claude-haiku-4-5-20251001", "label": "claude-haiku-4-5（固定版本）"},
]

PI_THINKING = ["off", "minimal", "low", "medium", "high", "xhigh"]

# 本机扫描的 AI 命令行工具。supported=True 的可以在控制台里全自动执行；其余可用“复制指令”方式。
KNOWN_CLIS = [
    {"id": "claude", "cmd": "claude", "name": "Claude Code", "supported": True},
    {"id": "codex", "cmd": "codex", "name": "Codex CLI", "supported": True},
    {"id": "pi", "cmd": "pi", "name": "pi coding agent", "supported": True},
    {"id": "gemini", "cmd": "gemini", "name": "Gemini CLI"},
    {"id": "qwen", "cmd": "qwen", "name": "Qwen Code"},
    {"id": "opencode", "cmd": "opencode", "name": "OpenCode"},
    {"id": "cursor-agent", "cmd": "cursor-agent", "name": "Cursor CLI"},
    {"id": "copilot", "cmd": "copilot", "name": "GitHub Copilot CLI"},
    {"id": "aider", "cmd": "aider", "name": "Aider"},
    {"id": "goose", "cmd": "goose", "name": "Goose"},
    {"id": "kimi", "cmd": "kimi", "name": "Kimi CLI"},
    {"id": "iflow", "cmd": "iflow", "name": "iFlow CLI"},
    {"id": "codebuddy", "cmd": "codebuddy", "name": "CodeBuddy Code"},
    {"id": "crush", "cmd": "crush", "name": "Crush"},
    {"id": "amp", "cmd": "amp", "name": "Amp"},
    {"id": "droid", "cmd": "droid", "name": "Factory Droid"},
    {"id": "kiro-cli", "cmd": "kiro-cli", "name": "Kiro CLI"},
]

DENY_ALWAYS = ["Edit(./factory/state.json)", "Write(./factory/state.json)", "Bash(sudo *)", "Bash(git push *)",
               "Bash(rm -rf /*)", "Bash(rm -rf ~*)"]


def provider_account(pid):
    return "provider:" + pid


OPENAI_ACCOUNT = "openai"


# ------------------------------------------------------------------ 显示名

def label(cfg):
    ex = cfg.get("executor", "demo")
    if ex == "claude":
        if cfg.get("claude_source") == "provider":
            p = next((x for x in PROVIDERS if x["id"] == cfg.get("provider_id")), None)
            return "Claude Code + %s" % (p["name"] if p else "第三方 API")
        return "Claude Code"
    if ex == "codex":
        return "Codex" + (" + OpenAI API Key" if cfg.get("codex_source") == "api_key" else "")
    if ex == "pi":
        return "pi" + ((" + " + cfg["pi_model"]) if cfg.get("pi_model") else "")
    return {"demo": "演示模式", "manual": "复制指令"}.get(ex, ex)


# ------------------------------------------------------------------ 检测

def _extra_dirs():
    """双击启动时 PATH 可能不完整（比如 nvm、bun 装的命令），补上常见的安装位置。"""
    h = os.path.expanduser("~")
    dirs = ["/opt/homebrew/bin", "/usr/local/bin", h + "/.local/bin", h + "/.npm-global/bin", h + "/.bun/bin",
            h + "/.volta/bin", h + "/.cargo/bin", h + "/Library/pnpm", h + "/.local/share/pnpm",
            h + "/.claude/local", h + "/.deno/bin", h + "/bin"]
    dirs += sorted(glob.glob(h + "/.nvm/versions/node/*/bin"), reverse=True)
    dirs += sorted(glob.glob(h + "/.fnm/node-versions/*/installation/bin"), reverse=True)
    return dirs


def search_path():
    seen, out = set(), []
    for d in (os.environ.get("PATH", "").split(os.pathsep) + _extra_dirs()):
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return os.pathsep.join(out)


def _which(path):
    if not path:
        return None
    if os.sep in path:
        return path if os.path.isfile(path) and os.access(path, os.X_OK) else None
    return shutil.which(path, path=search_path())


def _first_line(text):
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def scan_clis():
    """扫描本机装了哪些 AI 命令行工具，并读取版本号。"""
    found = [(c, _which(c["cmd"])) for c in KNOWN_CLIS]
    found = [(c, p) for c, p in found if p]

    def version(item):
        c, p = item
        code, text = _run([p, "--version"], timeout=8, env=_tool_env(p))
        return {"id": c["id"], "name": c["name"], "cmd": c["cmd"], "path": p,
                "supported": bool(c.get("supported")), "version": _first_line(text) if code == 0 else ""}

    if not found:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(version, found))


def _tool_env(path, base=None):
    """让命令能找到同目录下的 node 等运行时。"""
    env = dict(base if base is not None else os.environ)
    d = os.path.dirname(path or "")
    env["PATH"] = os.pathsep.join([x for x in [d, search_path()] if x])
    return env


# ------------------------------------------------------------------ 各工具自己的默认模型

def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def claude_default_model():
    for p in [os.path.expanduser("~/.claude/settings.json")]:
        try:
            m = (json.loads(_read_text(p) or "{}") or {}).get("model")
        except ValueError:
            m = None
        if m:
            return str(m)
    return os.environ.get("ANTHROPIC_MODEL") or ""


def codex_default_model():
    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    text = _read_text(os.path.join(home, "config.toml"))
    # 只读顶层的 model（第一个 [表] 之前）
    top = re.split(r"^\s*\[", text, maxsplit=1, flags=re.M)[0]
    m = re.search(r'^\s*model\s*=\s*["\']([^"\']+)["\']', top, flags=re.M)
    return m.group(1) if m else ""


def _codex_model_items(rows, cached=False, api_key=False):
    """只回传下拉需要的字段，忽略目录中的身份、凭据与隐藏型号。"""
    out, seen = [], set()
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        if cached:
            if row.get("visibility") != "list" or (api_key and row.get("supported_in_api") is False):
                continue
            value, name = row.get("slug"), row.get("display_name")
        else:
            if row.get("hidden"):
                continue
            value, name = row.get("model") or row.get("id"), row.get("displayName")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:/\[\]@+-]{1,120}", value) or value in seen:
            continue
        seen.add(value)
        out.append({"value": value, "label": name[:160] if isinstance(name, str) and name else value})
    return out


def _codex_app_server_models(path, cfg, timeout=10):
    """官方只读 model/list；不创建对话、不推理、不发起登录，也不回传原始错误。"""
    proc = None
    reader = None
    messages = queue.Queue()
    deadline = time.monotonic() + timeout
    try:
        # CODEX_API_KEY 是 exec 的参数来源，不能用它假装 app-server 已切换登录。
        # 目录沿用本机 Codex 登录/配置；工厂保存的 Key 不参与本次目录查询。
        env = run_env(dict(cfg, executor="codex", codex_source="account"))
        proc = subprocess.Popen([path, "app-server", "--listen", "stdio://"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", env=_tool_env(path, env),
                                start_new_session=os.name == "posix")

        def read_lines():
            try:
                for line in proc.stdout:
                    messages.put(line)
            finally:
                proc.stdout.close()
                messages.put(None)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def response(request_id):
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                line = messages.get(timeout=remaining)
                if line is None:
                    raise ValueError("app-server closed")
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict) or message.get("id") != request_id:
                    continue
                if "error" in message or not isinstance(message.get("result"), dict):
                    raise ValueError("app-server request failed")
                return message["result"]

        send({"id": 0, "method": "initialize", "params": {
            "clientInfo": {"name": "product_factory", "title": "产品工厂", "version": "0.4.0"}}})
        response(0)
        send({"method": "initialized", "params": {}})
        rows, cursors = [], set()
        cursor = None
        for request_id in range(1, 51):
            params = {"limit": 100, "includeHidden": False}
            if cursor is not None:
                params["cursor"] = cursor
            send({"id": request_id, "method": "model/list", "params": params})
            result = response(request_id)
            if not isinstance(result.get("data"), list):
                raise ValueError("invalid model list")
            rows.extend(result["data"])
            cursor = result.get("nextCursor")
            if cursor is None:
                return _codex_model_items(rows)
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("invalid model cursor")
            cursors.add(cursor)
        return None
    except (OSError, ValueError, TimeoutError, queue.Empty):
        return None
    finally:
        if proc is not None:
            def stop(force=False):
                try:
                    if os.name == "posix":
                        # npm 的 Codex 命令会再启动 Rust 子进程，需回收本次创建的整组。
                        os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
                    elif proc.poll() is None:
                        (proc.kill if force else proc.terminate)()
                except OSError:
                    pass

            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            try:
                proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                stop()
                try:
                    proc.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    stop(force=True)
                    proc.wait()
            stop()
            if reader is not None:
                reader.join(timeout=0.3)
                if reader.is_alive():
                    stop(force=True)
                    reader.join(timeout=0.3)
            # 不与仍在 read 的线程竞争管道锁，否则失控的包装器子进程会拖过查询时限。
            if proc.stdout is not None and (reader is None or not reader.is_alive()):
                proc.stdout.close()


def codex_models(path, cfg):
    """模型目录来源单独标记；目录不代表当前账号或 API Key 已获全部调用权限。"""
    models = _codex_app_server_models(path, cfg)
    if models is not None:
        return {"models": models, "models_source": "app_server", "models_message":
                "已从 Codex model/list 读取 %d 个模型。" % len(models)}

    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    top = re.split(r"^\s*\[", _read_text(os.path.join(home, "config.toml")), maxsplit=1, flags=re.M)[0]
    provider = re.search(r'^\s*model_provider\s*=\s*["\']([^"\']+)["\']', top, flags=re.M)
    # OpenAI 缓存不适用于自定义 provider；手填的模型名仍照常提交。
    overrides = re.search(r"^\s*(?:profile|model_catalog_json)\s*=", top, flags=re.M)
    provider_set = re.search(r"^\s*model_provider\s*=", top, flags=re.M)
    if not overrides and (not provider_set or (provider and provider.group(1) == "openai")):
        try:
            cache = json.loads(_read_text(os.path.join(home, "models_cache.json")) or "{}")
            if isinstance(cache, dict):
                models = _codex_model_items(cache.get("models"), cached=True,
                                            api_key=cfg.get("codex_source") == "api_key")
                if models:
                    fetched = cache.get("fetched_at")
                    return {"models": models, "models_source": "cache",
                            "models_fetched_at": fetched[:80] if isinstance(fetched, str) else "",
                            "models_message": "实时检索未完成，显示 Codex 本机缓存中的 %d 个模型。" % len(models)}
        except (OSError, ValueError):
            pass
    return {"models": [], "models_source": "unavailable", "models_message":
            "暂时没有读到模型目录。可点“重新检测”，或选“其他”填写模型名。"}


def pi_dir():
    return os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")


def pi_default_model():
    try:
        s = json.loads(_read_text(os.path.join(pi_dir(), "settings.json")) or "{}") or {}
    except ValueError:
        return ""
    if s.get("defaultModel"):
        return ("%s/%s" % (s["defaultProvider"], s["defaultModel"])) if s.get("defaultProvider") else s["defaultModel"]
    return ""


def pi_models(path):
    """pi --list-models 只列出已登录或已配置 Key 的模型。返回 [{provider, id, value}]。"""
    code, text = _run([path, "--list-models"], timeout=30, env=pi_env({}, path))
    if code != 0:
        return None
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] == "provider" or parts[0].startswith(("Warning", "No")):
            continue
        if not re.match(r"^[A-Za-z0-9._-]+$", parts[0]):
            continue
        out.append({"provider": parts[0], "id": parts[1], "value": "%s/%s" % (parts[0], parts[1])})
    return out


def _run(cmd, timeout=20, env=None, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return None, "超时"
    except OSError as e:
        return None, str(e)


def detect(cfg):
    """检测所有执行器。返回 {claude: {...}, codex: {...}}。"""
    out = {}
    c = _which(cfg.get("claude_path") or "claude")
    if not c:
        out["claude"] = {"found": False, "message": "没有安装。安装后在终端运行一次 claude 完成登录。"}
    else:
        code, text = _run([c, "--version"], timeout=15)
        info = {"found": True, "path": c, "version": text.strip().splitlines()[0] if text.strip() else ""}
        code, text = _run([c, "auth", "status"], timeout=15)
        info["logged_in"] = code == 0
        info["message"] = "已登录 Claude 账号。" if code == 0 else "已安装，但没有登录 Claude 账号（用第三方 API 时不需要登录）。"
        info["default_model"] = claude_default_model()
        out["claude"] = info
    x = _which(cfg.get("codex_path") or "codex")
    if not x:
        out["codex"] = {"found": False, "message": "没有安装。安装后在终端运行一次 codex 完成登录。"}
    else:
        code, text = _run([x, "--version"], timeout=15)
        info = {"found": True, "path": x, "version": text.strip().splitlines()[0] if text.strip() else ""}
        code, text = _run([x, "login", "status"], timeout=15)
        info["logged_in"] = code == 0
        first = text.strip().splitlines()[0] if text.strip() else ""
        info["message"] = ("已登录：%s" % first) if code == 0 else "已安装，但没有登录（也可以改用 OpenAI API Key）。"
        info["default_model"] = codex_default_model()
        info.update(codex_models(x, cfg))
        out["codex"] = info
    p = _which(cfg.get("pi_path") or "pi")
    if not p:
        out["pi"] = {"found": False, "message": "没有安装。安装：npm install -g @mariozechner/pi-coding-agent"}
    else:
        code, text = _run([p, "--version"], timeout=15, env=pi_env({}, p))
        info = {"found": True, "path": p, "version": _first_line(text)}
        models = pi_models(p)
        info["models"] = models or []
        info["logged_in"] = bool(models)
        info["default_model"] = pi_default_model()
        if models is None:
            info["message"] = "已安装，但读取模型列表失败。"
        elif not models:
            info["message"] = "已安装，但还没有可用的模型：在终端运行 pi，输入 /login 登录，或配置厂商的 API Key。"
        else:
            info["message"] = "可用模型 %d 个。" % len(models)
        out["pi"] = info
    return out


def ready_problem(cfg):
    """当前选择的执行器能否运行；不能时返回一句给用户的话。"""
    ex = cfg.get("executor")
    if ex == "claude":
        if not _which(cfg.get("claude_path") or "claude"):
            return "没有找到 Claude Code。到“设置”里检测，或换一种执行方式。"
        if cfg.get("claude_source") == "provider":
            if not cfg.get("provider_base_url") or not cfg.get("provider_model"):
                return "第三方 API 还没设置好接口地址和模型。"
            if not secrets.get_secret(provider_account(cfg.get("provider_id") or "custom")):
                return "还没有保存这个厂商的 API Key。"
    if ex == "codex":
        if not _which(cfg.get("codex_path") or "codex"):
            return "没有找到 Codex。到“设置”里检测，或换一种执行方式。"
        if cfg.get("codex_source") == "api_key" and not secrets.get_secret(OPENAI_ACCOUNT):
            return "还没有保存 OpenAI API Key。"
    if ex == "pi":
        if not _which(cfg.get("pi_path") or "pi"):
            return "没有找到 pi。到“设置”里检测，或换一种执行方式。"
    return None


# ------------------------------------------------------------------ 环境变量（凭据）

_CRED_VARS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
              "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
              "ANTHROPIC_SMALL_FAST_MODEL", "CODEX_API_KEY"]


def run_env(cfg):
    env = {k: v for k, v in os.environ.items() if k not in _CRED_VARS}
    ex = cfg.get("executor")
    if ex in AUTO_EXECUTORS:
        tool = _which(cfg.get(ex + "_path") or ex) or ""
        env = _tool_env(tool, env)
    if ex == "pi":
        env = pi_env(env)
    if ex == "claude" and cfg.get("claude_source") == "provider":
        key = secrets.get_secret(provider_account(cfg.get("provider_id") or "custom"))
        model = cfg.get("provider_model", "")
        env.update({
            "ANTHROPIC_BASE_URL": cfg.get("provider_base_url", ""),
            "ANTHROPIC_AUTH_TOKEN": key or "",
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": cfg.get("provider_small_model") or model,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        })
    if ex == "codex" and cfg.get("codex_source") == "api_key":
        env["CODEX_API_KEY"] = secrets.get_secret(OPENAI_ACCOUNT) or ""
    return env


# ------------------------------------------------------------------ Claude Code

def claude_command(cfg, stage, mode, prompt, session_id=None):
    _, _, defs = gate.stage_config()
    profile = "P3" if mode == "deploy" else defs[stage]["permission_profile"]
    base_tools = "Read,Glob,Grep,Write,Edit,TodoWrite"
    deny = list(DENY_ALWAYS)
    if profile == "P0":
        perm, tools = "dontAsk", base_tools
    elif profile == "P3":
        perm, tools = "acceptEdits", base_tools + ",Bash,WebFetch,WebSearch"
    else:
        perm = "acceptEdits"
        tools = base_tools + (",Bash" if cfg.get("allow_shell_in_build", True) else "")
    if profile != "P3":
        deny += ["Bash(vefaas deploy *)", "Bash(vefaas login *)"]
    cmd = [cfg.get("claude_path") or "claude", "--output-format", "stream-json", "--verbose",
           "--permission-mode", perm, "--allowedTools", tools, "--add-dir", SKILLS_ROOT]
    if cfg.get("claude_source") != "provider":
        cmd += ["--max-budget-usd", str(float(cfg.get("budget_per_run_usd") or 3.0))]
        if cfg.get("model"):
            cmd += ["--model", cfg["model"]]
    else:
        cmd += ["--model", cfg.get("provider_model", "")]
    if session_id:
        cmd += ["--resume", session_id]
    cmd += ["--disallowedTools", *deny]
    cmd += ["-p", prompt]
    return cmd


def claude_tool_text(name, inp):
    inp = inp or {}
    fp = inp.get("file_path") or inp.get("path") or ""
    if name == "Read":
        return "读取 " + os.path.basename(fp)
    if name == "Write":
        return "写入 " + fp
    if name in ("Edit", "MultiEdit"):
        return "修改 " + fp
    if name == "Bash":
        cmd = (inp.get("command") or "").strip().replace("\n", " ")
        return "运行命令：" + cmd[:90] + ("…" if len(cmd) > 90 else "")
    if name in ("Glob", "Grep"):
        return "查找文件"
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "更新任务清单"
    if name == "WebFetch":
        return "查阅网页 " + str(inp.get("url", ""))[:80]
    if name == "WebSearch":
        return "搜索：" + str(inp.get("query", ""))[:60]
    if name == "Skill":
        return "加载 Skill " + str(inp.get("skill", ""))
    return "使用工具 " + name


# ------------------------------------------------------------------ Codex

def codex_command(cfg, stage, mode, prompt, cwd):
    _, _, defs = gate.stage_config()
    profile = "P3" if mode == "deploy" else defs[stage]["permission_profile"]
    cmd = [cfg.get("codex_path") or "codex", "exec", "--json", "--skip-git-repo-check",
           "--sandbox", "workspace-write", "--cd", cwd]
    if profile in ("P2", "P3"):
        cmd += ["-c", "sandbox_workspace_write.network_access=true"]
    if cfg.get("codex_model"):
        cmd += ["--model", cfg["codex_model"]]
    cmd += [prompt]
    return cmd


def codex_event(ev, run):
    """把 Codex 的一条 JSON 事件翻译成进度；返回 ('result', ok, message) 或 None。"""
    typ = ev.get("type")
    if typ == "thread.started":
        run.session_id = ev.get("thread_id")
        return None
    if typ in ("item.started", "item.completed"):
        it = ev.get("item") or {}
        kind = it.get("type")
        if kind == "command_execution" and typ == "item.started":
            cmd = str(it.get("command") or "").replace("\n", " ")
            run.emit("tool", "运行命令：" + cmd[:90] + ("…" if len(cmd) > 90 else ""))
        elif kind == "command_execution" and typ == "item.completed" and it.get("exit_code") not in (0, None):
            run.emit("warn", "命令退出码 %s" % it.get("exit_code"))
        elif kind == "file_change" and typ == "item.completed":
            for ch in it.get("changes") or []:
                verb = {"add": "写入", "delete": "删除", "update": "修改"}.get(ch.get("kind"), "修改")
                run.emit("tool", "%s %s" % (verb, ch.get("path", "")))
        elif kind == "agent_message" and typ == "item.completed":
            txt = str(it.get("text") or "").strip().replace("\n", " ")
            if txt:
                run.emit("text", txt[:200] + ("…" if len(txt) > 200 else ""))
        elif kind == "web_search" and typ == "item.started":
            run.emit("tool", "搜索：" + str(it.get("query", ""))[:60])
        elif kind == "todo_list" and typ == "item.completed":
            run.emit("tool", "更新任务清单")
        elif kind == "mcp_tool_call" and typ == "item.started":
            run.emit("tool", "使用工具 %s.%s" % (it.get("server", ""), it.get("tool", "")))
        elif kind == "error":
            run.emit("warn", str(it.get("message", ""))[:200])
        return None
    if typ == "turn.completed":
        u = ev.get("usage") or {}
        tok = run.tokens or {"input": 0, "output": 0}
        tok["input"] += int(u.get("input_tokens") or 0)
        tok["output"] += int(u.get("output_tokens") or 0) + int(u.get("reasoning_output_tokens") or 0)
        run.tokens = tok
        return ("result", True, "")
    if typ == "turn.failed":
        return ("result", False, str((ev.get("error") or {}).get("message", "Codex 运行失败")))
    if typ == "error":
        run.emit("warn", str(ev.get("message", ""))[:200])
    return None


# ------------------------------------------------------------------ pi

def pi_env(env, path=None):
    env = dict(env) if env else {k: v for k, v in os.environ.items() if k not in _CRED_VARS}
    if path:
        env = _tool_env(path, env)
    env.update({"PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"})
    return env


PI_READ_TOOLS = "read,write,edit,grep,find,ls"


def pi_command(cfg, stage, mode, prompt, session_id=None):
    """pi 没有沙箱，只能用工具白名单控制：需求、架构、选型阶段不给 bash。"""
    _, _, defs = gate.stage_config()
    profile = "P3" if mode == "deploy" else defs[stage]["permission_profile"]
    tools = PI_READ_TOOLS
    if profile == "P3" or (profile in ("P1", "P2") and cfg.get("allow_shell_in_build", True)):
        tools += ",bash"
    cmd = [cfg.get("pi_path") or "pi", "--mode", "json", "--tools", tools, "--skill", SKILLS_ROOT]
    if cfg.get("pi_model"):
        cmd += ["--model", cfg["pi_model"]]
    if cfg.get("pi_thinking") in PI_THINKING:
        cmd += ["--thinking", cfg["pi_thinking"]]
    if session_id:
        cmd += ["--session", session_id]
    cmd += [prompt]
    return cmd


def pi_tool_text(name, args):
    args = args or {}
    fp = args.get("path") or args.get("file_path") or ""
    if name == "read":
        return "读取 " + os.path.basename(fp)
    if name == "write":
        return "写入 " + fp
    if name == "edit":
        return "修改 " + fp
    if name == "bash":
        cmd = str(args.get("command") or "").strip().replace("\n", " ")
        return "运行命令：" + cmd[:90] + ("…" if len(cmd) > 90 else "")
    if name in ("grep", "find", "ls"):
        return "查找文件"
    return "使用工具 " + name


def pi_event(ev, run):
    """翻译 pi --mode json 的一条事件。pi 在模型报错时退出码仍为 0，所以要记下最后一条助手消息的状态。
    返回 ('result', ok, message) 或 None。"""
    typ = ev.get("type")
    if typ == "session":
        run.session_id = ev.get("id") or run.session_id
        return None
    if typ == "tool_execution_start":
        run.emit("tool", pi_tool_text(ev.get("toolName", ""), ev.get("args")))
        return None
    if typ == "tool_execution_end" and ev.get("isError"):
        run.emit("warn", "%s 执行出错" % ev.get("toolName", "工具"))
        return None
    if typ == "auto_retry_start":
        run.emit("warn", "模型服务暂时不可用，正在重试（第 %s 次）" % ev.get("attempt"))
        return None
    if typ == "message_end":
        m = ev.get("message") or {}
        if m.get("role") != "assistant":
            return None
        if not getattr(run, "model_announced", False) and m.get("model"):
            run.model_announced = True
            run.emit("info", "模型：%s/%s" % (m.get("provider", ""), m.get("model")))
        for block in m.get("content") or []:
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                txt = block["text"].strip().replace("\n", " ")
                run.emit("text", txt[:200] + ("…" if len(txt) > 200 else ""))
        u = m.get("usage") or {}
        if u:
            tok = run.tokens or {"input": 0, "output": 0}
            tok["input"] += int(u.get("input") or 0) + int(u.get("cacheRead") or 0)
            tok["output"] += int(u.get("output") or 0)
            run.tokens = tok
        if m.get("stopReason") in ("error", "aborted"):
            return ("result", False, str(m.get("errorMessage") or "模型调用失败"))
        return ("result", True, "")
    return None


# ------------------------------------------------------------------ 连接测试

def test_connection(cfg):
    """用一个极小的任务实际调用一次模型。会产生极少量费用。"""
    prob = ready_problem(cfg)
    if prob:
        return {"ok": False, "message": prob}
    ex = cfg.get("executor")
    tmp = tempfile.mkdtemp(prefix="pf-test-")
    try:
        env = run_env(cfg)
        if ex == "claude":
            cmd = [cfg.get("claude_path") or "claude", "--output-format", "json", "--max-turns", "1",
                   "--permission-mode", "dontAsk", "--tools", ""]
            if cfg.get("claude_source") == "provider":
                cmd += ["--model", cfg.get("provider_model", "")]
            elif cfg.get("model"):
                cmd += ["--model", cfg["model"]]
            cmd += ["-p", "只回复两个字母：OK"]
            code, text = _run(cmd, timeout=120, env=env, cwd=tmp)
            try:
                data = json.loads(text.strip().splitlines()[-1])
            except (ValueError, IndexError):
                data = {}
            if code == 0 and not data.get("is_error"):
                return {"ok": True, "message": "连接成功，模型回复：%s" % str(data.get("result", "")).strip()[:40]}
            return {"ok": False, "message": "连接失败：%s" % (str(data.get("result") or text).strip()[:300])}
        if ex == "codex":
            cmd = [cfg.get("codex_path") or "codex", "exec", "--json", "--skip-git-repo-check", "--sandbox",
                   "read-only", "--cd", tmp]
            if cfg.get("codex_model"):
                cmd += ["--model", cfg["codex_model"]]
            cmd += ["只回复两个字母：OK"]
            code, text = _run(cmd, timeout=120, env=env, cwd=tmp)
            msg, failed = "", None
            for line in text.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                    msg = ev["item"].get("text", "")
                if ev.get("type") in ("turn.failed", "error"):
                    failed = str((ev.get("error") or {}).get("message") or ev.get("message"))
            if code == 0 and not failed:
                return {"ok": True, "message": "连接成功，模型回复：%s" % msg.strip()[:40]}
            return {"ok": False, "message": "连接失败：%s" % (failed or text.strip()[:300])}
        if ex == "pi":
            cmd = [cfg.get("pi_path") or "pi", "--mode", "json", "--no-tools", "--no-session", "--no-skills"]
            if cfg.get("pi_model"):
                cmd += ["--model", cfg["pi_model"]]
            cmd += ["只回复两个字母：OK"]
            code, text = _run(cmd, timeout=120, env=env, cwd=tmp)
            last = None
            for line in text.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
                    last = ev["message"]
            if code == 0 and last and last.get("stopReason") not in ("error", "aborted"):
                reply = "".join(b.get("text", "") for b in last.get("content") or [] if b.get("type") == "text")
                return {"ok": True, "message": "连接成功（%s/%s），模型回复：%s" % (
                    last.get("provider", ""), last.get("model", ""), reply.strip()[:40])}
            err = (last or {}).get("errorMessage") or _first_line(text) or "pi 退出码 %s" % code
            return {"ok": False, "message": "连接失败：%s" % str(err)[:300]}
        return {"ok": True, "message": "这种方式不需要测试连接。"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
