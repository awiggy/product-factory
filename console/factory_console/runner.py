"""AI 运行管理：生成阶段提示、调用执行器（Claude Code / 手动 / 演示）、记录进度、运行结束后吸收结果。"""

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid

from . import INBOX_PROTOCOL, SKILLS_ROOT
from . import executors as ex
from . import gate
from . import inbox as ib
from . import products as pr

_active = {}            # pid -> Run
_active_lock = threading.Lock()

MODES = {
    "start": "开始本阶段工作。",
    "continue": "继续本阶段工作：先读取下方用户的新输入，再接着做。",
    "fix": "修复用户验收时发现的问题，修完后给出新一轮验收清单。",
    "deploy": "用户已授权部署。在授权范围内执行部署并逐项验证。",
}

PROFILE_TEXT = {
    "P0": "只读：可以读需求、代码与资料，只写 factory/ 下的文档；不改代码、不调用付费模型、不访问外部系统。",
    "P1": "工作区写：可以修改本产品仓库的代码与文档、运行本地测试；不调用付费服务、不碰云资源。",
    "P2": "真实冒烟：在 P1 基础上，可以在预算内调用 .env 中已配置的真实模型/测试接口。",
    "P3": "发布：在用户授权的平台、环境、费用与公开范围内操作云平台；超出范围的操作必须停下来写进收件箱。",
}


def _now_iso():
    return gate.fg.now()


class Run:
    def __init__(self, pid, pdir, stage, mode, executor):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.pid, self.pdir, self.stage, self.mode, self.executor = pid, pdir, stage, mode, executor
        self.status = "running"
        self.started = _now_iso()
        self.started_ts = time.time()
        self.ended = None
        self.cost_usd = None
        self.tokens = None
        self.cost_note = ""
        self.executor_label = ""
        self.session_id = None
        self.error = None
        self.notes = []
        self.activity = []
        self.prompt = ""
        self.proc = None
        self.stop_requested = False
        self.state_snapshot = None
        self.lock = threading.Lock()

    def emit(self, kind, text):
        with self.lock:
            self.activity.append({"t": _now_iso(), "kind": kind, "text": text})

    def meta(self, with_activity=True, since=0):
        m = {"id": self.id, "stage": self.stage, "mode": self.mode, "executor": self.executor,
             "status": self.status, "started": self.started, "ended": self.ended,
             "cost_usd": self.cost_usd, "tokens": self.tokens, "cost_note": self.cost_note,
             "executor_label": self.executor_label, "session_id": self.session_id, "error": self.error,
             "notes": self.notes}
        if with_activity:
            with self.lock:
                m["activity"] = self.activity[since:]
                m["activity_total"] = len(self.activity)
        if self.executor == "manual":
            m["prompt"] = self.prompt
        return m

    def save(self):
        d = pr.runs_dir(self.pdir)
        os.makedirs(d, exist_ok=True)
        m = self.meta()
        m["prompt"] = self.prompt
        ib.write_json(os.path.join(d, self.id + ".json"), m)


# ------------------------------------------------------------------ 提示

