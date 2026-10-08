"""控制台后端测试（仅标准库）。运行：cd console && python3 -m unittest discover -s tests -v"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["FACTORY_DEMO_DELAY"] = "0"

from factory_console import app, executors, gate, preview, products as pr, runner, secrets  # noqa: E402
from factory_console import inbox as ib  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["FACTORY_SECRETS_FILE"] = os.path.join(self.tmp, "secrets", "secrets.json")
        secrets.FILE_PATH = os.environ["FACTORY_SECRETS_FILE"]
        self._cfg = pr.CONFIG_PATH
        pr.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        pr.update_config({"workspace": os.path.join(self.tmp, "products"), "user_name": "测试"})

    def tearDown(self):
        pr.CONFIG_PATH = self._cfg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait(self, pid, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if not runner.busy(pid):
                return pr.detail(pid, runner.active_meta(pid))
            time.sleep(0.02)
        self.fail("运行超时")

    def run_and_wait(self, pid, mode):
        runner.start(pid, mode)
        return self.wait(pid)


class DemoFlowTest(Base):
    def test_full_demo_flow(self):
        pid = pr.create_product("演示", "", demo=True)
        d = self.run_and_wait(pid, "start")
        self.assertEqual(d["next_action"]["kind"], "answer")
        with self.assertRaises(pr.UserError):
            pr.save_answers(pid, {"q1": "研究生"})          # 必答题没答完
        pr.save_answers(pid, {"q1": "研究生", "q2": "两者都要", "q3": "可以"})
        d = self.run_and_wait(pid, "continue")
        self.assertEqual(d["next_action"]["kind"], "approve")
        with self.assertRaises(pr.UserError):
            pr.approve(pid, "prd_signoff", "确认", acknowledged=False)   # 有未验证项必须先确认
        pr.approve(pid, "prd_signoff", "确认", acknowledged=True)
        self.assertEqual(pr.detail(pid)["next_action"]["kind"], "advance")
        pr.advance(pid)
        self.run_and_wait(pid, "start")
        pr.approve(pid, "blueprint_signoff", "确认", acknowledged=True)
        pr.advance(pid)
        d = self.run_and_wait(pid, "start")                 # adaptation 无需审批
        self.assertEqual(d["next_action"]["kind"], "advance")
        pr.advance(pid)
        d = self.run_and_wait(pid, "start")                 # build：先要用户操作
        self.assertEqual(d["next_action"]["kind"], "actions")
        self.assertEqual(d["stage"]["level"], "mock_passed")
        act = d["inbox"]["user_actions"][0]
        self.assertEqual([f["key"] for f in act["fields"]], ["DEEPSEEK_API_KEY", "MODEL_ID"])
        self.assertEqual(act["fields"][1]["value"], "deepseek-v4-flash")
        with self.assertRaises(pr.UserError):
            pr.save_env(pid, "a1", {"DEEPSEEK_API_KEY": ""})                 # 必填没填
        pr.save_actions(pid, ["a1"])                                          # 填写类不能靠勾选完成
        self.assertNotIn("a1", pr.detail(pid)["actions_done"])
        pr.save_env(pid, "a1", {"DEEPSEEK_API_KEY": "sk-secret-123 x", "MODEL_ID": "deepseek-v4-pro"})
        envp = os.path.join(d["path"], ".env")
        with open(envp, encoding="utf-8") as f:
            env = f.read()
        self.assertIn('DEEPSEEK_API_KEY="sk-secret-123 x"', env)
        self.assertIn("MODEL_ID=deepseek-v4-pro", env)
        self.assertEqual(os.stat(envp).st_mode & 0o777, 0o600)
        with open(os.path.join(d["path"], ".gitignore"), encoding="utf-8") as f:
            self.assertIn(".env", f.read().split())
        d = pr.detail(pid)
        self.assertIn("a1", d["actions_done"])
        self.assertNotIn("sk-secret", json.dumps(d, ensure_ascii=False))     # 页面拿不到 Key
        f0 = d["inbox"]["user_actions"][0]["fields"][0]
        self.assertTrue(f0["filled"] and "value" not in f0)
        prompt = runner.build_prompt(d["path"], "build", "continue")
        self.assertIn("DEEPSEEK_API_KEY（已填，保密）", prompt)
        self.assertNotIn("sk-secret", prompt)                                 # AI 也拿不到
        pr.save_env(pid, "a1", {"DEEPSEEK_API_KEY": "", "MODEL_ID": "deepseek-v4-flash"})   # 留空保持原值
        with open(envp, encoding="utf-8") as f:
            self.assertIn("sk-secret-123", f.read())
        with self.assertRaises(pr.UserError):
            pr.save_env(pid, "a1", {"MODEL_ID": "a\nEVIL=1"})
        d = self.run_and_wait(pid, "continue")
        self.assertEqual(d["next_action"]["kind"], "checklist")
        with self.assertRaises(pr.UserError):
            pr.approve(pid, "build_acceptance", "通过", acknowledged=True)  # 清单没走完不能签
        res = {c["id"]: {"result": "pass"} for c in d["inbox"]["checklist"]}
        res["c2"] = {"result": "fail", "note": "没反应"}
        pr.save_checklist(pid, res)
        d = pr.detail(pid)
        self.assertEqual(d["next_action"]["kind"], "fix")
        self.assertTrue(any("验收未通过" in b for b in d["stage"]["blockers"]))
        d = self.run_and_wait(pid, "fix")
        self.assertEqual(d["stage"]["blockers"], [])       # 新一轮清单，旧的失败阻塞清除
        pr.save_checklist(pid, {c["id"]: {"result": "pass"} for c in d["inbox"]["checklist"]})
        pr.approve(pid, "build_acceptance", "通过", acknowledged=True)
        pr.advance(pid)
        d = self.run_and_wait(pid, "start")
        pr.save_checklist(pid, {c["id"]: {"result": "pass"} for c in d["inbox"]["checklist"]})
        pr.approve(pid, "frontend_acceptance", "通过", acknowledged=True)
        pr.advance(pid)
        self.run_and_wait(pid, "start")
        pr.advance(pid)                                     # qa 无审批
        d = self.run_and_wait(pid, "start")
        self.assertEqual(d["current_stage"], "release")
        with self.assertRaises(pr.UserError):
            runner.start(pid, "deploy")                     # 未授权不能部署
        pr.save_actions(pid, ["a1", "a2"])
        self.assertEqual(pr.detail(pid)["next_action"]["kind"], "release_go")
        with self.assertRaises(pr.UserError):
            pr.approve(pid, "release_go", "同意", scope={"platform": "x"})  # 授权范围不完整
        pr.approve(pid, "release_go", "同意", scope={"platform": "火山", "environment": "生产", "cost": "100 元",
                                                    "visibility": "邀请码"})
        self.assertEqual(pr.detail(pid)["next_action"]["kind"], "deploy")
        d = self.run_and_wait(pid, "deploy")
        self.assertEqual(d["stage"]["level"], "production_verified")
        pr.save_checklist(pid, {c["id"]: {"result": "pass"} for c in d["inbox"]["checklist"]})
        pr.approve(pid, "launch_acceptance", "上线", acknowledged=True)
        pr.advance(pid)
        d = self.run_and_wait(pid, "start")
        self.assertEqual(d["current_stage"], "operate")
        pr.iterate(pid, "批量上传")
        d = pr.detail(pid)
        self.assertEqual(d["product"]["version"], 2)
        self.assertEqual(d["next_action"]["kind"], "start")
        self.assertIsNone(d["inbox"])
        approvals = [a for a in gate.load_state(d["path"])["approvals"]]
        self.assertTrue(all(a.get("via") == "console" for a in approvals))

    def test_feedback_and_skip(self):
        pid = pr.create_product("演示", "", demo=True)
        self.run_and_wait(pid, "start")
        pr.save_answers(pid, {"q1": "a", "q2": "两者都要", "q3": "可以"})
        self.run_and_wait(pid, "continue")
        pr.add_feedback(pid, "revise", "范围再小一点")
        self.assertEqual(pr.detail(pid)["next_action"]["kind"], "continue")
        d = self.run_and_wait(pid, "continue")
        self.assertEqual(d["pending_feedback"], [])
        with open(os.path.join(d["path"], "factory", "prd.md"), encoding="utf-8") as f:
            self.assertIn("范围再小一点", f.read())
        with self.assertRaises((pr.UserError, gate.GateError)):
            pr.skip(pid, "不需要")                           # prd 不可跳过


class EnvFieldsTest(Base):
    def test_old_style_steps_become_fields(self):
        raw = {"status": "needs_input", "summary": "x", "user_actions": [{"id": "a1", "title": "填写模型 Key 和型号", "steps": [
            "在产品文件夹里把 .env.example 复制一份，改名为 .env",
            "在 LLM_API_KEY= 后面粘贴你的 DeepSeek Key",
            "在 LLM_MODEL= 后面填型号名",
            "可选：在 LLM_PRICE_INPUT_PER_M / LLM_PRICE_OUTPUT_PER_M 填每百万 token 的美元单价"]}]}
        box, _ = ib.normalize(raw, "build")
        fs = box["user_actions"][0]["fields"]
        self.assertEqual([(f["key"], f["secret"], f["required"]) for f in fs], [
            ("LLM_API_KEY", True, True), ("LLM_MODEL", False, True),
            ("LLM_PRICE_INPUT_PER_M", False, False), ("LLM_PRICE_OUTPUT_PER_M", False, False)])
        self.assertEqual(box["user_actions"][0]["file"], ".env")
        self.assertEqual([k for k in ("LLM_API_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "LLM_MAX_OUTPUT_TOKENS",
                                       "LLM_CONTEXT_TOKENS", "KEYWORDS", "MONKEY_COUNT") if ib.is_secret_key(k)],
                         ["LLM_API_KEY", "GITHUB_TOKEN", "DB_PASSWORD"])
        self.assertEqual(ib.env_file("../../etc/passwd"), ".env")
        self.assertEqual(ib.env_file("backend/.env"), "backend/.env")
        self.assertEqual(ib.env_file(".env.example"), ".env")
        raw["user_actions"][0]["steps"] = ["去官网注册账号"]
        self.assertEqual(ib.normalize(raw, "build")[0]["user_actions"][0]["fields"], [])


class PreviewTest(Base):
    def make(self, script, checklist_text, preview_field=None):
        pid = pr.create_product("预览", "想法")
        pdir = pr.find(pid)["path"]
        with open(os.path.join(pdir, "start.sh"), "w") as f:
            f.write(script)
        os.chmod(os.path.join(pdir, "start.sh"), 0o755)
        raw = {"stage": "prd", "status": "ready_for_review", "summary": "s",
               "checklist": [{"id": "c1", "do": checklist_text, "expect": "看到页面"}]}
        if preview_field:
            raw["preview"] = preview_field
        os.makedirs(ib.inbox_dir(pdir), exist_ok=True)
        ib.write_json(ib.path(pdir, "prd"), raw)
        return pid, pdir

    def free_port(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def wait_status(self, pid, want, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            st = pr.detail(pid)["preview"]
            if st["status"] in want:
                return st
            time.sleep(0.2)
        self.fail("预览状态一直是 %s" % st)

    def test_start_open_stop(self):
        port = self.free_port()
        script = '#!/bin/sh\necho "starting sk-abc123"\nexec "%s" -m http.server %d --bind 127.0.0.1\n' % (sys.executable, port)
        pid, pdir = self.make(script, "在终端进入产品文件夹，运行 ./start.sh，浏览器打开 http://127.0.0.1:%d" % port)
        st = pr.detail(pid)["preview"]
        self.assertTrue(st["available"])
        self.assertEqual((st["status"], st["command"], st["url"]), ("idle", "./start.sh", "http://127.0.0.1:%d" % port))
        preview.start(pid, pdir, pr.read_inbox(pdir, "prd")[0])
        st = self.wait_status(pid, ("running",))
        self.assertNotIn("sk-abc123", st["log"])                 # 日志里的密钥打码
        self.assertEqual(preview.start(pid, pdir, pr.read_inbox(pdir, "prd")[0])["status"], "running")  # 不重复启动
        self.assertTrue(preview.stop(pid))
        st = self.wait_status(pid, ("stopped",))
        self.assertFalse(preview._reachable(st["url"]))
        import http.server
        srv = http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(ValueError):                   # 端口被别的程序占着时给出提示
                preview.start(pid, pdir, pr.read_inbox(pdir, "prd")[0])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_declared_preview_and_failure(self):
        port = self.free_port()
        pid, pdir = self.make("#!/bin/sh\necho boom; exit 3\n", "打开页面看看",
                              {"command": "./start.sh", "url": "http://localhost:%d/app" % port})
        self.assertEqual(pr.detail(pid)["preview"]["url"], "http://localhost:%d/app" % port)
        preview.start(pid, pdir, pr.read_inbox(pdir, "prd")[0])
        st = self.wait_status(pid, ("failed", "exited"))
        self.assertIn("boom", st["log"])
        self.assertIn("代码 3", st["message"])

    def test_rejects_unsafe_specs(self):
        pid, pdir = self.make("#!/bin/sh\n", "运行 ./start.sh", {"command": "../../bin/sh", "url": "http://127.0.0.1:1"})
        box = pr.read_inbox(pdir, "prd")[0]
        self.assertEqual(preview.spec(pdir, box)["command"], "start.sh")          # 回退为推断，且只用产品内脚本
        box["preview"] = {"command": "./start.sh", "url": "http://example.com"}
        box["checklist"] = []
        self.assertIsNone(preview.spec(pdir, box))                                  # 非本机地址不接受
        box["preview"] = {"command": "./start.sh; rm -rf ~", "url": "http://127.0.0.1:9"}
        self.assertIsNone(preview.spec(pdir, box))                                  # 不接受 shell 拼接

    def test_ai_run_stops_preview(self):
        port = self.free_port()
        script = '#!/bin/sh\nexec "%s" -m http.server %d --bind 127.0.0.1\n' % (sys.executable, port)
        pid, pdir = self.make(script, "运行 ./start.sh 打开 http://127.0.0.1:%d" % port)
        preview.start(pid, pdir, pr.read_inbox(pdir, "prd")[0])
        self.wait_status(pid, ("running",))
        self.run_and_wait(pid, "continue")                                          # 演示执行器
        self.assertEqual(preview._procs[pid].status, "stopped")
        self.assertFalse(preview._reachable("http://127.0.0.1:%d" % port))


class ConfigAndFilesTest(Base):
    def test_config_edit_and_file_view(self):
        pid = pr.create_product("配置", "想法")
        pdir = pr.find(pid)["path"]
        with open(os.path.join(pdir, ".env.example"), "w") as f:
            f.write("LLM_API_KEY=\nLLM_MODEL=deepseek-v4-flash\nPORT=8000\n")
        self.assertTrue(pr.detail(pid)["has_config"])
        c = pr.env_config(pid)
        self.assertEqual([(f["key"], f["secret"], f["filled"]) for f in c["fields"]],
                         [("LLM_API_KEY", True, False), ("LLM_MODEL", False, False), ("PORT", False, False)])
        pr.save_env_config(pid, {"LLM_API_KEY": "sk-real-key-999", "LLM_MODEL": "deepseek-v4-pro", "PORT": "8000"})
        c = pr.env_config(pid)
        self.assertNotIn("sk-real", json.dumps(c))
        self.assertTrue(c["fields"][0]["filled"])
        pr.save_env_config(pid, {"LLM_API_KEY": "", "LLM_MODEL": "deepseek-v4-flash"})       # 保密项留空 = 不变
        with open(os.path.join(pdir, ".env")) as f:
            env = f.read()
        self.assertIn("LLM_API_KEY=sk-real-key-999", env)
        self.assertIn("LLM_MODEL=deepseek-v4-flash", env)
        with self.assertRaises(pr.UserError):
            pr.save_env_config(pid, {"EVIL": "1"})
        # 查看日志：发现泄露时打码并警告
        os.makedirs(os.path.join(pdir, "data"))
        with open(os.path.join(pdir, "data", "app.log"), "w") as f:
            f.write("ok\ncalling with sk-real-key-999\n")
        v = pr.view_file(pid, "data/app.log")
        self.assertEqual(v["leaked_secrets"], ["LLM_API_KEY"])
        self.assertNotIn("sk-real", v["text"])
        with open(os.path.join(pdir, "data", "app.log"), "w") as f:
            f.write("clean\n")
        self.assertEqual(pr.view_file(pid, "./data/app.log")["leaked_secrets"], [])
        self.assertFalse(pr.view_file(pid, "data/none.log")["exists"])
        for bad in (".env", "../x.log", "/etc/passwd", ".git/config", "data/.env.log", "start.sh"):
            with self.assertRaises(pr.UserError, msg=bad):
                pr.view_file(pid, bad)


class ClaudeExecutorTest(Base):
    def wrapper(self, name, script):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, os.path.join(HERE, script)))
        os.chmod(path, 0o755)
        return path

    def test_fake_claude_guards(self):
        fake = self.wrapper("claude", "fake_claude.py")
        logf = os.path.join(self.tmp, "args.log")
        os.environ["FAKE_CLAUDE_LOG"] = logf
        pr.update_config({"executor": "claude", "claude_path": fake, "budget_per_run_usd": 2})
        pid = pr.create_product("真产品", "做一个论文助手")
        d = self.run_and_wait(pid, "start")
        run = d["runs"][0]
        self.assertEqual(run["status"], "succeeded", run.get("error"))
        self.assertEqual(run["cost_usd"], 0.0123)
        self.assertTrue(any("state.json" in n for n in run["notes"]))       # 篡改被发现
        state = gate.load_state(d["path"])
        self.assertEqual(state["approvals"], [])                           # 伪造审批被撤销
        self.assertNotEqual(d["stage"]["level"], "production_verified")    # 越级证据不被接受
        self.assertEqual(d["next_action"]["kind"], "answer")
        with open(logf, encoding="utf-8") as f:
            args = json.loads(f.readlines()[-1])
        self.assertEqual(args[-2], "-p")
        self.assertIn("dontAsk", args)                                     # prd 阶段只读档位
        self.assertIn("--add-dir", args)
        self.assertIn("Edit(./factory/state.json)", args)
        self.assertEqual(args[args.index("--max-budget-usd") + 1], "2.0")
        sessions = ib.read_json(os.path.join(d["path"], "factory", "runs", "sessions.json"))
        self.assertEqual(sessions["prd"], "sess-123")
        # 继续时接着上次的对话
        pr.save_answers(pid, {"q1": "研究生"})
        self.run_and_wait(pid, "continue")
        with open(logf, encoding="utf-8") as f:
            args = json.loads(f.readlines()[-1])
        self.assertIn("--resume", args)
        prompt = args[-1]
        self.assertIn("问：给谁用？", prompt)
        self.assertIn("答：研究生", prompt)
        info = executors.detect(pr.load_config())
        self.assertTrue(info["claude"]["found"])
        self.assertTrue(info["claude"]["logged_in"])

    def test_provider_api_key(self):
        fake = self.wrapper("claude", "fake_claude.py")
        envlog = os.path.join(self.tmp, "env.log")
        os.environ["FAKE_CLAUDE_ENVLOG"] = envlog
        os.environ["FAKE_CLAUDE_LOG"] = os.path.join(self.tmp, "args2.log")
        pr.update_config({"executor": "claude", "claude_path": fake, "claude_source": "provider",
                          "provider_id": "deepseek", "provider_base_url": "https://api.deepseek.com/anthropic",
                          "provider_model": "deepseek-v4-pro"})
        pid = pr.create_product("第三方", "一个想法")
        with self.assertRaises(pr.UserError):
            runner.start(pid, "start")                    # 还没保存 Key
        secrets.set_secret(executors.provider_account("deepseek"), "sk-test-1234567890")
        self.assertEqual(secrets.masked(executors.provider_account("deepseek")), "已保存（尾号 7890）")
        self.assertEqual(oct(os.stat(secrets.FILE_PATH).st_mode & 0o777), "0o600")
        d = self.run_and_wait(pid, "start")
        self.assertEqual(d["runs"][0]["status"], "succeeded", d["runs"][0].get("error"))
        self.assertIsNone(d["runs"][0]["cost_usd"])       # 第三方不按 Claude 价格估算
        with open(envlog) as f:
            env = json.loads(f.readlines()[-1])
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-test-1234567890")
        self.assertEqual(env["ANTHROPIC_MODEL"], "deepseek-v4-pro")
        self.assertIsNone(env["ANTHROPIC_API_KEY"])
        for root, _, files in os.walk(d["path"]):          # Key 不出现在产品文件里
            for fn in files:
                with open(os.path.join(root, fn), "rb") as f:
                    self.assertNotIn(b"sk-test-1234567890", f.read())
        self.assertTrue(executors.test_connection(pr.load_config())["ok"])

    def test_pi(self):
        fake = self.wrapper("pi", "fake_pi.py")
        logf = os.path.join(self.tmp, "pi.log")
        os.environ["FAKE_PI_LOG"] = logf
        pr.update_config({"executor": "pi", "pi_path": fake, "pi_model": "deepseek/deepseek-v4-pro",
                          "pi_thinking": "high"})
        info = executors.detect(pr.load_config())["pi"]
        self.assertTrue(info["found"] and info["logged_in"])
        self.assertEqual([m["value"] for m in info["models"]],
                         ["anthropic/claude-sonnet-5-5", "deepseek/deepseek-v4-pro"])
        self.assertEqual(executors.label(pr.load_config()), "pi + deepseek/deepseek-v4-pro")
        with self.assertRaises(pr.UserError):
            pr.update_config({"pi_model": "bad model; rm -rf"})
        with self.assertRaises(pr.UserError):
            pr.update_config({"pi_thinking": "max"})

        pid = pr.create_product("pi 产品", "一个想法")
        d = self.run_and_wait(pid, "start")
        run = d["runs"][0]
        self.assertEqual(run["status"], "succeeded", run.get("error"))
        self.assertEqual(run["tokens"], {"input": 250, "output": 25})
        self.assertEqual(d["next_action"]["kind"], "answer")
        with open(logf, encoding="utf-8") as f:
            calls = [json.loads(x) for x in f]
        a = calls[-1]["args"]
        self.assertFalse(calls[-1]["stdin_tty"])
        self.assertEqual(a[a.index("--tools") + 1], "read,write,edit,grep,find,ls")   # 需求阶段不给 bash
        self.assertEqual(a[a.index("--model") + 1], "deepseek/deepseek-v4-pro")
        self.assertEqual(a[a.index("--thinking") + 1], "high")
        self.assertIn("--skill", a)
        self.assertNotIn("--session", a)

        pr.save_answers(pid, {"q1": "研究生"})
        d = self.run_and_wait(pid, "continue")
        with open(logf, encoding="utf-8") as f:
            a = json.loads(f.read().splitlines()[-1])["args"]
        self.assertEqual(a[a.index("--session") + 1], "pi-session-1")              # 接着上次的对话

        os.environ["FAKE_PI_ERROR"] = "1"
        try:
            d = self.run_and_wait(pid, "continue")
        finally:
            os.environ.pop("FAKE_PI_ERROR")
        self.assertEqual(d["runs"][0]["status"], "failed")
        self.assertIn("Connection error", d["runs"][0]["error"])                    # 退出码 0 也要判为失败

        self.assertTrue(executors.test_connection(pr.load_config())["ok"])
        os.environ["FAKE_PI_NO_MODELS"] = "1"
        try:
            info = executors.detect(pr.load_config())["pi"]
        finally:
            os.environ.pop("FAKE_PI_NO_MODELS")
            os.environ.pop("FAKE_PI_LOG")
        self.assertFalse(info["logged_in"])

    def test_scan_and_defaults(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        for name, script in (("pi", "fake_pi.py"), ("codex", "fake_codex.py")):
            p = os.path.join(bindir, name)
            with open(p, "w") as f:
                f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, os.path.join(HERE, script)))
            os.chmod(p, 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = bindir + os.pathsep + old
        home = os.path.join(self.tmp, "codexhome")
        os.makedirs(home)
        with open(os.path.join(home, "config.toml"), "w") as f:
            f.write('model = "gpt-test"\n[profiles.fast]\nmodel = "other"\n')
        os.environ["CODEX_HOME"] = home
        try:
            found = {c["id"]: c for c in executors.scan_clis()}
            self.assertEqual(found["pi"]["version"], "0.73.1")
            self.assertTrue(found["pi"]["supported"])
            self.assertEqual(executors.codex_default_model(), "gpt-test")
        finally:
            os.environ["PATH"] = old
            os.environ.pop("CODEX_HOME")

    def test_codex(self):
        fake = self.wrapper("codex", "fake_codex.py")
        logf = os.path.join(self.tmp, "codex.log")
        os.environ["FAKE_CODEX_LOG"] = logf
        pr.update_config({"executor": "codex", "codex_path": fake})
        info = executors.detect(pr.load_config())["codex"]
        self.assertTrue(info["found"] and info["logged_in"])
        pid = pr.create_product("Codex 产品", "一个想法")
        d = self.run_and_wait(pid, "start")
        run = d["runs"][0]
        self.assertEqual(run["status"], "succeeded", run.get("error"))
        self.assertEqual(run["tokens"], {"input": 1200, "output": 300})
        self.assertEqual(d["next_action"]["kind"], "answer")
        with open(logf) as f:
            rec = [json.loads(l) for l in f if '"exec"' in l][-1]
        args = rec["args"]
        self.assertEqual(args[:2], ["exec", "--json"])
        self.assertIn("workspace-write", args)
        self.assertNotIn("sandbox_workspace_write.network_access=true", args)   # 需求阶段不联网
        self.assertFalse(rec["has_key"])
        meta = runner.get_run(pid, run["id"])
        texts = [a["text"] for a in meta["activity"]]
        self.assertIn("运行命令：cat factory/idea.md", texts)
        self.assertIn("写入 factory/inbox/prd.json", texts)
        # API Key 方式
        pr.update_config({"codex_source": "api_key"})
        self.assertIn("OpenAI", executors.ready_problem(pr.load_config()))
        secrets.set_secret(executors.OPENAI_ACCOUNT, "sk-openai-abcdefgh")
        self.assertTrue(executors.test_connection(pr.load_config())["ok"])
        with open(logf) as f:
            self.assertTrue(json.loads(f.readlines()[-1])["has_key"])

    def test_manual_mode(self):
        pr.update_config({"executor": "manual"})
        pid = pr.create_product("手动", "一个想法")
        meta = runner.start(pid, "start")
        self.assertEqual(meta["status"], "waiting_manual")
        self.assertIn("请在这个产品文件夹里工作", meta["prompt"])
        self.assertEqual(pr.detail(pid, runner.active_meta(pid))["next_action"]["kind"], "manual_wait")
        pdir = pr.find(pid)["path"]
        ib.write_json(ib.path(pdir, "prd"), {"stage": "prd", "round": 1, "status": "needs_input", "summary": "s",
                                             "questions": [{"id": "q1", "text": "谁用？"}]})
        runner.manual_done(pid)
        self.assertEqual(pr.detail(pid)["next_action"]["kind"], "answer")


class HttpTest(Base):
    def setUp(self):
        super().setUp()
        self.srv = app.make_server(port=0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def call(self, method, path, body=None, headers=None):
        h = {"X-Factory": "1", "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, headers=h,
                                     data=json.dumps(body or {}).encode() if method == "POST" else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_security(self):
        code, _ = self.call("POST", "/api/products/demo", headers={"X-Factory": ""})
        self.assertEqual(code, 403)
        code, _ = self.call("GET", "/api/products", headers={"Host": "evil.example:80"})
        self.assertEqual(code, 403)
        code, data = self.call("POST", "/api/products/demo")
        pid = data["id"]
        code, _ = self.call("GET", "/api/products/%s/doc?path=../../../etc/passwd" % pid)
        self.assertEqual(code, 403)
        code, _ = self.call("GET", "/api/products/%s/doc?path=factory/state.json" % pid)
        self.assertEqual(code, 403)
        code, data = self.call("GET", "/api/products/%s" % pid)
        self.assertEqual(code, 200)
        self.assertEqual(data["next_action"]["kind"], "start")

    def test_executor_api(self):
        code, data = self.call("GET", "/api/executors")
        self.assertEqual(code, 200)
        self.assertIn("claude", data["detected"])
        self.assertTrue(any(p["id"] == "deepseek" for p in data["providers"]))
        code, data = self.call("POST", "/api/secrets", {"kind": "provider", "provider_id": "kimi-cn", "value": "sk-kimi-00001111"})
        self.assertEqual(code, 200)
        self.assertEqual(data["masked"], "已保存（尾号 1111）")
        code, data = self.call("GET", "/api/executors")
        self.assertEqual(data["provider_keys"]["kimi-cn"], "已保存（尾号 1111）")
        self.assertNotIn("sk-kimi-00001111", json.dumps(data))
        code, _ = self.call("POST", "/api/secrets", {"kind": "provider", "provider_id": "evil", "value": "x"})
        self.assertEqual(code, 400)
        code, _ = self.call("POST", "/api/config", {"provider_base_url": "http://insecure"})
        self.assertEqual(code, 400)
        self.call("POST", "/api/secrets/delete", {"kind": "provider", "provider_id": "kimi-cn"})
        code, data = self.call("GET", "/api/executors")
        self.assertIsNone(data["provider_keys"]["kimi-cn"])

    def test_static(self):
        with urllib.request.urlopen("http://127.0.0.1:%d/" % self.port) as r:
            self.assertIn("产品工厂", r.read().decode("utf-8"))
        with urllib.request.urlopen("http://127.0.0.1:%d/app.js" % self.port) as r:
            self.assertIn("javascript", r.headers["Content-Type"])


if __name__ == "__main__":
    unittest.main()
