#!/usr/bin/env python3
"""AI 产品工厂的阶段状态机与闸门检查（仅用 Python 标准库，3.9+）。

产品仓库内的唯一事实来源是 factory/state.json。本脚本负责：
  init      在产品仓库中建立 factory/ 目录与 state.json
  status    显示各阶段状态、当前阶段与缺口
  check     检查某阶段能否通过闸门（默认当前阶段），不通过时退出码为 1
  require   检查某个审批是否已记录（如部署前 release_go），未记录时退出码为 1
  evidence  为阶段追加一条验证证据；--resolve N 标记失败证据已处理
  blocker   添加 / 清除阶段阻塞项
  approve   记录用户审批（必须附用户原话，由用户本人执行或在用户明确批准后代录）
  waive     记录用户豁免（例如暂无模型 Key，接受以 mock 证据结束 build）
  set       设置阶段字段（approval_required / skip）
  advance   当前阶段通过闸门后进入下一阶段
  iterate   上线后开启新一轮版本（归档当前 factory 状态，从 PRD 变更开始）

用法示例：
  python3 factory_gate.py init ./my-product --name "论文阅读助手"
  python3 factory_gate.py status ./my-product
  python3 factory_gate.py evidence ./my-product --level mock_passed --what "pytest 全部通过" \
      --how "pytest -q" --result pass --where "factory/stages/handoff.md#验证证据"
  python3 factory_gate.py approve ./my-product --id prd_signoff --by "产品负责人" --quote "PRD 确认，可以进入架构"
  python3 factory_gate.py check ./my-product && python3 factory_gate.py advance ./my-product
"""

import argparse
import datetime as _dt
import json
import os
import shutil
import sys
import tempfile

SCHEMA_VERSION = 1
TEMPLATE_MARKER = "<!-- factory:template -->"
HERE = os.path.dirname(os.path.abspath(__file__))
STAGES_FILE = os.path.join(HERE, "..", "assets", "stages.json")
STATUSES = ["not_started", "in_progress", "awaiting_approval", "passed", "blocked", "skipped"]
RESULTS = ["pass", "fail", "unverified", "n/a"]


def now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_stages():
    with open(STAGES_FILE, encoding="utf-8") as f:
        return json.load(f)


def stage_defs():
    cfg = load_stages()
    return cfg, [s["id"] for s in cfg["stages"]], {s["id"]: s for s in cfg["stages"]}


def state_path(product_dir):
    return os.path.join(product_dir, "factory", "state.json")


def load_state(product_dir):
    p = state_path(product_dir)
    if not os.path.exists(p):
        die("未找到 %s；先运行 init。" % p)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        die("state.json 不是合法 JSON：%s（不要手动编辑后留下语法错误）" % e)


def save_state(product_dir, state):
    """原子写入：先写临时文件再替换，避免中断时留下半个文件。"""
    p = state_path(product_dir)
    d = os.path.dirname(p)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def die(msg, code=2):
    print("错误：" + msg, file=sys.stderr)
    sys.exit(code)


def log(state, event, detail):
    state.setdefault("history", []).append({"at": now(), "event": event, "detail": detail})


# ---------------------------------------------------------------- 结构校验

def validate_state(state):
    """不依赖第三方库的结构校验，返回问题列表。"""
    errs = []
    cfg, order, defs = stage_defs()
    if state.get("schema_version") != SCHEMA_VERSION:
        errs.append("schema_version 应为 %d" % SCHEMA_VERSION)
    prod = state.get("product")
    if not isinstance(prod, dict) or not prod.get("name") or not isinstance(prod.get("version"), int):
        errs.append("product 需要 name 与整数 version")
    if state.get("current_stage") not in order:
        errs.append("current_stage 必须是 %s 之一" % order)
    stages = state.get("stages")
    if not isinstance(stages, dict):
        return errs + ["stages 必须是对象"]
    for sid in order:
        st = stages.get(sid)
        if not isinstance(st, dict):
            errs.append("缺少阶段 %s" % sid)
            continue
        if st.get("status") not in STATUSES:
            errs.append("%s.status 非法：%r" % (sid, st.get("status")))
        for ev in st.get("evidence", []):
            if ev.get("level") not in cfg["evidence_levels"]:
                errs.append("%s 证据等级非法：%r" % (sid, ev.get("level")))
            if ev.get("result") not in RESULTS:
                errs.append("%s 证据结果非法：%r" % (sid, ev.get("result")))
            for k in ("what", "how", "at"):
                if not ev.get(k):
                    errs.append("%s 证据缺少 %s" % (sid, k))
        if not isinstance(st.get("blockers", []), list):
            errs.append("%s.blockers 必须是列表" % sid)
    for a in state.get("approvals", []):
        for k in ("id", "stage", "by", "quote", "at"):
            if not a.get(k):
                errs.append("审批记录缺少 %s：%r" % (k, a))
    for w in state.get("waivers", []):
        for k in ("stage", "item", "reason", "by", "quote", "at"):
            if not w.get(k):
                errs.append("豁免记录缺少 %s：%r" % (k, w))
    return errs


