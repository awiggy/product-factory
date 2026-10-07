#!/usr/bin/env python3
"""测试用的假 pi：按 pi --mode json 的真实事件格式输出（格式取自 pi 0.73 的实际运行），并写收件箱。"""

import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("FAKE_PI_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"args": args, "stdin_tty": sys.stdin.isatty() if sys.stdin else None},
                           ensure_ascii=False) + "\n")

if args[:1] in (["--version"], ["-v"]):
    print("0.73.1")
    sys.exit(0)
if args[:1] == ["--list-models"]:
    if os.environ.get("FAKE_PI_NO_MODELS"):
        print("No models available. Use /login or set an API key environment variable.")
        sys.exit(0)
    print("provider   model              context  max-out  thinking  images")
    print("anthropic  claude-sonnet-5-5  1M       64K      yes       yes")
    print("deepseek   deepseek-v4-pro    128K     32K      yes       no")
    sys.exit(0)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def assistant(content, stop="stop", err=None, inp=100, outp=20):
    m = {"role": "assistant", "content": content, "api": "openai-completions", "provider": "deepseek",
         "model": "deepseek-v4-pro", "usage": {"input": inp, "output": outp, "cacheRead": 0, "cacheWrite": 0,
                                               "totalTokens": inp + outp, "cost": {"total": 0.0001}},
         "stopReason": stop, "timestamp": 1}
    if err:
        m["errorMessage"] = err
    return m


prompt = args[-1]
sid = args[args.index("--session") + 1] if "--session" in args else "pi-session-1"
out({"type": "session", "version": 3, "id": sid, "timestamp": "t", "cwd": os.getcwd()})
out({"type": "agent_start"})
out({"type": "turn_start"})
if os.environ.get("FAKE_PI_ERROR"):
    for _ in range(2):
        out({"type": "message_end", "message": assistant([], "error", "Connection error.", 0, 0)})
        out({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 3, "delayMs": 10, "errorMessage": "x"})
    out({"type": "message_end", "message": assistant([], "error", "Connection error.", 0, 0)})
    out({"type": "agent_end", "messages": []})
    sys.exit(0)                                   # 真实 pi 在模型报错时也是退出码 0
if "OK" in prompt and "factory" not in prompt:
    out({"type": "message_end", "message": assistant([{"type": "text", "text": "OK"}])})
    out({"type": "agent_end", "messages": []})
    sys.exit(0)
inbox = {"stage": "prd", "round": 1, "status": "needs_input", "summary": "pi 读完了想法。",
         "questions": [{"id": "q1", "text": "给谁用？", "type": "text"}]}
call = {"type": "toolCall", "id": "c1", "name": "write",
        "arguments": {"path": "factory/inbox/prd.json", "content": json.dumps(inbox, ensure_ascii=False)}}
out({"type": "message_end", "message": assistant([{"type": "text", "text": "我先写收件箱。"}, call])})
out({"type": "tool_execution_start", "toolCallId": "c1", "toolName": "write", "args": call["arguments"]})
os.makedirs(os.path.join("factory", "inbox"), exist_ok=True)
with open(os.path.join("factory", "inbox", "prd.json"), "w", encoding="utf-8") as f:
    f.write(call["arguments"]["content"])
out({"type": "tool_execution_end", "toolCallId": "c1", "toolName": "write",
     "result": {"content": [{"type": "text", "text": "ok"}]}, "isError": False})
out({"type": "message_end", "message": assistant([{"type": "text", "text": "已写入收件箱。"}], inp=150, outp=5)})
out({"type": "agent_end", "messages": []})
