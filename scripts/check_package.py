#!/usr/bin/env python3
"""检查 Skill 包结构（仅标准库，3.9+）。在仓库根目录运行：python3 scripts/check_package.py

检查：
- skills/ 下每个目录都有 SKILL.md，frontmatter 的 name 与目录名一致、description 非空且 ≤ 1024 字符
- SKILL.md 正文长度预算（避免入口过长）
- 所有 Markdown 相对链接存在，且不指向本 Skill 目录之外
- agents/openai.yaml 存在且 default_prompt 引用 $<name>
- 所有 .json 可解析，.py 可编译
- 不包含 .env、.DS_Store、__pycache__、.venv 等不该分发的文件
"""

import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILLS = os.path.join(ROOT, "skills")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BODY_LIMIT_CHARS = 6000
FORBIDDEN = {".env", ".DS_Store"}
FORBIDDEN_DIRS = {".venv", "node_modules"}
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".git"}  # 运行产物，已在 .gitignore 中

problems = []


def err(msg):
    problems.append(msg)


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, text
    fm, body = text[4:end], text[end + 5:]
    meta = {}
    for line in fm.splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta, body


def check_links(path, base_dir, boundary):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 忽略代码块中的内容
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+://", target) or target.startswith("#") or target.startswith("mailto:"):
            continue
        t = target.split("#", 1)[0]
        if not t:
            continue
        full = os.path.normpath(os.path.join(base_dir, t))
        rel = os.path.relpath(path, ROOT)
        if not os.path.exists(full):
            err("%s 链接不存在：%s" % (rel, target))
        elif boundary and not full.startswith(boundary + os.sep) and full != boundary:
            err("%s 链接越出 Skill 目录：%s" % (rel, target))


def main():
    names = []
    for name in sorted(os.listdir(SKILLS)):
        d = os.path.join(SKILLS, name)
        if not os.path.isdir(d):
            continue
        names.append(name)
        sk = os.path.join(d, "SKILL.md")
        if not os.path.exists(sk):
            err("%s 缺少 SKILL.md" % name)
            continue
        with open(sk, encoding="utf-8") as f:
            text = f.read()
        meta, body = parse_frontmatter(text)
        if meta is None:
            err("%s/SKILL.md 缺少 YAML frontmatter" % name)
            continue
        if meta.get("name") != name:
            err("%s/SKILL.md 的 name=%r 与目录名不一致" % (name, meta.get("name")))
        desc = meta.get("description", "")
        if not desc:
            err("%s/SKILL.md 缺少 description" % name)
        elif len(desc) > 1024:
            err("%s description 超过 1024 字符（%d）" % (name, len(desc)))
        if "<" in desc or ">" in desc:
            err("%s description 不应包含尖括号" % name)
        if len(body) > BODY_LIMIT_CHARS:
            err("%s/SKILL.md 正文 %d 字符，超过预算 %d；把细节移到 references/" % (name, len(body), BODY_LIMIT_CHARS))
        oy = os.path.join(d, "agents", "openai.yaml")
        if not os.path.exists(oy):
            err("%s 缺少 agents/openai.yaml" % name)
        else:
            with open(oy, encoding="utf-8") as f:
                y = f.read()
            if "$" + name not in y:
                err("%s/agents/openai.yaml 的 default_prompt 未引用 $%s" % (name, name))
        for root, dirs, files in os.walk(d):
            for fn in files:
                if fn.endswith(".md"):
                    check_links(os.path.join(root, fn), root, d)

    # 仓库级 Markdown 链接（不限制边界）
    for top in ("README.md", "CHANGELOG.md"):
        p = os.path.join(ROOT, top)
        if os.path.exists(p):
            check_links(p, ROOT, None)
    docs = os.path.join(ROOT, "docs")
    if os.path.isdir(docs):
        for fn in os.listdir(docs):
            if fn.endswith(".md"):
                check_links(os.path.join(docs, fn), docs, None)

    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in IGNORED_DIRS]
        for dn in dirs:
            if dn in FORBIDDEN_DIRS:
                err("不应分发的目录：%s" % os.path.relpath(os.path.join(root, dn), ROOT))
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, ROOT)
            if fn in FORBIDDEN:
                err("不应分发的文件：%s" % rel)
            if fn.endswith(".json"):
                try:
                    with open(p, encoding="utf-8") as f:
                        json.load(f)
                except Exception as e:  # noqa: BLE001
                    err("%s 不是合法 JSON：%s" % (rel, e))
            if fn.endswith(".jsonl"):
                with open(p, encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if line.strip():
                            try:
                                json.loads(line)
                            except Exception as e:  # noqa: BLE001
                                err("%s 第 %d 行不是合法 JSON：%s" % (rel, n, e))
            if fn.endswith(".py"):
                try:
                    with open(p, encoding="utf-8") as f:
                        compile(f.read(), p, "exec")
                except SyntaxError as e:
                    err("%s 无法编译：%s" % (rel, e))

    print("Skill：%s" % ", ".join(names))
    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("包结构检查通过。")


if __name__ == "__main__":
    main()