# ---------------------------------------------------------------- 闸门

def achieved_level(cfg, st):
    levels = cfg["evidence_levels"]
    best = -1
    for ev in st.get("evidence", []):
        if ev.get("result") == "pass" and ev.get("level") in levels:
            best = max(best, levels.index(ev["level"]))
    return best


def has_approval(state, aid, version=None):
    version = version or state["product"]["version"]
    return any(a["id"] == aid and a.get("product_version", version) == version for a in state.get("approvals", []))


def has_waiver(state, sid, item):
    v = state["product"]["version"]
    return any(w["stage"] == sid and w["item"] == item and w.get("product_version", v) == v
               for w in state.get("waivers", []))


def gate_problems(product_dir, state, sid):
    cfg, order, defs = stage_defs()
    d = defs[sid]
    st = state["stages"][sid]
    probs = []
    if st["status"] == "skipped":
        if not d.get("skippable"):
            probs.append("该阶段不允许跳过")
        elif not st.get("skipped_reason"):
            probs.append("跳过必须写明理由")
        return probs
    # 1. 交接物存在且不是未填写的模板
    for rel in d["artifacts"]:
        p = os.path.join(product_dir, rel)
        if not os.path.exists(p):
            probs.append("缺少交接物 %s" % rel)
            continue
        if os.path.getsize(p) == 0:
            probs.append("交接物为空 %s" % rel)
            continue
        if rel.endswith(".md"):
            with open(p, encoding="utf-8") as f:
                text = f.read()
            if TEMPLATE_MARKER in text:
                probs.append("%s 仍含模板标记 %s（填写完成后删除该行）" % (rel, TEMPLATE_MARKER))
    # 2. 阻塞项
    for b in st.get("blockers", []):
        probs.append("未解除的阻塞：%s" % b)
    # 3. 证据等级
    levels = cfg["evidence_levels"]
    need = levels.index(d["min_evidence"])
    got = achieved_level(cfg, st)
    if got < need and not has_waiver(state, sid, "min_evidence"):
        got_name = levels[got] if got >= 0 else "无"
        probs.append("证据等级不足：需要 %s，当前 %s（缺条件时由用户 waive，不能以低等级冒充）"
                     % (d["min_evidence"], got_name))
    failing = [e for e in st.get("evidence", []) if e.get("result") == "fail"]
    for e in failing:
        if not e.get("resolved"):
            probs.append("存在失败且未处理的证据：%s" % e["what"])
    # 4. 审批
    for ap in d.get("approvals", []):
        if ap["mode"] == "conditional":
            req = st.get("approval_required")
            if req is None:
                probs.append("需声明 %s 是否需要用户确认（set --approval-required true/false）" % ap["id"])
                continue
            if not req:
                continue
        if not has_approval(state, ap["id"]):
            probs.append("缺少用户审批 %s：%s" % (ap["id"], ap["ask"]))
    return probs


# ---------------------------------------------------------------- 命令

