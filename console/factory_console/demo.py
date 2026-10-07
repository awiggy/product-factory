"""演示执行器：不调用任何 AI，按阶段写入示例文档与收件箱，用来体验完整流程。"""

import json
import os
import time

from . import inbox as ib
from . import products as pr

STEP_DELAY = float(os.environ.get("FACTORY_DEMO_DELAY", "0.35"))


def _w(pdir, rel, text):
    p = os.path.join(pdir, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def _steps(run, items):
    for kind, text in items:
        if run.stop_requested:
            return False
        run.emit(kind, text)
        time.sleep(STEP_DELAY)
    return True


def _inbox(run, data):
    box, _ = pr.read_inbox(run.pdir, run.stage)
    data = dict(data)
    data["stage"] = run.stage
    data["round"] = (box["round"] + 1) if box else 1
    data.setdefault("questions", [])
    data.setdefault("user_actions", [])
    data.setdefault("checklist", [])
    data.setdefault("evidence", [])
    data.setdefault("blockers", [])
    ib.write_json(ib.path(run.pdir, run.stage), data)


def _answer(run, qid, default=""):
    answers = ib.read_json(ib.path(run.pdir, run.stage, ".answers"), {}) or {}
    for rk in sorted(answers, key=lambda x: int(x), reverse=True):
        if qid in answers[rk]:
            v = answers[rk][qid]
            return "、".join(v) if isinstance(v, list) else v
    return default


def _feedback_used(run):
    data = ib.read_json(ib.path(run.pdir, run.stage, ".feedback"), []) or []
    return [f for f in data if f.get("used_by") == run.id]


def _summary(done, verified, unverified, next_, new_costs=None, questions=None):
    return {"done": done, "verified": verified, "unverified": unverified,
            "new_costs": new_costs or [], "questions": questions or [], "next": next_}


# ------------------------------------------------------------------ 各阶段

def prd(run):
    box, _ = pr.read_inbox(run.pdir, run.stage)
    fb = _feedback_used(run)
    if box is None:
        if not _steps(run, [("tool", "读取 idea.md"), ("tool", "读取 prd-author/SKILL.md"),
                            ("tool", "读取 interview.md"),
                            ("text", "想法里已经说清了“读英文论文”，还缺目标用户、成功标准和数据边界。")]):
            return
        _inbox(run, {
            "status": "needs_input",
            "summary": "我读完了你的想法。先确认三件会影响范围和隐私的事，答完我就起草 PRD。",
            "questions": [
                {"id": "q1", "text": "主要给谁用？他们现在是怎么读英文论文的？", "why": "用户决定后面所有取舍。",
                 "type": "text", "example": "AI 方向的研究生；现在一段段复制到翻译软件，再手动查术语", "required": True},
                {"id": "q2", "text": "做成什么样算“成了”？", "why": "没有标准就没法验收。", "type": "choice",
                 "options": ["30 页论文 5 分钟内能开始读", "术语解释准确、能积累成词库", "两者都要"],
                 "required": True},
                {"id": "q3", "text": "论文文件可以发给云端大模型处理吗？", "why": "这决定能用哪些模型，以及隐私红线怎么写。",
                 "type": "choice", "options": ["可以", "只能发脱敏后的文字", "不能离开本机"], "required": True},
            ],
        })
        return
    if not _steps(run, [("info", "收到你的 %d 个回答" % len(pr.qa_history(run.pdir, run.stage))),
                        ("tool", "读取 assets/prd.md"), ("tool", "写入 factory/prd.md"),
                        ("tool", "读取 references/prd-quality.md"), ("text", "按质量检查清单自查：AC 都可以判定，红线具体。")]):
        return
    who = _answer(run, "q1", "需要读英文论文的研究生")
    goal = _answer(run, "q2", "两者都要")
    privacy = _answer(run, "q3", "可以")
    revised = ""
    if fb:
        revised = "\n> 已根据你的反馈修改：%s\n" % "；".join(f["text"] for f in fb)
    _w(run.pdir, "factory/prd.md", PRD_TEXT.format(who=who, goal=goal, privacy=privacy, revised=revised))
    _inbox(run, {
        "status": "ready_for_review",
        "summary": "PRD 初稿写好了：一条核心闭环、8 条验收标准，MVP 只做 Web 端。" + ("已按你的反馈修改。" if fb else ""),
        "approval_summary": _summary(
            "写好了 PRD：用户是%s；核心闭环是上传 PDF → 中英对照 → 术语卡片 → 个人词库。" % who,
            ["一句话定位、范围、红线、8 条验收标准（方案写好）"],
            ["成功指标里的“术语准确率”目标值是建议值，还没有真实数据"],
            "签字后进入架构阶段，AI 会判断要不要做成 Agent。",
            questions=["MVP 先只做 Web 端，可以吗？"]),
    })


def blueprint(run):
    if not _steps(run, [("tool", "读取 factory/prd.md"), ("tool", "读取 agent-blueprint/SKILL.md"),
                        ("tool", "读取 component-decisions.md"),
                        ("text", "步骤基本固定：解析 → 翻译 → 术语抽取。用固定流程 + 局部模型调用，不需要动态 Agent。"),
                        ("tool", "写入 factory/blueprint.md")]):
        return
    _w(run.pdir, "factory/blueprint.md", BLUEPRINT_TEXT)
    _inbox(run, {
        "status": "ready_for_review",
        "summary": "结论是不需要动态 Agent：固定流程 + 两处模型调用就够了，成本和出错面都更小。",
        "approval_summary": _summary(
            "架构方案：固定流程编排，模型只负责翻译和术语抽取；只选了 5 个组件。",
            ["五要素、组件取舍、工具权限与预算上限（方案写好）"],
            ["每篇论文的模型费用是估算值（约 0.05–0.2 元），要到 MVP 阶段用真实论文测"],
            "签字后进入技术选型。",
            new_costs=["需要一个 DeepSeek API 账号（按调用量付费）"]),
    })


def adaptation(run):
    if not _steps(run, [("tool", "读取 factory/blueprint.md"), ("tool", "读取 default-stack.md"),
                        ("text", "全新项目，没有特殊约束：直接用默认技术栈，后端先行。"),
                        ("tool", "写入 factory/adaptation.md"), ("tool", "写入 factory/stages/plan.md")]):
        return
    _w(run.pdir, "factory/adaptation.md", ADAPT_TEXT)
    _w(run.pdir, "factory/stages/plan.md", PLAN_TEXT)
    _inbox(run, {
        "status": "ready_for_review", "approval_required": False,
        "summary": "全部采用默认方案，没有新增费用或平台，不需要你确认，可以直接进入开发。",
        "approval_summary": _summary("技术适配声明与 3 个开发阶段的计划。", ["方案写好"], [], "进入 MVP 开发。"),
    })


def build(run):
    box, _ = pr.read_inbox(run.pdir, run.stage)
    if box is None:
        if not _steps(run, [("tool", "读取 factory/stages/plan.md"), ("tool", "写入 backend/app/main.py"),
                            ("tool", "写入 backend/app/services/translate.py"), ("tool", "写入 backend/tests/test_parse.py"),
                            ("tool", "运行命令：pytest -q"), ("text", "12 个测试通过（全部使用假数据）。"),
                            ("text", "真实模型测试需要 DeepSeek Key，先请你填进 .env。")]):
            return
        _w(run.pdir, ".env.example", "DEEPSEEK_API_KEY=\nMODEL_ID=deepseek-chat\n")
        _inbox(run, {
            "status": "needs_input",
            "summary": "核心代码写好了，假数据测试全部通过。接下来要用真实模型跑一遍，需要你填一下 Key。",
            "user_actions": [{"id": "a1", "title": "填写 DeepSeek 模型 Key",
                              "steps": ["在 platform.deepseek.com 创建一个 API Key，粘贴到下面"],
                              "file": ".env",
                              "fields": [
                                  {"key": "DEEPSEEK_API_KEY", "label": "DeepSeek API Key", "secret": True,
                                   "help": "在 platform.deepseek.com → API Keys 创建"},
                                  {"key": "MODEL_ID", "label": "模型", "default": "deepseek-v4-flash",
                                   "options": ["deepseek-v4-flash", "deepseek-v4-pro"]}]}],
            "evidence": [{"level": "mock_passed", "what": "后端 12 个单元测试通过（假数据）", "how": "pytest -q",
                          "result": "pass", "where": "backend/tests", "env": "本地"}],
            "blockers": [],
        })
        return
    fixing = run.mode == "fix"
    if not _steps(run, [("info", "你已完成：填写 DeepSeek 模型 Key" if not fixing else "读取上一轮验收结果"),
                        ("tool", "运行命令：curl -N localhost:8000/api/v1/papers -F file=@samples/attention.pdf"),
                        ("text", "真实模型返回正常，首段 4.2 秒出现，整篇 38 秒。"),
                        ("tool", "写入 factory/stages/handoff.md")]):
        return
    _w(run.pdir, "factory/stages/handoff.md", HANDOFF_TEXT)
    _inbox(run, {
        "status": "ready_for_review",
        "summary": ("已修复你指出的问题。" if fixing else "") + "真实模型跑通了。请照着清单亲手试一遍。",
        "evidence": [{"level": "real_passed", "what": "上传 10 页论文 → 中英对照 → 术语卡片，真实模型全链路",
                      "how": "curl -N /api/v1/papers；deepseek-chat", "result": "pass",
                      "where": "factory/stages/handoff.md#验证证据", "env": "本地 + 真实模型"}],
        "checklist": [
            {"id": "c1", "do": "在终端进入产品文件夹，运行 ./start.sh", "expect": "最后一行显示 http://localhost:8000"},
            {"id": "c2", "do": "浏览器打开 http://localhost:8000，上传 samples/attention.pdf", "expect": "1 分钟内出现中英左右对照"},
            {"id": "c3", "do": "点任意一个高亮术语", "expect": "弹出术语卡片：中文释义、英文原义、例句"},
            {"id": "c4", "do": "刷新页面", "expect": "刚才的论文还在，不会重新生成"},
        ],
        "approval_summary": _summary(
            "MVP 核心闭环：上传 PDF → 中英对照 → 术语卡片 → 刷新后可恢复。",
            ["假数据测试 12 项通过", "真实模型全链路 1 次通过（单篇约 0.12 元）"],
            ["扫描版 PDF 暂不支持（PRD 中已列为后续版本）"],
            "签字后进入正式前端。"),
    })


def frontend(run):
    if not _steps(run, [("tool", "读取 default-frontend-stack.md"), ("tool", "写入 frontend/app/page.tsx"),
                        ("tool", "运行命令：npm run lint && npm run typecheck && npm run build"),
                        ("text", "代表页做好了，按 390 / 1280 像素检查过布局。"),
                        ("tool", "写入 factory/frontend/ui-acceptance.md")]):
        return
    _w(run.pdir, "factory/frontend/adaptation.md", FE_ADAPT_TEXT)
    _w(run.pdir, "factory/frontend/ui-acceptance.md", FE_ACCEPT_TEXT)
    _inbox(run, {
        "status": "ready_for_review",
        "summary": "正式前端做好了：阅读页、术语卡片、我的词库三个页面。请在电脑和手机上各试一次。",
        "evidence": [{"level": "real_passed", "what": "浏览器中走通上传到阅读的闭环（真实后端）",
                      "how": "Playwright e2e + 手动检查 390/1280 像素", "result": "pass",
                      "where": "factory/frontend/ui-acceptance.md", "env": "本地"}],
        "checklist": [
            {"id": "c1", "do": "电脑浏览器打开 http://localhost:3000，上传一篇论文", "expect": "看到生成进度，完成后左右对照"},
            {"id": "c2", "do": "生成过程中刷新页面", "expect": "进度继续，不会重新开始"},
            {"id": "c3", "do": "用手机打开同一个地址（同一 Wi-Fi）", "expect": "排版正常，术语卡片能打开"},
        ],
        "approval_summary": _summary("三个页面与完整状态（加载、失败、断线恢复）。",
                                     ["lint / 类型检查 / 构建通过", "浏览器真实闭环通过"],
                                     ["iPhone Safari 未实测，需要你用手机验证"], "签字后进入评测。"),
    })


def qa(run):
    if not _steps(run, [("tool", "读取 factory/prd.md"), ("tool", "写入 factory/eval/plan.md"),
                        ("tool", "写入 factory/eval/cases.jsonl"),
                        ("tool", "运行命令：python3 eval_cases.py ."), ("text", "8 条验收标准都有用例覆盖。"),
                        ("tool", "运行命令：pytest tests/eval -q"), ("tool", "写入 factory/eval/report.md")]):
        return
    _w(run.pdir, "factory/eval/plan.md", QA_PLAN_TEXT)
    _w(run.pdir, "factory/eval/cases.jsonl", QA_CASES)
    _w(run.pdir, "factory/eval/report.md", QA_REPORT_TEXT)
    _inbox(run, {
        "status": "ready_for_review",
        "summary": "评测完成：16 个用例 15 个通过，1 个次要问题（长表格翻译后对齐错位），不阻塞上线。",
        "evidence": [{"level": "real_passed", "what": "16 个评测用例（含越权、重复提交、断线恢复）",
                      "how": "pytest tests/eval；人工抽检 50 条术语", "result": "pass",
                      "where": "factory/eval/report.md", "env": "本地 + 真实模型"}],
        "approval_summary": _summary("评测报告。", ["功能 8/8、安全 3/3、可靠性 4/4", "术语抽检 50 条错误 2 条"],
                                     ["长表格对齐问题留到下一版"], "进入上线。"),
    })


def release(run):
    if run.mode != "deploy":
        if not _steps(run, [("tool", "读取 release-gates.md"), ("tool", "读取 platform-volcengine-vefaas.md"),
                            ("text", "数据要放托管数据库，文件放对象存储；需要你完成账号相关的本人操作。"),
                            ("tool", "写入 factory/release/record.md")]):
            return
        _w(run.pdir, "factory/release/record.md", RELEASE_DRAFT)
        _inbox(run, {
            "status": "needs_input",
            "summary": "上线检查完成，代码层面没有阻塞。需要你完成两件本人操作，并授权部署。",
            "user_actions": [
                {"id": "a1", "title": "准备火山引擎账号与子账号", "steps": ["登录 console.volcengine.com 并完成实名",
                 "按 record.md 里的清单为子账号开通函数服务、API 网关、对象存储、数据库的最小权限"],
                 "done_when": "权限开好后勾选"},
                {"id": "a2", "title": "在你自己的终端登录部署工具", "steps": ["终端运行 vefaas login，按提示输入密钥",
                 "不要把密钥发到任何对话里"], "done_when": "看到登录成功后勾选"}],
            "release_request": {"platform": "火山引擎 veFaaS + API 网关", "environment": "生产（邀请码访问）",
                                "cost": "预计每月 50–120 元（数据库约 60 元 + 按量）", "visibility": "公网，凭邀请码登录",
                                "data_migration": "首次上线，无历史数据", "rollback": "保留上一版本，可一键切回"},
        })
        return
    if not _steps(run, [("info", "已确认授权范围"), ("tool", "运行命令：vefaas inspect"),
                        ("tool", "运行命令：vefaas env list"), ("tool", "运行命令：vefaas deploy --newApp paper-reader …"),
                        ("text", "部署完成，核对线上版本为 a3f9c21。"),
                        ("tool", "运行命令：curl https://…/api/v1/health"), ("tool", "写入 factory/release/record.md")]):
        return
    _w(run.pdir, "factory/release/record.md", RELEASE_FINAL)
    _inbox(run, {
        "status": "ready_for_review",
        "summary": "已部署。版本、登录隔离、重启后数据保留都实测过。请按清单在线上走一遍。",
        "evidence": [
            {"level": "production_verified", "what": "线上版本 a3f9c21 与本次提交一致", "how": "GET /api/v1/version", "result": "pass", "env": "生产"},
            {"level": "production_verified", "what": "测试账号 A 无法读取账号 B 的论文", "how": "换 ID 直接请求，返回 403", "result": "pass", "env": "生产"},
            {"level": "production_verified", "what": "重新部署后测试数据仍在", "how": "写入 → 重新部署 → 读取", "result": "pass", "env": "生产"}],
        "checklist": [
            {"id": "c1", "do": "用邀请码 DEMO-01 打开线上地址并登录", "expect": "进入首页"},
            {"id": "c2", "do": "上传一篇论文", "expect": "1 分钟内出现对照"},
            {"id": "c3", "do": "换邀请码 DEMO-02 登录", "expect": "看不到上一个账号的论文"},
        ],
        "approval_summary": _summary("v1 已上线（邀请码访问）。", ["版本核对、权限隔离、数据持久化（线上验证）"],
                                     ["备份恢复只做了方案，尚未演练"], "签字后进入运营阶段。",
                                     new_costs=["已开通托管数据库（约 60 元/月）"]),
    })


def operate(run):
    if not _steps(run, [("tool", "读取 operate-and-iterate.md"), ("text", "整理了 12 位用户两周的反馈与运行数据。"),
                        ("tool", "写入 factory/feedback.md")]):
        return
    _w(run.pdir, "factory/feedback.md", FEEDBACK_TEXT)
    _inbox(run, {"status": "ready_for_review", "summary": "反馈整理好了。最多人提的是批量上传和导出笔记。",
                 "approval_summary": _summary("v1 运营反馈。", [], [], "确定下一版范围后开始 v2。")})


def run(r):
    fn = globals().get(r.stage)
    if not fn:
        r.emit("warn", "演示模式不支持这个阶段")
        return
    fn(r)


# ------------------------------------------------------------------ 演示文档内容

PRD_TEXT = """# 论文阅读助手 PRD

> 版本：v1 ｜ 状态：待签字 ｜ 演示内容
{revised}
## 1. 一句话定位
给{who}，把英文论文变成“中英对照 + 术语卡片”的阅读材料，省掉逐段复制翻译、逐词查术语的时间。

## 2. 用户与场景
- 目标用户：{who}
- 场景：每周读 2–5 篇英文论文，需要快速读懂并积累术语。
- 交互方式：上传后异步等待结果，再阅读。

## 3. 目标与成功指标
| 指标 | 目标值 | 测量方法 | 状态 |
| --- | --- | --- | --- |
| 30 页论文从上传到可读 | ≤ 5 分钟 | 计时 10 篇样本 | 待测 |
| 术语解释明显错误率 | ≤ 5% | 人工抽检 100 条 | 建议值，待确认 |

用户最看重：{goal}

## 4. 核心闭环
用户上传 PDF → 生成中英对照 → 术语高亮并给出解释 → 用户收藏术语 → 进入个人词库，跨论文积累。

## 5. 范围
- MVP 必须有：上传文本型 PDF、中英对照阅读、术语卡片、个人词库。
- 后续版本：扫描件识别、批量上传、导出笔记。
- 明确不做：论文推荐、社区分享。

## 9. 红线
- 数据与隐私：论文处理方式——{privacy}；不向第三方以外的服务上传。
- 不删除用户的词库。
- 不编造术语解释：没有把握时标注“待核实”。

## 13. 验收标准
| 编号 | 场景 | 给定条件 | 操作 | 预期结果 | 判定方式 |
| --- | --- | --- | --- | --- | --- |
| AC-1 | 上传文本 PDF | 10 页论文 | 上传 | 60 秒内出现中英对照 | 自动 + 人工 |
| AC-2 | 刷新恢复 | 生成中 | 刷新页面 | 进度继续，不重复生成 | 自动 |
| AC-3 | 扫描件 | 无文字层 PDF | 上传 | 提示暂不支持，可粘贴文本 | 自动 |
| AC-4 | 术语卡片 | 已生成 | 点术语 | 显示释义、原义、例句 | 人工 |
| AC-5 | 术语质量 | 20 篇论文 | 抽检 100 条 | 明显错误 ≤ 5 条 | 人工评测 |
| AC-6 | 词库 | 收藏 3 个术语 | 打开词库 | 3 个术语都在，可跨论文查看 | 自动 |
| AC-7 | 模型失败 | 模型超时 | 生成 | 有限重试后提示，可重试，不丢输入 | 自动 |
| AC-8 | 数据隔离 | 两个账号 | B 请求 A 的论文 | 返回无权限 | 自动 |
"""

BLUEPRINT_TEXT = """# Agent 架构蓝图：论文阅读助手

> 演示内容 ｜ 依据：factory/prd.md（AC-1..AC-8）

## 是否需要 Agent
不需要动态 Agent。解析 → 分段翻译 → 术语抽取 → 保存，步骤固定，用代码状态机编排；模型只在“翻译”和“术语抽取”两步被调用。

## 五要素
| 工具 | 知识 | 观察证据 | 行动接口 | 权限 |
| --- | --- | --- | --- | --- |
| PDF 解析、翻译、术语抽取、词库读写 | AI 领域术语表、翻译风格规则 | 每段翻译结果的结构校验、耗时与费用 | 后端 API | 用户只能访问自己的论文与词库 |

## 组件与架构
| 组件 | 选/不选 | 需求依据 | 没有它会怎样 | 更简单的替代 |
| --- | --- | --- | --- | --- |
| 工具系统 | 选 | AC-1、AC-4 | 无法调用解析与模型 | — |
| 权限系统 | 选 | AC-8 | 数据串号 | — |
| 任务系统（持久化） | 选 | AC-2 | 刷新后重新生成、重复收费 | — |
| 工作流运行时 | 选 | 步骤固定 | 需要模型自己规划，成本高 | — |
| 技能加载 | 选 | 术语表较大 | 每次塞满上下文 | — |
| 记忆、Agent 团队、MCP、定时调度 | 不选 | 无对应需求 | 无影响 | — |

## 预算与停止条件
单篇论文模型调用 ≤ 40 次、≤ 0.3 元；单段超时 30 秒，最多重试 2 次。
"""

ADAPT_TEXT = """# 技术适配声明

> 演示内容

## 1. 产品形态判断
- 核心交互：一次生成 + 阅读；开发路径：后端先行。
- 首个终端：Web。新项目。

## 2. 采用的默认方案
- Python + FastAPI + Pydantic + pytest：默认方案，无约束。
- Next.js 前端：在前端阶段引入。

## 3. 触发的按需模块
- SQLite + SQLAlchemy：论文、术语、用户三类实体（AC-6、AC-8）。
- SSE：逐段展示翻译结果（AC-1）。

## 4. 偏离或暂缓的默认方案
- 无。

## 5. 强制底线检查
- 密钥与隐私：通过（只在后端 .env）。
- 数据与任务可恢复：通过（任务状态持久化）。

## 6. 需要用户决定的问题
无。
"""

PLAN_TEXT = """# 阶段开发计划

> 演示内容

| 阶段 | 业务闭环 | 覆盖的 AC | 是否需要验收界面 |
| --- | --- | --- | --- |
| 1 | 上传 → 对照 → 刷新恢复 | AC-1、AC-2、AC-3、AC-7 | 需要（静态验收页） |
| 2 | 术语卡片与词库 | AC-4、AC-5、AC-6 | 需要 |
| 3 | 登录与数据隔离 | AC-8 | 不需要 |
"""

HANDOFF_TEXT = """# 阶段交付记录

> 演示内容

## 验证证据
| 检查 | 层级 | 命令/操作 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| 单元测试 12 项 | mock | pytest -q | 通过 | backend/tests |
| 上传 → 对照 → 术语 | 真实冒烟 | curl -N /api/v1/papers | 通过 | 首段 4.2 秒，整篇 38 秒，约 0.12 元 |

## 用户待验收（照着做）
见控制台中的验收清单。

## 下一阶段输入
接口：/api/v1/papers、/api/v1/terms；配置名：DEEPSEEK_API_KEY、MODEL_ID。
"""

FE_ADAPT_TEXT = """# 前端适配声明

> 演示内容

- 主要终端：桌面 Web + 移动 Web。新项目，采用默认前端栈（Next.js + TypeScript + Tailwind）。
- Agent 状态：submitting、queued、running、streaming、succeeded、failed、disconnected。
- 待确认事项：无。
"""

FE_ACCEPT_TEXT = """# 前端交互交付记录

> 演示内容

## 自动检查
| 命令 | 结果 |
| --- | --- |
| npm run lint | 通过 |
| npm run typecheck | 通过 |
| npm run build | 通过 |

## 待验收与限制
iPhone Safari 需要真机验证。
"""

QA_PLAN_TEXT = """# 评测计划

> 演示内容

| AC | 类型 | 验证层 | 判定方式 | 通过阈值 |
| --- | --- | --- | --- | --- |
| AC-1 | functional | real | rule | 60 秒内出现对照 |
| AC-5 | agent_quality | manual | rubric | 明显错误 ≤ 5% |
| AC-8 | safety | real | rule | 返回无权限 |
"""

QA_CASES = "\n".join(json.dumps(c, ensure_ascii=False) for c in [
    {"id": "TC-001", "ac": ["AC-1"], "type": "functional", "layer": "real", "input": "10 页论文", "expected": "60 秒内出现对照", "judge": "rule", "result": "pass", "evidence": "report.md"},
    {"id": "TC-002", "ac": ["AC-2"], "type": "reliability", "layer": "real", "input": "生成中刷新", "expected": "不重复生成", "judge": "rule", "result": "pass", "evidence": "report.md"},
    {"id": "TC-008", "ac": ["AC-8"], "type": "safety", "layer": "real", "input": "B 请求 A 的论文", "expected": "403", "judge": "rule", "result": "pass", "evidence": "report.md"},
]) + "\n"

QA_REPORT_TEXT = """# 评测报告

> 演示内容

## 结论
可以进入发布。

## 效果指标
| 指标 | 阈值 | 实际 | 样本 |
| --- | --- | --- | --- |
| 术语明显错误率 | ≤ 5% | 4%（2/50） | 50 条人工抽检 |

## 失败与缺陷
| 用例 | 严重度 | 现象 |
| --- | --- | --- |
| TC-011 | minor | 长表格翻译后列对齐错位 |
"""

RELEASE_DRAFT = """# 发布检查与交付记录

> 演示内容 ｜ 状态：待授权

## 发布门槛
| 项目 | 结果 |
| --- | --- |
| 访问控制 | 通过（邀请码 + 按用户隔离，本地测试） |
| 数据与文件 | 方案：托管数据库 + 对象存储私有桶 |
| 发布恢复 | 方案已准备，未演练 |
"""

RELEASE_FINAL = """# 发布检查与交付记录

> 演示内容 ｜ 状态：已上线

## 实际执行与结果
- 线上版本：a3f9c21（与提交一致）
- 权限隔离：线上实测通过
- 重新部署后数据保留：线上实测通过
- 备份恢复：方案已准备，未演练

## 回滚
保留上一版本，出现关键接口持续失败时切回。
"""

FEEDBACK_TEXT = """# 运营反馈｜v1

> 演示内容

## 指标对照
| PRD 指标 | 目标 | 实际 | 结论 |
| --- | --- | --- | --- |
| 30 页论文到可读 | ≤ 5 分钟 | 中位数 3 分 10 秒 | 达标 |

## 下一版候选
- 必须修：长表格对齐。
- 值得做：批量上传、导出笔记。
"""
