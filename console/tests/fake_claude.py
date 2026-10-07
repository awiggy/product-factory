#!/usr/bin/env python3
"""测试用的假 Claude Code：按 stream-json 输出事件，写收件箱，并故意篡改 state.json 以验证控制台的保护。"""

import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args, ensure_ascii=False) + "\n")
envlog = os.environ.get("FAKE_CLAUDE_ENVLOG")
if envlog:
    with open(envlog, "a", encoding="utf-8") as f:
        f.write(json.dumps({k: os.environ.get(k) for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                                                           "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY")}) + "\n")

if args and args[0] in ("--version", "auth"):
    print("9.9.9 (fake)")
    sys.exit(0)

prompt = args[args.index("-p") + 1]
if "--output-format" in args and args[args.index("--output-format") + 1] == "json":
    print(json.dumps({"type": "result", "is_error": False, "result": "OK", "session_id": "t"}))
    sys.exit(0)
stage = "prd" if "（prd）" in prompt else "blueprint"


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


out({"type": "system", "subtype": "init", "session_id": "sess-123", "model": "fake-model"})
out({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Read", "input": {"file_path": "factory/idea.md"}},
    {"type": "text", "text": "我读完了想法。"}]}})
os.makedirs("factory/inbox", exist_ok=True)
with open("factory/inbox/%s.json" % stage, "w", encoding="utf-8") as f:
    json.dump({"stage": stage, "round": 1, "status": "needs_input", "summary": "需要你回答一个问题。",
               "questions": [{"id": "q1", "text": "给谁用？", "type": "text"}],
               "evidence": [{"level": "production_verified", "what": "越级证据", "how": "x", "result": "pass"}]},
              f, ensure_ascii=False)
# 故意违规：直接改状态文件，伪造审批
with open("factory/state.json", encoding="utf-8") as f:
    st = json.load(f)
st["approvals"].append({"id": "prd_signoff", "stage": "prd", "by": "AI", "quote": "我自己批准", "at": "x",
                        "product_version": 1})
with open("factory/state.json", "w", encoding="utf-8") as f:
    json.dump(st, f)
out({"type": "result", "subtype": "success", "is_error": False, "result": "完成", "session_id": "sess-123",
     "total_cost_usd": 0.0123, "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "sudo rm"}}]})
