#!/usr/bin/env python3
"""检查 factory/eval/cases.jsonl 的格式、AC 覆盖并汇总结果（仅标准库，3.9+）。

用法：
  python3 eval_cases.py <产品仓库>            # 默认读 factory/prd.md 与 factory/eval/cases.jsonl
  python3 eval_cases.py <产品仓库> --cases 其他.jsonl --prd 其他.md

退出码：0 = 格式正确且所有有效 AC 都有用例；1 = 有问题（会列出）。
注意：结果中存在 fail / unverified 不会让退出码为 1，是否可发布由 QA 报告与闸门判断。
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

TYPES = {"functional", "agent_quality", "safety", "reliability", "performance"}
LAYERS = {"mock", "real", "manual"}
JUDGES = {"exact", "rule", "rubric", "human", "model_judge", "measure"}
RESULTS = {"pass", "fail", "unverified", "n/a"}
SEVERITIES = {"blocker", "major", "minor"}
REQUIRED = ["id", "ac", "type", "layer", "input", "expected", "judge", "result"]
AC_ROW = re.compile(r"^\|\s*(AC-\d+)\s*\|(.*)$")


def prd_acs(prd_path):
    """从 PRD 的验收标准表格中读取 AC 编号；标注“已废弃”的跳过。"""
    acs, deprecated = [], []
    with open(prd_path, encoding="utf-8") as f:
        for line in f:
            m = AC_ROW.match(line.strip())
            if not m:
                continue
            ac, rest = m.group(1), m.group(2)
            if "已废弃" in rest:
                deprecated.append(ac)
            elif ac not in acs:
                acs.append(ac)
    return acs, deprecated


def load_cases(path):
    cases, problems = [], []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append("第 %d 行不是合法 JSON：%s" % (n, e))
                continue
            if not isinstance(c, dict):
                problems.append("第 %d 行不是对象" % n)
                continue
            c["_line"] = n
            cases.append(c)
    return cases, problems


def check_case(c, problems, seen):
    where = "第 %d 行（%s）" % (c["_line"], c.get("id", "无 id"))
    for k in REQUIRED:
        if k not in c or c[k] in ("", None, []):
            problems.append("%s 缺少 %s" % (where, k))
    cid = c.get("id")
    if cid in seen:
        problems.append("%s id 重复" % where)
    seen.add(cid)
    ac = c.get("ac")
    if not isinstance(ac, list) or not all(isinstance(x, str) and re.match(r"^AC-\d+$", x) for x in ac or []):
        problems.append("%s ac 必须是 AC-n 列表" % where)
    for field, allowed in (("type", TYPES), ("layer", LAYERS), ("judge", JUDGES), ("result", RESULTS)):
        if field in c and c[field] not in allowed:
            problems.append("%s %s 非法：%r" % (where, field, c[field]))
    if c.get("result") == "fail" and c.get("severity") not in SEVERITIES:
        problems.append("%s 失败用例必须标 severity（blocker/major/minor）" % where)
    if c.get("judge") in ("rubric", "model_judge", "human") and not c.get("rubric"):
        problems.append("%s judge=%s 需要 rubric（评分标准或其位置）" % (where, c.get("judge")))
    if c.get("result") == "pass" and not c.get("evidence"):
        problems.append("%s 标为 pass 但没有 evidence" % where)


def main(argv=None):
    ap = argparse.ArgumentParser(description="检查评测用例与 AC 覆盖")
    ap.add_argument("product_dir")
    ap.add_argument("--cases")
    ap.add_argument("--prd")
    a = ap.parse_args(argv)
    cases_path = a.cases or os.path.join(a.product_dir, "factory", "eval", "cases.jsonl")
    prd_path = a.prd or os.path.join(a.product_dir, "factory", "prd.md")
    for p in (cases_path, prd_path):
        if not os.path.exists(p):
            print("找不到 %s" % p)
            sys.exit(1)

    acs, deprecated = prd_acs(prd_path)
    cases, problems = load_cases(cases_path)
    seen = set()
    for c in cases:
        check_case(c, problems, seen)

    by_ac = defaultdict(list)
    for c in cases:
        for x in c.get("ac") or []:
            by_ac[x].append(c)
    if not acs:
        problems.append("PRD 中没有找到验收标准表格行（格式：| AC-1 | ... |）")
    uncovered = [x for x in acs if x not in by_ac]
    for x in uncovered:
        problems.append("%s 没有任何用例" % x)
    unknown = sorted(set(by_ac) - set(acs) - set(deprecated))
    for x in unknown:
        problems.append("用例引用了 PRD 中不存在的 %s" % x)
    for x in sorted(set(by_ac) & set(deprecated)):
        print("提示：%s 在 PRD 中已废弃，相关用例可移除或改挂新 AC" % x)

    # 汇总
    res = Counter(c.get("result") for c in cases)
    sev = Counter(c.get("severity") for c in cases if c.get("result") == "fail")
    print("用例 %d 条：pass %d / fail %d / unverified %d / n/a %d" % (
        len(cases), res["pass"], res["fail"], res["unverified"], res["n/a"]))
    if res["fail"]:
        print("失败严重度：blocker %d / major %d / minor %d" % (sev["blocker"], sev["major"], sev["minor"]))
    print("\n| AC | 用例数 | pass | fail | unverified | 结论 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for x in acs:
        cs = by_ac.get(x, [])
        r = Counter(c.get("result") for c in cs)
        if not cs:
            verdict = "未覆盖"
        elif r["fail"]:
            verdict = "未通过"
        elif r["unverified"]:
            verdict = "未验证完"
        else:
            verdict = "通过"
        print("| %s | %d | %d | %d | %d | %s |" % (x, len(cs), r["pass"], r["fail"], r["unverified"], verdict))
    types = Counter(c.get("type") for c in cases)
    for t in ("safety", "reliability"):
        if not types[t]:
            print("\n提示：没有 %s 类用例，确认是否确实不适用。" % t)

    if problems:
        print("\n问题：")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("\n格式与 AC 覆盖检查通过。")


if __name__ == "__main__":
    main()