def cmd_init(a):
    cfg, order, defs = stage_defs()
    fdir = os.path.join(a.product_dir, "factory")
    if os.path.exists(state_path(a.product_dir)):
        die("factory/state.json 已存在，不覆盖。")
    for sub in ("stages", "frontend", "eval", "release", "history"):
        os.makedirs(os.path.join(fdir, sub), exist_ok=True)
    readme_src = os.path.join(HERE, "..", "assets", "factory-template", "README.md")
    readme_dst = os.path.join(fdir, "README.md")
    if not os.path.exists(readme_dst):
        shutil.copyfile(readme_src, readme_dst)
    state = {
        "schema_version": SCHEMA_VERSION,
        "product": {"name": a.name, "slug": a.slug or "", "version": 1, "created_at": now()},
        "current_stage": order[0],
        "stages": {},
        "approvals": [],
        "waivers": [],
        "budget": {
            "model_usd_per_stage": a.model_budget,
            "cloud_spend_requires_approval": True,
            "max_fix_attempts_per_blocker": 2,
        },
        "history": [],
    }
    for sid in order:
        state["stages"][sid] = {"status": "not_started", "evidence": [], "blockers": [],
                                "approval_required": None, "skipped_reason": None, "notes": ""}
    state["stages"][order[0]]["status"] = "in_progress"
    log(state, "init", "创建工厂状态，从 %s 开始" % order[0])
    save_state(a.product_dir, state)
    print("已初始化 %s，当前阶段：%s" % (fdir, order[0]))


def cmd_status(a):
    state = load_state(a.product_dir)
    cfg, order, defs = stage_defs()
    errs = validate_state(state)
    p = state["product"]
    print("产品：%s  版本：v%s  当前阶段：%s" % (p["name"], p["version"], state["current_stage"]))
    levels = cfg["evidence_levels"]
    for sid in order:
        st = state["stages"][sid]
        got = achieved_level(cfg, st)
        mark = "▶" if sid == state["current_stage"] else " "
        print(" %s %-11s %-18s 证据:%-20s 需要:%-20s 阻塞:%d  [%s]" % (
            mark, sid, st["status"], levels[got] if got >= 0 else "-", defs[sid]["min_evidence"],
            len(st.get("blockers", [])), defs[sid]["skill"]))
    if errs:
        print("\nstate.json 结构问题：")
        for e in errs:
            print("  - " + e)
    cur = state["current_stage"]
    evs = state["stages"][cur].get("evidence", [])
    if evs:
        print("\n当前阶段证据：")
        for i, e in enumerate(evs):
            tag = "（已处理）" if e.get("resolved") else ""
            print("  [%d] %s/%s %s%s" % (i, e.get("level"), e.get("result"), e.get("what"), tag))
    probs = gate_problems(a.product_dir, state, cur)
    print("\n当前阶段闸门：" + ("可通过" if not probs else "未通过"))
    for x in probs:
        print("  - " + x)


def cmd_check(a):
    state = load_state(a.product_dir)
    errs = validate_state(state)
    if errs:
        for e in errs:
            print("结构问题：" + e)
        sys.exit(1)
    sid = a.stage or state["current_stage"]
    probs = gate_problems(a.product_dir, state, sid)
    if probs:
        print("阶段 %s 闸门未通过：" % sid)
        for x in probs:
            print("  - " + x)
        sys.exit(1)
    print("阶段 %s 闸门通过。" % sid)


def cmd_require(a):
    state = load_state(a.product_dir)
    if has_approval(state, a.id):
        print("已记录审批 %s。" % a.id)
        return
    print("未记录审批 %s，停止在该操作之前。" % a.id)
    sys.exit(1)


def _stage(state, sid):
    _, order, _ = stage_defs()
    sid = sid or state["current_stage"]
    if sid not in order:
        die("未知阶段 %s" % sid)
    return sid, state["stages"][sid]


def cmd_evidence(a):
    state = load_state(a.product_dir)
    sid, st = _stage(state, a.stage)
    cfg, _, _ = stage_defs()
    if a.resolve is not None:
        evs = st.get("evidence", [])
        if a.resolve < 0 or a.resolve >= len(evs) or evs[a.resolve].get("result") != "fail":
            die("第 %d 条不是失败证据（编号从 0 开始，可用 status 查看）" % a.resolve)
        if not a.resolution:
            die("标记已处理时必须用 --resolution 写明如何处理（例如“修复后已追加 pass 证据”）")
        evs[a.resolve]["resolved"] = {"how": a.resolution, "at": now()}
        log(state, "evidence_resolve", "%s 第 %d 条：%s" % (sid, a.resolve, a.resolution))
        save_state(a.product_dir, state)
        print("已标记 %s 第 %d 条失败证据为已处理。" % (sid, a.resolve))
        return
    for k in ("level", "what", "how", "result"):
        if not getattr(a, k):
            die("记录证据需要 --%s" % k)
    if a.level not in cfg["evidence_levels"]:
        die("证据等级必须是 %s" % cfg["evidence_levels"])
    ev = {"level": a.level, "what": a.what, "how": a.how, "result": a.result,
          "where": a.where or "", "env": a.env or "", "at": now()}
    st.setdefault("evidence", []).append(ev)
    if st["status"] == "not_started":
        st["status"] = "in_progress"
    log(state, "evidence", "%s: [%s/%s] %s" % (sid, a.level, a.result, a.what))
    save_state(a.product_dir, state)
    print("已记录证据到 %s。" % sid)


