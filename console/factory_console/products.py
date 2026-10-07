"""产品注册、详情汇总、下一步判断，以及 AI 运行结束后的收件箱吸收。"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading

from . import DATA_ROOT, PACKAGE_ROOT
from . import gate
from . import inbox as ib

GUIDES_PATH = os.path.join(os.path.dirname(__file__), "guides.json")
CONFIG_PATH = os.path.join(DATA_ROOT, "config.json")
_cfg_lock = threading.Lock()

DEFAULT_CONFIG = {
    "user_name": "",
    "executor": "demo",          # demo | claude | codex | pi | manual
    "claude_path": "claude",
    "model": "",
    "claude_source": "account",  # account（Claude 账号）| provider（第三方兼容 API）
    "provider_id": "deepseek",
    "provider_base_url": "https://api.deepseek.com/anthropic",
    "provider_model": "deepseek-v4-pro",
    "provider_small_model": "",
    "codex_path": "codex",
    "codex_source": "account",   # account（ChatGPT 登录）| api_key（OpenAI API Key）
    "codex_model": "",
    "pi_path": "pi",
    "pi_model": "",              # provider/model，留空用 pi 自己的默认
    "pi_thinking": "",           # 留空用默认；off | minimal | low | medium | high | xhigh
    "budget_per_run_usd": 3.0,
    "max_minutes_per_run": 45,
    "allow_shell_in_build": True,
    "workspace": os.path.join(PACKAGE_ROOT, "products"),
    "products": [],
}


class UserError(Exception):
    """可以直接展示给用户的错误。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def guides():
    with open(GUIDES_PATH, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ 配置

def load_config():
    with _cfg_lock:
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(ib.read_json(CONFIG_PATH, {}) or {})
        return cfg


def save_config(cfg):
    with _cfg_lock:
        ib.write_json(CONFIG_PATH, cfg)


def update_config(changes):
    cfg = load_config()
    allowed = {"user_name", "executor", "claude_path", "model", "budget_per_run_usd",
               "max_minutes_per_run", "allow_shell_in_build", "workspace", "claude_source", "provider_id",
               "provider_base_url", "provider_model", "provider_small_model", "codex_path", "codex_source",
               "codex_model", "pi_path", "pi_model", "pi_thinking"}
    for k, v in changes.items():
        if k not in allowed:
            continue
        if isinstance(v, str):
            v = v.strip()
        if k == "executor" and v not in ("demo", "claude", "codex", "pi", "manual"):
            raise UserError("执行方式无效")
        if k == "claude_source" and v not in ("account", "provider"):
            raise UserError("Claude Code 的模型来源无效")
        if k == "codex_source" and v not in ("account", "api_key"):
            raise UserError("Codex 的登录方式无效")
        if k == "pi_thinking" and v not in ("", "off", "minimal", "low", "medium", "high", "xhigh"):
            raise UserError("思考强度无效")
        if k in ("model", "codex_model", "pi_model", "provider_model", "provider_small_model") and v \
                and not re.match(r"^[A-Za-z0-9._:/\[\]@+-]{1,120}$", v):
            raise UserError("模型名只能包含字母、数字和 . _ - / : 等符号")
        if k == "provider_base_url" and v and not re.match(r"^https://[^\s]+$", v):
            raise UserError("接口地址需要以 https:// 开头")
        if k in ("budget_per_run_usd", "max_minutes_per_run"):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise UserError("%s 需要是数字" % k)
            if v <= 0:
                raise UserError("%s 需要大于 0" % k)
        cfg[k] = v
    save_config(cfg)
    return cfg


# ------------------------------------------------------------------ 注册

def product_id(path):
    return hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:10]


def registry():
    cfg = load_config()
    out = []
    for item in cfg.get("products", []):
        if os.path.exists(os.path.join(item["path"], "factory", "state.json")):
            out.append(item)
    return out


def find(pid):
    for item in registry():
        if item["id"] == pid:
            return item
    raise UserError("找不到这个产品，它的文件夹可能已被移动或删除。", 404)