def build_prompt(pdir, stage, mode):
    state = gate.load_state(pdir)
    cfg, order, defs = gate.stage_config()
    d = defs[stage]
    profile = "P3" if mode == "deploy" else d["permission_profile"]
    box, _ = pr.read_inbox(pdir, stage)
    answers, checks, actions_done, feedback = pr.user_inputs(pdir, stage, box)
    lines = [
        "你在「AI 产品工厂」控制台中执行一个阶段。",
        "产品：%s（v%d）。阶段：%s（%s）。工作目录是产品仓库根目录。"
        % (state["product"]["name"], state["product"]["version"], d["title"], stage),
        "",
        "## 先读这些文件",
        "- 阶段 Skill：%s（以及它按需引用的文件）" % os.path.join(SKILLS_ROOT, d["skill"], "SKILL.md"),
        "- 工厂交接约定：%s" % os.path.join(SKILLS_ROOT, "product-factory", "references", "handoff-conventions.md"),
        "- 收件箱协议（必须遵守）：%s" % INBOX_PROTOCOL,
        "",
        "## 本阶段要求",
        "- 交接物：%s。从 Skill 的模板起稿时，写完要删除首行 %s。" % ("、".join(d["artifacts"]), gate.TEMPLATE_MARKER),
        "- 闸门最低证据等级：%s。" % d["min_evidence"],
        "- 权限档位 %s：%s" % (profile, PROFILE_TEXT[profile]),
        "",
        "## 控制台模式的规则",
        "- 你无法和用户对话。需要用户回答的问题、需要用户本人完成的操作、验收清单、审批摘要，全部写进 "
        "factory/inbox/%s.json，然后结束本次运行。" % stage,
        "- 本次收件箱的 round 写 %d。" % ((box["round"] + 1) if box else 1),
        "- 不要修改 factory/state.json，不要运行 factory_gate.py 的 approve、waive、advance、iterate、blocker、evidence；"
        "证据和阻塞写进收件箱，由控制台记录。",
        "- 不在任何文件、日志或输出中写入密钥值。",
        "- 每轮最多问 3 个问题；已经回答过的问题不要再问。",
        "",
        "## 本次任务",
        MODES.get(mode, MODES["continue"]),
    ]
    if stage == "prd":
        idea = os.path.join(pdir, "factory", "idea.md")
        if os.path.exists(idea):
            with open(idea, encoding="utf-8") as f:
                lines += ["", "## 用户的产品想法（factory/idea.md）", f.read().strip()]
        if state["product"]["version"] > 1:
            lines += ["", "这是 v%d：使用 prd-author 的变更模式，基于 factory/feedback.md 与上一版 PRD 修订。"
                      % state["product"]["version"], "阶段备注：" + state["stages"][stage].get("notes", "")]
    hist = pr.qa_history(pdir, stage)
    if hist:
        lines += ["", "## 用户已回答的问题"]
        for h in hist:
            a = h["answer"] if isinstance(h["answer"], str) else "、".join(h["answer"])
            lines.append("- 问：%s\n  答：%s" % (h["question"], a))
    if box and box["user_actions"]:
        done = [a["title"] for a in box["user_actions"] if a["id"] in actions_done]
        todo = [a["title"] for a in box["user_actions"] if a["id"] not in actions_done]
        if done:
            lines += ["", "## 用户已完成的操作", *["- " + t for t in done]]
        if todo:
            lines += ["", "## 用户尚未完成的操作", *["- " + t for t in todo]]
    if box and box["checklist"] and checks:
        lines += ["", "## 上一轮验收结果"]
        for c in box["checklist"]:
            r = checks.get(c["id"])
            if r:
                lines.append("- [%s] %s → 预期：%s%s" % ("通过" if r["result"] == "pass" else "不通过", c["do"],
                                                        c["expect"], "；用户说明：" + r["note"] if r["note"] else ""))
    if feedback:
        lines += ["", "## 用户反馈（优先处理）"]
        for f in feedback:
            label = {"revise": "要求修改", "question": "提问（在收件箱 summary 里回答，不必修改文件）",
                     "info": "补充信息"}[f["kind"]]
            lines.append("- %s：%s" % (label, f["text"]))
    probs = [p for p in gate.problems(pdir, state, stage) if not pr._is_approval_problem(p)]
    if probs:
        lines += ["", "## 闸门检查目前未通过的项目（需要你处理的）", *["- " + p for p in probs]]
    if mode == "deploy":
        scope = next((a.get("scope", "") for a in state.get("approvals", [])
                      if a["id"] == "release_go" and a.get("product_version") == state["product"]["version"]), "")
        lines += ["", "## 部署授权范围", scope or "（未写明，停止并在收件箱说明）"]
    return "\n".join(lines)


# ------------------------------------------------------------------ 执行器：Claude Code

def _sessions_path(pdir):
    return os.path.join(pr.runs_dir(pdir), "sessions.json")


