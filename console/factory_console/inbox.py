"""收件箱读写与校验。AI 写 factory/inbox/<stage>.json，用户的回答、勾选、操作完成情况由控制台写入旁边的文件。"""

import json
import os
import tempfile

STATUSES = {"needs_input", "ready_for_review", "blocked", "working"}
Q_TYPES = {"text", "choice", "multi"}
RESULTS = {"pass", "fail", "unverified", "n/a"}


def inbox_dir(product_dir):
    return os.path.join(product_dir, "factory", "inbox")


def path(product_dir, stage, suffix=""):
    return os.path.join(inbox_dir(product_dir), "%s%s.json" % (stage, suffix))


def read_json(p, default=None):
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".tmp.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def _list(v):
    return v if isinstance(v, list) else []


def normalize(raw, stage):
    """校验并整理 AI 写入的收件箱。返回 (inbox, 问题列表)。问题不致命时尽量保留可用内容。"""
    probs = []
    if not isinstance(raw, dict):
        return None, ["收件箱不是 JSON 对象"]
    box = {
        "stage": stage,
        "round": raw.get("round") if isinstance(raw.get("round"), int) else 1,
        "status": raw.get("status") if raw.get("status") in STATUSES else "working",
        "summary": str(raw.get("summary") or "").strip(),
        "questions": [],
        "user_actions": [],
        "checklist": [],
        "evidence": [],
        "blockers": [str(b) for b in _list(raw.get("blockers")) if str(b).strip()],
        "approval_required": raw.get("approval_required") if raw.get("approval_required") in (True, False) else None,
        "approval_summary": None,
        "release_request": raw.get("release_request") if isinstance(raw.get("release_request"), dict) else None,
    }
    if raw.get("stage") and raw.get("stage") != stage:
        probs.append("收件箱的 stage 是 %r，与当前阶段 %r 不一致" % (raw.get("stage"), stage))
    if raw.get("status") not in STATUSES:
        probs.append("status 缺失或无效，按 working 处理")
    seen = set()
    for i, q in enumerate(_list(raw.get("questions"))):
        if not isinstance(q, dict) or not q.get("text"):
            probs.append("第 %d 个问题缺少 text" % (i + 1))
            continue
        qid = str(q.get("id") or "q%d" % (i + 1))
        if qid in seen:
            qid = "%s_%d" % (qid, i + 1)
        seen.add(qid)
        qt = q.get("type") if q.get("type") in Q_TYPES else "text"
        opts = [str(o) for o in _list(q.get("options"))]
        if qt != "text" and not opts:
            qt = "text"
        box["questions"].append({
            "id": qid, "text": str(q["text"]), "why": str(q.get("why") or ""), "type": qt,
            "options": opts, "example": str(q.get("example") or ""), "required": q.get("required", True) is not False,
        })
    for i, a in enumerate(_list(raw.get("user_actions"))):
        if not isinstance(a, dict) or not a.get("title"):
            continue
        box["user_actions"].append({
            "id": str(a.get("id") or "a%d" % (i + 1)), "title": str(a["title"]),
            "steps": [str(s) for s in _list(a.get("steps"))], "done_when": str(a.get("done_when") or ""),
        })
    for i, c in enumerate(_list(raw.get("checklist"))):
        if not isinstance(c, dict) or not c.get("do"):
            continue
        box["checklist"].append({"id": str(c.get("id") or "c%d" % (i + 1)), "do": str(c["do"]),
                                 "expect": str(c.get("expect") or "")})
    for e in _list(raw.get("evidence")):
        if not isinstance(e, dict):
            continue
        if not (e.get("level") and e.get("what") and e.get("how") and e.get("result") in RESULTS):
            probs.append("有一条证据缺少 level/what/how/result，已忽略")
            continue
        box["evidence"].append({k: str(e.get(k) or "") for k in ("level", "what", "how", "result", "where", "env")})
    s = raw.get("approval_summary")
    if isinstance(s, dict):
        box["approval_summary"] = {
            "done": str(s.get("done") or ""),
            "verified": [str(x) for x in _list(s.get("verified"))],
            "unverified": [str(x) for x in _list(s.get("unverified"))],
            "new_costs": [str(x) for x in _list(s.get("new_costs"))],
            "questions": [str(x) for x in _list(s.get("questions"))],
            "next": str(s.get("next") or ""),
        }
    elif box["status"] == "ready_for_review":
        probs.append("status 为 ready_for_review 但缺少 approval_summary")
    return box, probs