def cmd_blocker(a):
    state = load_state(a.product_dir)
    sid, st = _stage(state, a.stage)
    if a.add:
        st.setdefault("blockers", []).append(a.add)
        st["status"] = "blocked"
        log(state, "blocker_add", "%s: %s" % (sid, a.add))
    if a.clear is not None:
        bl = st.get("blockers", [])
        if a.clear < 0 or a.clear >= len(bl):
            die("没有编号 %d 的阻塞项（从 0 开始）" % a.clear)
        removed = bl.pop(a.clear)
        if not bl and st["status"] == "blocked":
            st["status"] = "in_progress"
        log(state, "blocker_clear", "%s: %s（处理：%s）" % (sid, removed, a.resolution or "未说明"))
    save_state(a.product_dir, state)
    print("阶段 %s 阻塞项：%s" % (sid, st.get("blockers", [])))


def cmd_approve(a):
    state = load_state(a.product_dir)
    cfg, order, defs = stage_defs()
    owner = None
    for sid in order:
        if any(ap["id"] == a.id for ap in defs[sid].get("approvals", [])):
            owner = sid
    if owner is None:
        die("未知审批 id：%s" % a.id)
    rec = {"id": a.id, "stage": owner, "by": a.by, "quote": a.quote, "at": now(),
           "product_version": state["product"]["version"], "via": a.via}
    if a.scope:
        rec["scope"] = a.scope
    state.setdefault("approvals", []).append(rec)
    log(state, "approve", "%s by %s：%s" % (a.id, a.by, a.quote))
    save_state(a.product_dir, state)
    print("已记录审批 %s。" % a.id)


def cmd_waive(a):
    state = load_state(a.product_dir)
    sid, st = _stage(state, a.stage)
    rec = {"stage": sid, "item": a.item, "reason": a.reason, "by": a.by, "quote": a.quote,
           "at": now(), "product_version": state["product"]["version"], "via": a.via}
    state.setdefault("waivers", []).append(rec)
    log(state, "waive", "%s/%s：%s" % (sid, a.item, a.reason))
    save_state(a.product_dir, state)
    print("已记录豁免 %s/%s。豁免会出现在后续报告中，不等于已验证。" % (sid, a.item))


def cmd_set(a):
    state = load_state(a.product_dir)
    cfg, order, defs = stage_defs()
    sid, st = _stage(state, a.stage)
    if a.approval_required is not None:
        st["approval_required"] = a.approval_required == "true"
        log(state, "set", "%s.approval_required=%s" % (sid, st["approval_required"]))
    if a.skip:
        if not defs[sid].get("skippable"):
            die("阶段 %s 不允许跳过" % sid)
        st["status"] = "skipped"
        st["skipped_reason"] = a.skip
        log(state, "skip", "%s：%s" % (sid, a.skip))
    if a.notes is not None:
        st["notes"] = a.notes
    save_state(a.product_dir, state)
    print("已更新阶段 %s。" % sid)


def cmd_advance(a):
    state = load_state(a.product_dir)
    errs = validate_state(state)
    if errs:
        die("state.json 结构问题：%s" % "; ".join(errs), 1)
    cfg, order, defs = stage_defs()
    cur = state["current_stage"]
    if defs[cur].get("terminal"):
        die("%s 是持续阶段；开启新版本请用 iterate。" % cur, 1)
    probs = gate_problems(a.product_dir, state, cur)
    if probs:
        print("阶段 %s 闸门未通过，不能推进：" % cur)
        for x in probs:
            print("  - " + x)
        sys.exit(1)
    if state["stages"][cur]["status"] != "skipped":
        state["stages"][cur]["status"] = "passed"
    i = order.index(cur) + 1
    nxt = order[i]
    state["current_stage"] = nxt
    if state["stages"][nxt]["status"] == "not_started":
        state["stages"][nxt]["status"] = "in_progress"
    log(state, "advance", "%s → %s" % (cur, nxt))
    save_state(a.product_dir, state)
    print("阶段 %s 已通过，进入 %s（Skill：%s）。" % (cur, nxt, defs[nxt]["skill"]))


