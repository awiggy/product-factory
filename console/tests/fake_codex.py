#!/usr/bin/env python3
"""测试用的假 Codex：按 codex exec --json 的事件格式输出，并写收件箱。"""

import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("FAKE_CODEX_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"args": args, "has_key": bool(os.environ.get("CODEX_API_KEY"))}, ensure_ascii=False) + "\n")

if args[:1] == ["--version"]:
    print("codex-cli 0.99.0")
    sys.exit(0)
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT")
    sys.exit(0)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


cwd = args[args.index("--cd") + 1] if "--cd" in args else os.getcwd()
prompt = args[-1]
out({"type": "thread.started", "thread_id": "th-1"})
out({"type": "turn.started"})
out({"type": "item.started", "item": {"id": "1", "type": "command_execution", "command": "cat factory/idea.md",
                                      "status": "in_progress"}})
out({"type": "item.completed", "item": {"id": "1", "type": "command_execution", "command": "cat factory/idea.md",
                                        "exit_code": 0, "status": "completed"}})
if "OK" in prompt and "factory" not in prompt:
    out({"type": "item.completed", "item": {"id": "2", "type": "agent_message", "text": "OK"}})
else:
    os.makedirs(os.path.join(cwd, "factory", "inbox"), exist_ok=True)
    with open(os.path.join(cwd, "factory", "inbox", "prd.json"), "w", encoding="utf-8") as f:
        json.dump({"stage": "prd", "round": 1, "status": "needs_input", "summary": "Codex 读完了想法。",
                   "questions": [{"id": "q1", "text": "给谁用？", "type": "text"}]}, f, ensure_ascii=False)
    out({"type": "item.completed", "item": {"id": "3", "type": "file_change", "status": "completed",
                                            "changes": [{"path": "factory/inbox/prd.json", "kind": "add"}]}})
    out({"type": "item.completed", "item": {"id": "4", "type": "agent_message", "text": "已写入收件箱。"}})
out({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 0, "output_tokens": 300}})