def _run_claude(run, cfg):
    sessions = ib.read_json(_sessions_path(run.pdir), {}) or {}
    sid = sessions.get(run.stage) if run.mode != "start" else None
    for attempt in (1, 2):
        cmd = ex.claude_command(cfg, run.stage, run.mode, run.prompt, sid)
        run.emit("info", "启动 Claude Code" + ("（接着上次的对话）" if sid else ""))
        try:
            run.proc = subprocess.Popen(cmd, cwd=run.pdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, bufsize=1, start_new_session=True, env=ex.run_env(cfg))
        except FileNotFoundError:
            raise RuntimeError("找不到 Claude Code（%s）。到“设置”里检测，或换一种执行方式。" % cmd[0])
        stderr_lines = []
        t = threading.Thread(target=lambda: stderr_lines.extend(run.proc.stderr.readlines()), daemon=True)
        t.start()
        result = None
        raw_path = os.path.join(pr.runs_dir(run.pdir), run.id + ".jsonl")
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with open(raw_path, "a", encoding="utf-8") as raw:
            for line in run.proc.stdout:
                raw.write(line)
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                typ = ev.get("type")
                if typ == "system" and ev.get("subtype") == "init":
                    run.session_id = ev.get("session_id")
                    run.emit("info", "模型：%s" % ev.get("model", ""))
                elif typ == "system" and ev.get("subtype") == "api_retry":
                    run.emit("warn", "模型服务暂时不可用，正在重试（第 %s 次）" % ev.get("attempt"))
                elif typ == "assistant":
                    for block in (ev.get("message") or {}).get("content", []):
                        if block.get("type") == "tool_use":
                            run.emit("tool", ex.claude_tool_text(block.get("name", ""), block.get("input")))
                        elif block.get("type") == "text" and block.get("text", "").strip():
                            txt = block["text"].strip().replace("\n", " ")
                            run.emit("text", txt[:200] + ("…" if len(txt) > 200 else ""))
                elif typ == "result":
                    result = ev
        run.proc.wait()
        t.join(timeout=2)
        for stream in (run.proc.stdout, run.proc.stderr):
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
        if result:
            run.session_id = result.get("session_id") or run.session_id
            if result.get("total_cost_usd") is not None and cfg.get("claude_source") != "provider":
                run.cost_usd = round((run.cost_usd or 0) + float(result["total_cost_usd"]), 4)
            u = result.get("usage") or {}
            if u:
                tok = run.tokens or {"input": 0, "output": 0}
                tok["input"] += int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
                tok["output"] += int(u.get("output_tokens") or 0)
                run.tokens = tok
            for den in result.get("permission_denials") or []:
                run.emit("warn", "被拦截的操作：%s" % ex.claude_tool_text(den.get("tool_name", ""), den.get("tool_input")))
        err_text = "".join(stderr_lines).strip()
        if run.stop_requested:
            return
        bad_resume = sid and ("No conversation found" in err_text or
                              (result and result.get("is_error") and "conversation" in str(result.get("result", ""))))
        if bad_resume and attempt == 1:
            run.emit("info", "上次的对话已不可用，改为新开对话")
            sid = None
            continue
        if run.session_id:
            sessions[run.stage] = run.session_id
            ib.write_json(_sessions_path(run.pdir), sessions)
        if run.proc.returncode != 0 or (result and result.get("is_error")):
            msg = (result or {}).get("result") or err_text or "Claude Code 退出码 %s" % run.proc.returncode
            sub = (result or {}).get("subtype", "")
            if "budget" in str(sub) or "budget" in str(msg).lower():
                msg = "达到单次运行预算上限（%s 美元），已停止。可在设置里调整预算后继续。" % cfg.get("budget_per_run_usd")
            raise RuntimeError(str(msg)[:600])
        return


def _run_codex(run, cfg):
    cmd = ex.codex_command(cfg, run.stage, run.mode, run.prompt, run.pdir)
    run.emit("info", "启动 Codex")
    try:
        run.proc = subprocess.Popen(cmd, cwd=run.pdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, bufsize=1, start_new_session=True, env=ex.run_env(cfg))
    except FileNotFoundError:
        raise RuntimeError("找不到 Codex（%s）。到“设置”里检测，或换一种执行方式。" % cmd[0])
    stderr_lines = []
    t = threading.Thread(target=lambda: stderr_lines.extend(run.proc.stderr.readlines()), daemon=True)
    t.start()
    outcome = None
    raw_path = os.path.join(pr.runs_dir(run.pdir), run.id + ".jsonl")
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)
    with open(raw_path, "a", encoding="utf-8") as raw:
        for line in run.proc.stdout:
            raw.write(line)
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            r = ex.codex_event(evt, run)
            if r:
                outcome = r
    run.proc.wait()
    t.join(timeout=2)
    for stream in (run.proc.stdout, run.proc.stderr):
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass
    if run.stop_requested:
        return
    if run.proc.returncode != 0 or (outcome and not outcome[1]):
        msg = (outcome[2] if outcome and not outcome[1] else "") or "".join(stderr_lines).strip()[-600:] \
            or "Codex 退出码 %s" % run.proc.returncode
        raise RuntimeError(msg)


# ------------------------------------------------------------------ 运行生命周期

def active(pid):
    with _active_lock:
        r = _active.get(pid)
    return r


def active_meta(pid):
    r = active(pid)
    if r and r.status in ("running", "waiting_manual"):
        return {"id": r.id, "status": r.status, "stage": r.stage, "mode": r.mode, "executor": r.executor}
    return None