def _register(path, demo=False):
    cfg = load_config()
    pid = product_id(path)
    items = [p for p in cfg.get("products", []) if p["id"] != pid]
    items.insert(0, {"id": pid, "path": os.path.abspath(path), "demo": bool(demo)})
    cfg["products"] = items
    save_config(cfg)
    return pid


def _safe_dirname(name):
    n = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name).strip().strip(".")
    return n[:60] or "新产品"


def create_product(name, idea, notes="", path=None, demo=False):
    name = (name or "").strip()
    idea = (idea or "").strip()
    if not name:
        raise UserError("给产品起个名字，方便以后找到它。")
    if not idea and not demo:
        raise UserError("用一两句话说说你想做什么，AI 会从这里开始提问。")
    cfg = load_config()
    if path:
        target = os.path.abspath(os.path.expanduser(path))
    else:
        base = os.path.join(cfg["workspace"], _safe_dirname(name))
        target, n = base, 2
        while os.path.exists(target):
            target = "%s-%d" % (base, n)
            n += 1
    if os.path.exists(os.path.join(target, "factory", "state.json")):
        raise UserError("这个文件夹里已经有工厂记录了，请用“打开已有产品”。")
    if os.path.isdir(target) and os.listdir(target) and not path:
        raise UserError("文件夹 %s 已存在且不为空。" % target)
    os.makedirs(target, exist_ok=True)
    if shutil.which("git") and not os.path.exists(os.path.join(target, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=target, capture_output=True)
    gi = os.path.join(target, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write(".env\n.DS_Store\n__pycache__/\n.venv/\nnode_modules/\nfactory/runs/\n")
    gate.must(["init", target, "--name", name])
    with open(os.path.join(target, "factory", "idea.md"), "w", encoding="utf-8") as f:
        f.write("# 产品想法\n\n%s\n" % (idea or "（演示产品）"))
        if notes.strip():
            f.write("\n## 补充材料\n\n%s\n" % notes.strip())
    os.makedirs(ib.inbox_dir(target), exist_ok=True)
    return _register(target, demo=demo)


def import_product(path):
    target = os.path.abspath(os.path.expanduser(path or ""))
    if not os.path.isdir(target):
        raise UserError("找不到文件夹：%s" % target)
    if not os.path.exists(os.path.join(target, "factory", "state.json")):
        raise UserError("这个文件夹里没有 factory/state.json。新产品请用“新建产品”。")
    gate.load_state(target)
    return _register(target)


def forget_product(pid):
    cfg = load_config()
    cfg["products"] = [p for p in cfg.get("products", []) if p["id"] != pid]
    save_config(cfg)


# ------------------------------------------------------------------ 收件箱相关读取

def _round_key(box):
    return str(box["round"]) if box else "0"


def read_inbox(pdir, stage):
    raw = ib.read_json(ib.path(pdir, stage))
    if raw is None:
        if os.path.exists(ib.path(pdir, stage)):
            return None, ["收件箱文件不是合法 JSON，请让 AI 重新生成"]
        return None, []
    return ib.normalize(raw, stage)


def user_inputs(pdir, stage, box):
    rk = _round_key(box)
    answers = (ib.read_json(ib.path(pdir, stage, ".answers"), {}) or {}).get(rk, {})
    checks = (ib.read_json(ib.path(pdir, stage, ".checklist"), {}) or {}).get(rk, {})
    actions = (ib.read_json(ib.path(pdir, stage, ".actions"), {}) or {}).get(rk, [])
    feedback = ib.read_json(ib.path(pdir, stage, ".feedback"), []) or []
    pending_feedback = [f for f in feedback if not f.get("used_by")]
    return answers, checks, actions, pending_feedback


def qa_history(pdir, stage):
    """本阶段历次问答，用于下一次运行的提示。"""
    hist_dir = os.path.join(ib.inbox_dir(pdir), "history")
    answers_all = ib.read_json(ib.path(pdir, stage, ".answers"), {}) or {}
    out = []
    if not os.path.isdir(hist_dir):
        return out
    files = sorted(f for f in os.listdir(hist_dir) if f.startswith(stage + "-r") and f.endswith(".json"))
    for fn in files:
        box, _ = ib.normalize(ib.read_json(os.path.join(hist_dir, fn), {}) or {}, stage)
        if not box:
            continue
        ans = answers_all.get(str(box["round"]), {})
        for q in box["questions"]:
            if q["id"] in ans:
                out.append({"round": box["round"], "question": q["text"], "answer": ans[q["id"]]})
    return out


# ------------------------------------------------------------------ 详情与下一步

def _approval_needed(state, d, st):
    need = []
    for ap in d.get("approvals", []):
        if ap["when"] != "exit":
            continue
        if ap["mode"] == "conditional" and st.get("approval_required") is not True:
            continue
        if not gate.has_approval(state, ap["id"]):
            need.append(ap)
    return need


def _is_approval_problem(p):
    return p.startswith("缺少用户审批") or p.startswith("需声明")


def detail(pid, active_run=None):
    item = find(pid)
    pdir = item["path"]
    state = gate.load_state(pdir)
    cfg, order, defs = gate.stage_config()
    g = guides()
    cur = state["current_stage"]
    d = defs[cur]
    st = state["stages"][cur]
    probs = gate.problems(pdir, state, cur)
    box, box_probs = read_inbox(pdir, cur)
    answers, checks, actions_done, pending_feedback = user_inputs(pdir, cur, box)

    stages = []
    for sid in order:
        s = state["stages"][sid]
        stages.append({
            "id": sid, "title": defs[sid]["title"], "short": g["stages"][sid]["short"],
            "status": s["status"], "level": gate.achieved_level(s), "need": defs[sid]["min_evidence"],
            "blockers": len(s.get("blockers", [])), "skippable": bool(defs[sid].get("skippable")),
        })

    artifacts = []
    for rel in d["artifacts"]:
        p = os.path.join(pdir, rel)
        filled = os.path.exists(p) and os.path.getsize(p) > 0
        if filled and rel.endswith(".md"):
            with open(p, encoding="utf-8") as f:
                filled = gate.TEMPLATE_MARKER not in f.read()
        artifacts.append({"path": rel, "exists": os.path.exists(p), "filled": filled})

    need_approvals = _approval_needed(state, d, st)
    release_go_needed = (cur == "release" and not gate.has_approval(state, "release_go"))
    runs = list_runs(pdir, limit=8)
    cost_total = sum(r.get("cost_usd") or 0 for r in list_runs(pdir, limit=10000))

    action = next_action(cur, d, st, state, probs, box, answers, checks, actions_done,
                         need_approvals, release_go_needed, active_run, pending_feedback)

    return {
        "id": pid, "path": pdir, "demo": item.get("demo", False),
        "product": state["product"], "current_stage": cur,
        "stage": {"id": cur, "title": d["title"], "skill": d["skill"], "guide": g["stages"][cur],
                  "min_evidence": d["min_evidence"], "level": gate.achieved_level(st),
                  "status": st["status"], "skippable": bool(d.get("skippable")),
                  "terminal": bool(d.get("terminal")),
                  "evidence": st.get("evidence", []), "blockers": st.get("blockers", []),
                  "approval_required": st.get("approval_required"), "notes": st.get("notes", ""),
                  "artifacts": artifacts},
        "stages": stages,
        "levels": cfg["evidence_levels"], "level_names": g["levels"],
        "problems": probs,
        "inbox": box, "inbox_problems": box_probs,
        "answers": answers, "checklist_results": checks, "actions_done": actions_done,
        "pending_feedback": pending_feedback,
        "approvals_needed": [{"id": a["id"], "name": g["approvals"].get(a["id"], a["id"]), "ask": a["ask"]}
                             for a in need_approvals],
        "release_go": {"needed": release_go_needed, "approved": gate.has_approval(state, "release_go"),
                       "ask": next((a["ask"] for a in d.get("approvals", []) if a["id"] == "release_go"), "")},
        "approvals": [a for a in state.get("approvals", []) if a.get("product_version") == state["product"]["version"]],
        "waivers": [w for w in state.get("waivers", []) if w.get("product_version") == state["product"]["version"]],
        "history": state.get("history", [])[-30:],
        "runs": runs, "cost_total_usd": round(cost_total, 4),
        "active_run": active_run,
        "next_action": action,
        "docs": list_docs(pdir),
    }


def next_action(cur, d, st, state, probs, box, answers, checks, actions_done,
                need_approvals, release_go_needed, active_run, pending_feedback):
    g = guides()["stages"][cur]
    if active_run and active_run.get("status") in ("running", "waiting_manual"):
        if active_run["status"] == "waiting_manual":
            return {"kind": "manual_wait", "title": "把指令交给你的 AI 助手",
                    "detail": "复制下面的指令到 AI 助手里执行，完成后回到这里点“AI 已完成”。"}
        return {"kind": "running", "title": "AI 正在工作", "detail": "可以先离开，完成后这里会更新。"}
    if d.get("terminal"):
        return {"kind": "operate", "title": "整理反馈，决定下一版",
                "detail": "把用户反馈和运行数据整理好，确定范围后开始新版本。"}
    if st["status"] == "skipped":
        return {"kind": "advance", "title": "已跳过本阶段", "detail": "进入下一阶段。"}
    if box is None:
        return {"kind": "start", "title": g["start_label"], "detail": g["what"], "mode": "start"}
    unanswered = [q for q in box["questions"] if q["required"] and q["id"] not in answers]
    if box["status"] == "needs_input" and box["questions"] and unanswered:
        return {"kind": "answer", "title": "回答 %d 个问题" % len(unanswered),
                "detail": "回答完 AI 会继续往下做。不确定的可以写“不确定”。"}
    open_actions = [a for a in box["user_actions"] if a["id"] not in actions_done]
    if open_actions:
        return {"kind": "actions", "title": "需要你本人完成 %d 件事" % len(open_actions),
                "detail": "这些操作 AI 无法代办，照着步骤做完后勾选。"}
    if cur == "release" and not pending_feedback and box["status"] != "blocked":
        if release_go_needed and box.get("release_request"):
            return {"kind": "release_go", "title": "授权部署",
                    "detail": "确认平台、费用和公开范围后盖章，AI 才会开始部署。"}
        if not release_go_needed and gate.achieved_level(st) != "production_verified" and not box["checklist"]:
            return {"kind": "deploy", "title": "开始部署", "detail": "已授权。AI 会在授权范围内部署并逐项验证。",
                    "mode": "deploy"}
    if box["status"] == "needs_input" or pending_feedback:
        return {"kind": "continue", "title": "让 AI 继续", "detail": "把你的回答和反馈交给 AI。", "mode": "continue"}
    if box["status"] == "blocked":
        return {"kind": "blocked", "title": "AI 遇到了阻塞",
                "detail": "看下面的说明：可以补充信息让 AI 再试，也可以接受豁免或回到上一阶段。"}
    if box["checklist"]:
        unchecked = [c for c in box["checklist"] if c["id"] not in checks]
        failed = [c for c in box["checklist"] if checks.get(c["id"], {}).get("result") == "fail"]
        if unchecked:
            return {"kind": "checklist", "title": "照着清单验收（%d 步）" % len(box["checklist"]),
                    "detail": "一步一步操作，看到的和预期一致就点“通过”。"}
        if failed:
            return {"kind": "fix", "title": "有 %d 步没通过" % len(failed),
                    "detail": "把问题交给 AI 修复，修完会给你新的验收清单。", "mode": "fix"}
    if cur == "release":
        if release_go_needed:
            if box.get("release_request"):
                return {"kind": "release_go", "title": "授权部署",
                        "detail": "确认平台、费用和公开范围后盖章，AI 才会开始部署。"}
            return {"kind": "continue", "title": "让 AI 继续上线检查", "detail": "AI 还没有提交部署申请。",
                    "mode": "continue"}
        if gate.achieved_level(st) != "production_verified":
            return {"kind": "deploy", "title": "开始部署", "detail": "已授权。AI 会在授权范围内部署并逐项验证。",
                    "mode": "deploy"}
    others = [p for p in probs if not _is_approval_problem(p)]
    if box["status"] == "working" or others:
        return {"kind": "continue", "title": "让 AI 补齐", "detail": "还有未完成的项目，见右侧质检单。",
                "mode": "continue"}
    if need_approvals:
        return {"kind": "approve", "title": guides()["approvals"].get(need_approvals[0]["id"], "审批"),
                "detail": "看完审批卡再盖章。"}
    if not probs:
        return {"kind": "advance", "title": "进入下一阶段", "detail": "本阶段的闸门检查已全部通过。"}
    return {"kind": "continue", "title": "让 AI 继续", "detail": "", "mode": "continue"}


def summary(item):
    pdir = item["path"]
    state = gate.load_state(pdir)
    cfg, order, defs = gate.stage_config()
    cur = state["current_stage"]
    return {
        "id": item["id"], "name": state["product"]["name"], "version": state["product"]["version"],
        "path": pdir, "demo": item.get("demo", False), "current_stage": cur,
        "current_title": defs[cur]["title"],
        "stages": [{"id": s, "status": state["stages"][s]["status"]} for s in order],
        "updated": (state.get("history") or [{}])[-1].get("at", ""),
    }


# ------------------------------------------------------------------ 文档

DOC_EXCLUDE = {"inbox", "runs", "history"}


def list_docs(pdir):
    root = os.path.join(pdir, "factory")
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = sorted(x for x in dirnames if x not in DOC_EXCLUDE)
        for fn in sorted(files):
            if fn.endswith((".md", ".jsonl")) and fn != "README.md":
                rel = os.path.relpath(os.path.join(dirpath, fn), pdir)
                out.append(rel.replace(os.sep, "/"))
    return out


def read_doc(pid, rel):
    pdir = find(pid)["path"]
    rel = (rel or "").replace("\\", "/")
    full = os.path.realpath(os.path.join(pdir, rel))
    root = os.path.realpath(pdir)
    if not full.startswith(root + os.sep) or not rel.endswith((".md", ".jsonl")):
        raise UserError("只能查看产品文件夹里的文档。", 403)
    if not os.path.exists(full):
        raise UserError("还没有这份文档：%s" % rel, 404)
    with open(full, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ 运行记录

def runs_dir(pdir):
    return os.path.join(pdir, "factory", "runs")


def list_runs(pdir, limit=10):
    d = runs_dir(pdir)
    if not os.path.isdir(d):
        return []
    metas = []
    for fn in os.listdir(d):
        if fn.endswith(".json") and fn != "sessions.json":
            m = ib.read_json(os.path.join(d, fn))
            if m:
                m.pop("activity", None)
                m.pop("prompt", None)
                metas.append(m)
    metas.sort(key=lambda m: (m.get("started_ts") or 0, m.get("started", ""), m.get("id", "")), reverse=True)
    return metas[:limit]


# ------------------------------------------------------------------ 用户输入

def _merge_round(pdir, stage, suffix, rk, value):
    p = ib.path(pdir, stage, suffix)
    data = ib.read_json(p, {}) or {}
    data[rk] = value
    ib.write_json(p, data)


def save_answers(pid, answers):
    pdir = find(pid)["path"]
    state = gate.load_state(pdir)
    stage = state["current_stage"]
    box, _ = read_inbox(pdir, stage)
    if not box or not box["questions"]:
        raise UserError("现在没有需要回答的问题。")
    clean = {}
    for q in box["questions"]:
        v = answers.get(q["id"])
        if isinstance(v, list):
            v = [str(x) for x in v if str(x).strip()]
        elif v is not None:
            v = str(v).strip()
        if q["required"] and not v:
            raise UserError("还有问题没回答：%s" % q["text"])
        if v:
            clean[q["id"]] = v
    _merge_round(pdir, stage, ".answers", _round_key(box), clean)


def save_actions(pid, done_ids):
    pdir = find(pid)["path"]
    stage = gate.load_state(pdir)["current_stage"]
    box, _ = read_inbox(pdir, stage)
    if not box:
        raise UserError("现在没有待办操作。")
    valid = {a["id"] for a in box["user_actions"]}
    _merge_round(pdir, stage, ".actions", _round_key(box), [i for i in done_ids if i in valid])


def save_checklist(pid, results):
    pdir = find(pid)["path"]
    with gate.lock_for(pdir):
        stage = gate.load_state(pdir)["current_stage"]
        box, _ = read_inbox(pdir, stage)
        if not box or not box["checklist"]:
            raise UserError("现在没有验收清单。")
        clean = {}
        for c in box["checklist"]:
            r = results.get(c["id"])
            if not r:
                continue
            res = r.get("result")
            if res not in ("pass", "fail"):
                raise UserError("验收结果只能是通过或不通过。")
            note = str(r.get("note") or "").strip()
            if res == "fail" and not note:
                raise UserError("“%s”没通过，请写一句你看到了什么，AI 才能修。" % c["do"])
            clean[c["id"]] = {"result": res, "note": note}
        _merge_round(pdir, stage, ".checklist", _round_key(box), clean)
        sync_console_blockers(pdir, stage)


def add_feedback(pid, kind, text):
    if kind not in ("revise", "question", "info"):
        raise UserError("反馈类型无效。")
    text = (text or "").strip()
    if not text:
        raise UserError("写一句你希望 AI 改什么，或你想问什么。")
    pdir = find(pid)["path"]
    stage = gate.load_state(pdir)["current_stage"]
    p = ib.path(pdir, stage, ".feedback")
    data = ib.read_json(p, []) or []
    data.append({"kind": kind, "text": text, "at": gate.fg.now()})
    ib.write_json(p, data)


def consume_feedback(pdir, stage, run_id):
    p = ib.path(pdir, stage, ".feedback")
    data = ib.read_json(p, []) or []
    used = []
    for f in data:
        if not f.get("used_by"):
            f["used_by"] = run_id
            used.append(f)
    if used:
        ib.write_json(p, data)
    return used


# ------------------------------------------------------------------ 状态写入（经闸门脚本）

def _user(cfg=None):
    cfg = cfg or load_config()
    return (cfg.get("user_name") or "").strip() or "产品负责人"


def approve(pid, aid, quote, scope=None, acknowledged=False):
    pdir = find(pid)["path"]
    quote = (quote or "").strip()
    if len(quote) < 2:
        raise UserError("写一句你的批准意见，它会作为签字原话保存。")
    with gate.lock_for(pdir):
        state = gate.load_state(pdir)
        cur = state["current_stage"]
        _, _, defs = gate.stage_config()
        ap = next((a for a in defs[cur].get("approvals", []) if a["id"] == aid), None)
        if not ap:
            raise UserError("当前阶段没有这项审批。")
        if gate.has_approval(state, aid):
            raise UserError("这项已经签过字了。")
        box, _ = read_inbox(pdir, cur)
        summ = (box or {}).get("approval_summary") or {}
        if (summ.get("unverified") or summ.get("new_costs")) and not acknowledged:
            raise UserError("请先展开并确认“未验证”和“新增费用”两部分。")
        if ap["when"] == "exit":
            others = [p for p in gate.problems(pdir, state, cur) if not _is_approval_problem(p)]
            if others:
                raise UserError("还有未完成的项目，先处理完再签字：%s" % others[0])
            checks = user_inputs(pdir, cur, box)[1]
            if box and box["checklist"] and any(c["id"] not in checks or checks[c["id"]]["result"] != "pass"
                                                for c in box["checklist"]):
                raise UserError("验收清单还没有全部通过。")
        if aid == "release_go":
            if not scope or not all(str(scope.get(k) or "").strip() for k in ("platform", "environment", "cost", "visibility")):
                raise UserError("授权部署需要写明平台、环境、费用上限和公开范围。")
            scope = "；".join("%s：%s" % (lbl, str(scope.get(k)).strip()) for k, lbl in (
                ("platform", "平台"), ("environment", "环境"), ("cost", "费用上限"), ("visibility", "公开范围"),
                ("data_migration", "数据迁移"), ("rollback", "回滚")) if str(scope.get(k) or "").strip())
        argv = ["approve", pdir, "--id", aid, "--by", _user(), "--quote", quote, "--via", "console"]
        if scope:
            argv += ["--scope", scope]
        gate.must(argv)


def waive(pid, reason, quote):
    pdir = find(pid)["path"]
    if not (reason or "").strip() or not (quote or "").strip():
        raise UserError("豁免需要写明原因和你的确认原话。")
    with gate.lock_for(pdir):
        gate.must(["waive", pdir, "--item", "min_evidence", "--reason", reason.strip(),
                   "--by", _user(), "--quote", quote.strip(), "--via", "console"])


def advance(pid):
    pdir = find(pid)["path"]
    with gate.lock_for(pdir):
        code, text = gate.run(["advance", pdir])
        if code != 0:
            lines = [l.strip(" -") for l in text.splitlines()[1:] if l.strip()]
            raise UserError("还不能进入下一阶段：" + ("；".join(lines) or text))


def skip(pid, reason):
    pdir = find(pid)["path"]
    if not (reason or "").strip():
        raise UserError("跳过需要写明理由。")
    with gate.lock_for(pdir):
        gate.must(["set", pdir, "--skip", reason.strip()])


def blocker(pid, add=None, clear=None, resolution=None):
    pdir = find(pid)["path"]
    with gate.lock_for(pdir):
        if add:
            gate.must(["blocker", pdir, "--add", add.strip()])
        if clear is not None:
            gate.must(["blocker", pdir, "--clear", str(int(clear)), "--resolution", resolution or "用户在控制台处理"])


def iterate(pid, reason):
    pdir = find(pid)["path"]
    if not (reason or "").strip():
        raise UserError("写一句下一版要做什么。")
    with gate.lock_for(pdir):
        gate.must(["iterate", pdir, "--reason", reason.strip()])
        d = ib.inbox_dir(pdir)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    os.remove(p)
            shutil.rmtree(os.path.join(d, "history"), ignore_errors=True)


# ------------------------------------------------------------------ 吸收 AI 运行结果

def _console_meta(pdir, stage):
    return ib.read_json(ib.path(pdir, stage, ".console"), {}) or {}


def _save_console_meta(pdir, stage, meta):
    ib.write_json(ib.path(pdir, stage, ".console"), meta)


def sync_console_blockers(pdir, stage):
    """阻塞 = AI 报告的阻塞 + 本轮验收未通过的步骤；用户手动添加的阻塞保持不动。"""
    box, _ = read_inbox(pdir, stage)
    desired = list(box["blockers"]) if box else []
    if box and box["checklist"]:
        checks = user_inputs(pdir, stage, box)[1]
        for c in box["checklist"]:
            r = checks.get(c["id"])
            if r and r["result"] == "fail":
                desired.append("验收未通过：%s（%s）" % (c["do"], r["note"]))
    meta = _console_meta(pdir, stage)
    prev = set(meta.get("blockers", []))
    state = gate.load_state(pdir)
    st = state["stages"][stage]
    kept = [b for b in st.get("blockers", []) if b not in prev]
    new = kept + [b for b in desired if b not in kept]
    if new != st.get("blockers", []):
        st["blockers"] = new
        if new and st["status"] in ("in_progress", "awaiting_approval"):
            st["status"] = "blocked"
        elif not new and st["status"] == "blocked":
            st["status"] = "in_progress"
        gate.fg.log(state, "console_blockers", "%s：%d 项" % (stage, len(new)))
        gate.fg.save_state(pdir, state)
    meta["blockers"] = desired
    _save_console_meta(pdir, stage, meta)


def ingest(pdir, stage, run_started_ts, deploy_mode=False):
    """AI 运行结束后调用。返回给运行记录的提示信息列表。"""
    notes = []
    p = ib.path(pdir, stage)
    if not os.path.exists(p) or os.path.getmtime(p) + 1 < run_started_ts:
        notes.append("AI 本次没有更新收件箱。")
        box = None
    else:
        raw = ib.read_json(p)
        if raw is None:
            return ["收件箱不是合法 JSON，请重新运行或让 AI 修复。"]
        box, probs = ib.normalize(raw, stage)
        notes += probs
        hist = os.path.join(ib.inbox_dir(pdir), "history")
        os.makedirs(hist, exist_ok=True)
        ib.write_json(os.path.join(hist, "%s-r%03d.json" % (stage, box["round"])), raw)
    cfg, order, defs = gate.stage_config()
    levels = cfg["evidence_levels"]
    cap = levels.index(defs[stage]["min_evidence"])
    meta = _console_meta(pdir, stage)
    applied = set(meta.get("applied_evidence", []))
    if box:
        state = gate.load_state(pdir)
        for ev in box["evidence"]:
            h = hashlib.sha1(json.dumps(ev, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if h in applied:
                continue
            if ev["level"] not in levels:
                notes.append("忽略了等级无效的证据：%s" % ev["what"])
                continue
            if levels.index(ev["level"]) > cap:
                notes.append("证据“%s”的等级 %s 超过本阶段要求，已按 %s 记录" % (ev["what"], ev["level"], levels[cap]))
                ev = dict(ev, level=levels[cap])
            if ev["level"] == "production_verified" and not (deploy_mode and gate.has_approval(state, "release_go")):
                notes.append("未授权部署时不能记录线上验证证据，已忽略：%s" % ev["what"])
                continue
            argv = ["evidence", pdir, "--stage", stage, "--level", ev["level"], "--what", ev["what"],
                    "--how", ev["how"], "--result", ev["result"]]
            if ev.get("where"):
                argv += ["--where", ev["where"]]
            if ev.get("env"):
                argv += ["--env", ev["env"]]
            code, text = gate.run(argv)
            if code == 0:
                applied.add(h)
            else:
                notes.append("记录证据失败：%s" % text)
        if stage == "adaptation" and box["approval_required"] is not None:
            gate.run(["set", pdir, "--stage", stage, "--approval-required",
                      "true" if box["approval_required"] else "false"])
    meta["applied_evidence"] = sorted(applied)
    _save_console_meta(pdir, stage, meta)
    # 文档阶段：交接物写完即记录 planned 证据
    if defs[stage]["min_evidence"] == "planned":
        state = gate.load_state(pdir)
        st = state["stages"][stage]
        if gate.achieved_level(st) is None:
            ok = True
            for rel in defs[stage]["artifacts"]:
                fp = os.path.join(pdir, rel)
                if not (os.path.exists(fp) and os.path.getsize(fp) > 0):
                    ok = False
                    break
                if rel.endswith(".md"):
                    with open(fp, encoding="utf-8") as f:
                        if gate.TEMPLATE_MARKER in f.read():
                            ok = False
                            break
            if ok:
                gate.run(["evidence", pdir, "--stage", stage, "--level", "planned",
                          "--what", "交接物已写完：" + "、".join(defs[stage]["artifacts"]),
                          "--how", "控制台检查文件存在且已删除模板标记", "--result", "pass"])
    sync_console_blockers(pdir, stage)
    if box and box["status"] == "ready_for_review":
        state = gate.load_state(pdir)
        st = state["stages"][stage]
        if st["status"] == "in_progress" and _approval_needed(state, defs[stage], st):
            st["status"] = "awaiting_approval"
            gate.fg.save_state(pdir, state)
    return notes
