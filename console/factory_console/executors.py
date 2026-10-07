"""AI 执行器：Claude Code（官方账号或第三方兼容 API）、Codex（ChatGPT 账号或 OpenAI API Key）。

负责：检测安装与登录、按阶段权限拼命令、注入凭据环境变量、把事件流翻译成界面上的进度。
"""

import json
import os
import shutil
import subprocess
import tempfile

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
    return {"demo": "演示模式", "manual": "复制指令"}.get(ex, ex)


# ------------------------------------------------------------------ 检测

def _which(path):
    if not path:
        return None
    found = shutil.which(path)
    if found:
        return found
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


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
        out["codex"] = info
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
    return None


# ------------------------------------------------------------------ 环境变量（凭据）

_CRED_VARS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
              "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
              "ANTHROPIC_SMALL_FAST_MODEL", "CODEX_API_KEY"]


def run_env(cfg):
    env = {k: v for k, v in os.environ.items() if k not in _CRED_VARS}
    ex = cfg.get("executor")
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
        return {"ok": True, "message": "这种方式不需要测试连接。"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