def start(pid, mode="continue"):
    item = pr.find(pid)
    pdir = item["path"]
    cfg = pr.load_config()
    if mode not in MODES:
        raise pr.UserError("未知的运行方式：%s" % mode)
    with _active_lock:
        cur = _active.get(pid)
        if cur and cur.status in ("running", "waiting_manual"):
            raise pr.UserError("AI 正在处理这个产品，等它完成后再开始新的任务。", 409)
        state = gate.load_state(pdir)
        stage = state["current_stage"]
        if mode == "deploy" and not gate.has_approval(state, "release_go"):
            raise pr.UserError("还没有授权部署。", 403)
        executor = "demo" if item.get("demo") else cfg.get("executor", "demo")
        if executor in ("claude", "codex"):
            prob = ex.ready_problem(cfg)
            if prob:
                raise pr.UserError(prob)
        run = Run(pid, pdir, stage, mode, executor)
        run.executor_label = "演示模式" if executor == "demo" else ex.label(cfg)
        if executor == "claude" and cfg.get("claude_source") == "provider":
            run.cost_note = "第三方模型的费用以厂商账单为准"
        _active[pid] = run
    try:
        run.prompt = build_prompt(pdir, stage, mode)
        used = pr.consume_feedback(pdir, stage, run.id)
        if used:
            run.emit("info", "附上了你的 %d 条反馈" % len(used))
        with open(gate.fg.state_path(pdir), "rb") as f:
            run.state_snapshot = f.read()
    except Exception:
        with _active_lock:
            _active.pop(pid, None)
        raise
    if executor == "manual":
        run.prompt = "请在这个产品文件夹里工作：%s\n（如果你的 AI 助手支持 Skill，Skill 文件在 %s）\n\n%s" % (
            pdir, SKILLS_ROOT, run.prompt)
        run.status = "waiting_manual"
        run.emit("info", "已生成指令，等待你在 AI 助手里执行")
        run.save()
        return run.meta()
    threading.Thread(target=_worker, args=(run, cfg), daemon=True).start()
    if executor in ("claude", "codex"):
        threading.Thread(target=_watchdog, args=(run, float(cfg.get("max_minutes_per_run") or 45)), daemon=True).start()
    run.save()
    return run.meta()


def _watchdog(run, minutes):
    deadline = time.time() + minutes * 60
    while run.status == "running" and time.time() < deadline:
        time.sleep(2)
    if run.status == "running":
        run.emit("warn", "超过 %d 分钟，已停止本次运行" % minutes)
        _terminate(run)


def _terminate(run):
    run.stop_requested = True
    p = run.proc
    if p and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGINT)
        except (OSError, AttributeError):
            p.send_signal(signal.SIGINT)
        for _ in range(10):
            if p.poll() is not None:
                return
            time.sleep(0.5)
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (OSError, AttributeError):
            p.terminate()


def _worker(run, cfg):
    try:
        if run.executor == "claude":
            _run_claude(run, cfg)
        elif run.executor == "codex":
            _run_codex(run, cfg)
        else:
            from . import demo
            demo.run(run)
        if run.stop_requested:
            run.status = "stopped"
            run.emit("warn", "已停止")
        else:
            run.status = "succeeded"
    except Exception as e:  # noqa: BLE001
        run.status = "failed"
        run.error = str(e)
        run.emit("error", str(e))
    finally:
        _finish(run)


def _finish(run):
    with gate.lock_for(run.pdir):
        sp = gate.fg.state_path(run.pdir)
        try:
            with open(sp, "rb") as f:
                now_bytes = f.read()
        except OSError:
            now_bytes = None
        if run.state_snapshot is not None and now_bytes != run.state_snapshot:
            with open(sp, "wb") as f:
                f.write(run.state_snapshot)
            run.notes.append("AI 改动了 factory/state.json，已恢复（状态只能由控制台修改）。")
            run.emit("warn", "AI 改动了状态文件，已恢复")
        try:
            run.notes += pr.ingest(run.pdir, run.stage, run.started_ts, deploy_mode=(run.mode == "deploy"))
        except Exception as e:  # noqa: BLE001
            run.notes.append("吸收结果时出错：%s" % e)
    run.ended = _now_iso()
    run.emit("done", {"succeeded": "本次运行完成", "failed": "本次运行失败", "stopped": "已停止"}.get(run.status, "结束"))
    run.save()


def stop(pid):
    run = active(pid)
    if not run or run.status not in ("running", "waiting_manual"):
        raise pr.UserError("现在没有正在进行的任务。")
    if run.status == "waiting_manual":
        run.stop_requested = True
        run.status = "stopped"
        _finish(run)
        return
    run.emit("info", "正在停止…")
    threading.Thread(target=_terminate, args=(run,), daemon=True).start()


def manual_done(pid):
    run = active(pid)
    if not run or run.status != "waiting_manual":
        raise pr.UserError("没有等待中的手动任务。")
    run.status = "succeeded"
    run.emit("info", "你确认 AI 助手已执行完毕")
    _finish(run)
    return run.meta()


def get_run(pid, run_id, since=0):
    run = active(pid)
    if run and run.id == run_id:
        return run.meta(since=since)
    pdir = pr.find(pid)["path"]
    m = ib.read_json(os.path.join(pr.runs_dir(pdir), run_id + ".json"))
    if not m:
        raise pr.UserError("找不到这次运行记录。", 404)
    m["activity_total"] = len(m.get("activity", []))
    m["activity"] = m.get("activity", [])[since:]
    if m.get("executor") != "manual":
        m.pop("prompt", None)
    return m


def busy(pid):
    r = active(pid)
    return bool(r and r.status in ("running", "waiting_manual"))