def cmd_iterate(a):
    state = load_state(a.product_dir)
    cfg, order, defs = stage_defs()
    if state["current_stage"] != "operate":
        die("只有在 operate 阶段才能开启新版本（当前 %s）。" % state["current_stage"], 1)
    v = state["product"]["version"]
    fdir = os.path.join(a.product_dir, "factory")
    arch = os.path.join(fdir, "history", "v%d" % v)
    if os.path.exists(arch):
        die("归档目录已存在：%s" % arch)
    os.makedirs(arch)
    for name in os.listdir(fdir):
        if name in ("history",):
            continue
        src = os.path.join(fdir, name)
        dst = os.path.join(arch, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    state["product"]["version"] = v + 1
    for sid in order:
        state["stages"][sid] = {"status": "not_started", "evidence": [], "blockers": [],
                                "approval_required": None, "skipped_reason": None, "notes": ""}
    state["current_stage"] = order[0]
    state["stages"][order[0]]["status"] = "in_progress"
    state["stages"][order[0]]["notes"] = "变更模式：基于 factory/feedback.md 与上一版 PRD 修订（%s）" % (a.reason or "")
    log(state, "iterate", "v%d 已归档到 history/v%d，开始 v%d：%s" % (v, v, v + 1, a.reason or ""))
    save_state(a.product_dir, state)
    print("已归档 v%d，开始 v%d，当前阶段 prd（变更模式）。" % (v, v + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 产品工厂阶段状态机与闸门")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("product_dir"); p.add_argument("--name", required=True)
    p.add_argument("--slug"); p.add_argument("--model-budget", type=float, default=None,
                                               help="每阶段真实模型调用预算（美元，可选）")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("status"); p.add_argument("product_dir"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("check"); p.add_argument("product_dir"); p.add_argument("--stage"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("require"); p.add_argument("product_dir"); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_require)

    p = sub.add_parser("evidence"); p.add_argument("product_dir"); p.add_argument("--stage")
    p.add_argument("--level"); p.add_argument("--what")
    p.add_argument("--how", help="实际命令或操作")
    p.add_argument("--result", choices=RESULTS)
    p.add_argument("--where", help="证据位置（文件、截图、日志）"); p.add_argument("--env", help="环境")
    p.add_argument("--resolve", type=int, help="把第 N 条失败证据标记为已处理（从 0 开始）")
    p.add_argument("--resolution", help="处理说明，配合 --resolve")
    p.set_defaults(fn=cmd_evidence)

    p = sub.add_parser("blocker"); p.add_argument("product_dir"); p.add_argument("--stage")
    p.add_argument("--add"); p.add_argument("--clear", type=int); p.add_argument("--resolution")
    p.set_defaults(fn=cmd_blocker)

    p = sub.add_parser("approve"); p.add_argument("product_dir"); p.add_argument("--id", required=True)
    p.add_argument("--by", required=True); p.add_argument("--quote", required=True, help="用户批准原话")
    p.add_argument("--scope", help="授权范围，例如 release_go 的平台/环境/费用上限")
    p.add_argument("--via", default="cli", help="记录来源：cli（命令行）或 console（控制台）")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("waive"); p.add_argument("product_dir"); p.add_argument("--stage")
    p.add_argument("--item", required=True, help="例如 min_evidence"); p.add_argument("--reason", required=True)
    p.add_argument("--by", required=True); p.add_argument("--quote", required=True)
    p.add_argument("--via", default="cli")
    p.set_defaults(fn=cmd_waive)

    p = sub.add_parser("set"); p.add_argument("product_dir"); p.add_argument("--stage")
    p.add_argument("--approval-required", choices=["true", "false"]); p.add_argument("--skip", help="跳过理由")
    p.add_argument("--notes"); p.set_defaults(fn=cmd_set)

    p = sub.add_parser("advance"); p.add_argument("product_dir"); p.set_defaults(fn=cmd_advance)
    p = sub.add_parser("iterate"); p.add_argument("product_dir"); p.add_argument("--reason")
    p.set_defaults(fn=cmd_iterate)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
