"""工厂状态机与评测脚本的端到端测试（仅标准库）。运行：python3 -m unittest discover -s tests -v"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATE = os.path.join(ROOT, "skills", "product-factory", "scripts", "factory_gate.py")
EVAL = os.path.join(ROOT, "skills", "qa-eval", "scripts", "eval_cases.py")


def run(*args, ok=True):
    p = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise AssertionError("命令失败 %s\nstdout:%s\nstderr:%s" % (args, p.stdout, p.stderr))
    return p


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class FactoryFlowTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def state(self):
        with open(os.path.join(self.d, "factory", "state.json"), encoding="utf-8") as f:
            return json.load(f)

    def gate(self, *args, ok=True):
        return run(GATE, args[0], self.d, *args[1:], ok=ok)

    def approve(self, aid):
        self.gate("approve", "--id", aid, "--by", "测试负责人", "--quote", "批准")

    def test_full_flow(self):
        self.gate("init", "--name", "测试产品")
        self.assertEqual(self.state()["current_stage"], "prd")
        # init 不覆盖
        self.assertNotEqual(self.gate("init", "--name", "x", ok=False).returncode, 0)

        # prd：缺交接物 → 未通过
        self.assertEqual(self.gate("check", ok=False).returncode, 1)
        # 仍含模板标记 → 未通过
        write(os.path.join(self.d, "factory/prd.md"), "<!-- factory:template -->\n# PRD\n| AC-1 | a |\n")
        out = self.gate("check", ok=False)
        self.assertIn("模板标记", out.stdout)
        write(os.path.join(self.d, "factory/prd.md"), "# PRD\n| AC-1 | 上传 | x |\n| AC-2 | 越权 | y |\n")
        # 缺证据与审批
        out = self.gate("advance", ok=False)
        self.assertIn("证据等级不足", out.stdout)
        self.assertIn("prd_signoff", out.stdout)
        self.gate("evidence", "--level", "planned", "--what", "PRD 完成", "--how", "写作", "--result", "pass")
        self.approve("prd_signoff")
        self.gate("advance")
        self.assertEqual(self.state()["current_stage"], "blueprint")

        # blueprint
        write(os.path.join(self.d, "factory/blueprint.md"), "# 蓝图\n")
        self.gate("evidence", "--level", "planned", "--what", "蓝图", "--how", "写作", "--result", "pass")
        self.approve("blueprint_signoff")
        self.gate("advance")

        # adaptation：条件审批必须先声明
        write(os.path.join(self.d, "factory/adaptation.md"), "# 适配\n")
        write(os.path.join(self.d, "factory/stages/plan.md"), "# 计划\n")
        self.gate("evidence", "--level", "planned", "--what", "适配", "--how", "写作", "--result", "pass")
        out = self.gate("check", ok=False)
        self.assertIn("approval-required", out.stdout)
        self.gate("set", "--approval-required", "false")
        self.gate("advance")
        self.assertEqual(self.state()["current_stage"], "build")

        # build：mock 不足以通过；失败证据未处理阻止通过
        write(os.path.join(self.d, "factory/stages/handoff.md"), "# 交接\n")
        self.gate("evidence", "--level", "mock_passed", "--what", "pytest", "--how", "pytest -q", "--result", "pass")
        self.approve("build_acceptance")
        out = self.gate("check", ok=False)
        self.assertIn("需要 real_passed", out.stdout)
        self.gate("evidence", "--level", "real_passed", "--what", "真实冒烟", "--how", "curl", "--result", "fail")
        self.gate("evidence", "--level", "real_passed", "--what", "真实冒烟重跑", "--how", "curl", "--result", "pass")
        out = self.gate("check", ok=False)
        self.assertIn("失败且未处理", out.stdout)
        self.gate("evidence", "--resolve", "1", "--resolution", "修复超时后重跑通过")
        # 阻塞项
        self.gate("blocker", "--add", "缺少用户确认的阈值")
        self.assertEqual(self.state()["stages"]["build"]["status"], "blocked")
        self.assertEqual(self.gate("check", ok=False).returncode, 1)
        self.gate("blocker", "--clear", "0", "--resolution", "用户已确认")
        self.gate("advance")

        # frontend：可跳过但需理由
        self.gate("set", "--skip", "纯 API 产品，无界面")
        self.gate("advance")
        self.assertEqual(self.state()["stages"]["frontend"]["status"], "skipped")

        # qa：用 waive 豁免证据等级
        for f in ("plan.md", "report.md"):
            write(os.path.join(self.d, "factory/eval", f), "# x\n")
        write(os.path.join(self.d, "factory/eval/cases.jsonl"), "{}\n")
        out = self.gate("check", ok=False)
        self.assertIn("证据等级不足", out.stdout)
        self.gate("waive", "--item", "min_evidence", "--reason", "测试豁免", "--by", "测试负责人", "--quote", "接受")
        self.gate("advance")

        # release：部署前 require
        self.assertEqual(self.gate("require", "--id", "release_go", ok=False).returncode, 1)
        self.approve("release_go")
        self.gate("require", "--id", "release_go")
        write(os.path.join(self.d, "factory/release/record.md"), "# 发布\n")
        self.gate("evidence", "--level", "production_verified", "--what", "线上验证", "--how", "测试账号", "--result", "pass")
        out = self.gate("check", ok=False)
        self.assertIn("launch_acceptance", out.stdout)
        self.approve("launch_acceptance")
        self.gate("advance")
        self.assertEqual(self.state()["current_stage"], "operate")
        # operate 不能 advance
        self.assertNotEqual(self.gate("advance", ok=False).returncode, 0)

        # iterate：归档并开始 v2，旧审批不再生效
        self.gate("iterate", "--reason", "增加批量上传")
        st = self.state()
        self.assertEqual(st["product"]["version"], 2)
        self.assertEqual(st["current_stage"], "prd")
        self.assertTrue(os.path.exists(os.path.join(self.d, "factory/history/v1/state.json")))
        self.gate("evidence", "--level", "planned", "--what", "PRD v2", "--how", "修订", "--result", "pass")
        out = self.gate("check", ok=False)
        self.assertIn("prd_signoff", out.stdout)

        # status 可运行
        self.assertIn("当前阶段", self.gate("status").stdout)

    def test_invalid_inputs(self):
        self.gate("init", "--name", "p")
        self.assertNotEqual(self.gate("approve", "--id", "nope", "--by", "a", "--quote", "b", ok=False).returncode, 0)
        self.assertNotEqual(self.gate("evidence", "--level", "great", "--what", "a", "--how", "b",
                                      "--result", "pass", ok=False).returncode, 0)
        self.assertNotEqual(self.gate("set", "--stage", "build", "--skip", "x", ok=False).returncode, 0)
        # 损坏的 state.json 给出清晰错误
        write(os.path.join(self.d, "factory/state.json"), "{bad")
        out = self.gate("status", ok=False)
        self.assertIn("不是合法 JSON", out.stderr)


class EvalCasesTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        write(os.path.join(self.d, "factory/prd.md"),
              "| 编号 | 场景 |\n| --- | --- |\n| AC-1 | a |\n| AC-2 | b |\n| AC-3 | 已废弃（v2） |\n")

    def tearDown(self):
        shutil.rmtree(self.d)

    def cases(self, rows):
        write(os.path.join(self.d, "factory/eval/cases.jsonl"),
              "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    def base(self, **kw):
        c = {"id": "TC-1", "ac": ["AC-1"], "type": "functional", "layer": "mock", "input": "i",
             "expected": "e", "judge": "rule", "result": "pass", "evidence": "pytest"}
        c.update(kw)
        return c

    def test_uncovered_and_errors(self):
        self.cases([self.base(), self.base(id="TC-2", ac=["AC-9"], result="fail")])
        p = run(EVAL, self.d, ok=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("AC-2 没有任何用例", p.stdout)
        self.assertIn("不存在的 AC-9", p.stdout)
        self.assertIn("severity", p.stdout)

    def test_pass(self):
        self.cases([self.base(), self.base(id="TC-2", ac=["AC-2"], type="safety", result="unverified", evidence="")])
        p = run(EVAL, self.d)
        self.assertIn("格式与 AC 覆盖检查通过", p.stdout)
        self.assertIn("| AC-2 | 1 | 0 | 0 | 1 | 未验证完 |", p.stdout)

    def test_example_file_is_valid_format(self):
        ex = os.path.join(ROOT, "skills", "qa-eval", "assets", "cases.example.jsonl")
        prd = os.path.join(self.d, "prd.md")
        write(prd, "".join("| AC-%d | x |\n" % i for i in (1, 3, 6, 8)))
        run(EVAL, self.d, "--cases", ex, "--prd", prd)


class PackageTest(unittest.TestCase):
    def test_package_check(self):
        run(os.path.join(ROOT, "scripts", "check_package.py"))


if __name__ == "__main__":
    unittest.main()
