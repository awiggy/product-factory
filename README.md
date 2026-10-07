# AI 产品工厂 Skills

把一个 AI 产品从想法推进到上线、再到迭代：每个阶段有专门的 Skill 负责做事，有统一的状态机负责“能不能往下走”。

```text
想法 → ① PRD → ② 架构蓝图 → ③ 技术适配 → ④ MVP 核心闭环 → ⑤ 正式前端 → ⑥ QA 与效果评测 → ⑦ 上线 → ⑧ 运营迭代 ─┐
          ▲                                                                                            │
          └──────────────────────────── 新版本（变更模式）◀──────────────────────────────────────────────┘
```

包含三部分：

- **控制台**：在你电脑上运行的网页界面。回答问题、勾选待办、照清单验收、盖章审批都是点按钮完成，AI 在后台工作。**推荐从这里开始。**
- **7 个 Skill**：给 AI 编程助手（Claude Code、Codex 等支持 `SKILL.md` 的助手）的阶段工作规范，控制台和对话两种方式都用它们。
- **状态机脚本**：不依赖第三方库，负责闸门检查与审批记录。

它不是自动建站平台，也不会自己去开云资源：付费、部署、公开访问都要你在审批点明确授权。

## 开始使用控制台

双击 `启动控制台.command`（或运行 `python3 console/server.py`），浏览器会打开控制台。先点“先看看演示产品”走一遍完整流程（不调用 AI），再到“设置”里选择 AI 执行方式：Claude Code 或 Codex，可以用各自的账号，也可以填 DeepSeek、Kimi 等国内模型的 API Key。详见 [控制台说明](console/README.md)。

## 7 个 Skill

| 阶段 | Skill | 做什么 | 交接物 |
| --- | --- | --- | --- |
| 总入口 | [product-factory](skills/product-factory/SKILL.md) | 看当前阶段、调用对应 Skill、跑闸门、停在审批点、上线后开新版本 | factory/state.json |
| ① | [prd-author](skills/prd-author/SKILL.md) | 三轮访谈把想法问清楚，写带编号验收标准（AC）的 PRD | factory/prd.md |
| ② | [agent-blueprint](skills/agent-blueprint/SKILL.md) | 判断要不要 Agent，五要素建模，最小组件选型，工具权限与预算 | factory/blueprint.md |
| ③④ | [agent-mvp-delivery](skills/agent-mvp-delivery/SKILL.md) | 技术适配声明（默认 FastAPI 技术栈）→ 分阶段实现 → mock + 真实模型双层验收 | factory/adaptation.md、stages/ |
| ⑤ | [agent-frontend-delivery](skills/agent-frontend-delivery/SKILL.md) | 任务型前端（默认 Next.js）：统一任务状态、流式、确认、断线恢复、浏览器验收 | factory/frontend/ |
| ⑥ | [qa-eval](skills/qa-eval/SKILL.md) | AC → 功能/效果/安全/可靠性用例，覆盖检查与评测报告 | factory/eval/ |
| ⑦ | [agent-release-readiness](skills/agent-release-readiness/SKILL.md) | 发布门槛、数据恢复与回滚、授权后部署（含火山引擎 veFaaS 适配器） | factory/release/record.md |

每个 Skill 也可以单独使用，例如只用 prd-author 写 PRD，或只用 agent-release-readiness 做上线检查。

## 闸门：什么时候能进入下一阶段

`factory_gate.py check` 检查四件事，全部满足才能 `advance`：

1. **交接物**写完了（文件存在，且已删除模板标记 `<!-- factory:template -->`）。
2. **没有阻塞项**，失败的验证已处理。
3. **证据等级够了**：`planned` → `scaffold_runs` → `mock_passed` → `real_passed` → `production_verified`。例如 MVP 必须有真实模型冒烟（real_passed），上线必须在目标环境实际验证（production_verified）。条件不具备时只能由你豁免，报告里会显示“豁免”。
4. **你签了字**：PRD、蓝图、MVP 验收、前端验收、部署授权（release_go）、上线验收。签字会记录你的原话。

## 不用控制台，直接在对话里用

需要 Python 3.9+（只用标准库）。

```sh
# 1. 检查包是否完整
python3 scripts/check_package.py
python3 -m unittest discover -s tests
(cd console && python3 -m unittest discover -s tests)

# 2. 安装 Skill（默认装到 ~/.claude/skills；已有同名 Skill 会先备份）
./scripts/install.sh
#   装到某个项目：./scripts/install.sh /path/to/project/.claude/skills

# 3. 在产品仓库里对助手说：
#    “使用 product-factory，为‘论文阅读助手’建立工厂流程，从 PRD 开始。”
```

状态机也可以手动用：

```sh
GATE=~/.claude/skills/product-factory/scripts/factory_gate.py
python3 $GATE init ./my-product --name "论文阅读助手"
python3 $GATE status ./my-product
python3 $GATE approve ./my-product --id prd_signoff --by "我" --quote "PRD 确认"
python3 $GATE check ./my-product && python3 $GATE advance ./my-product
```

更多对话示例见 [使用说明](docs/usage.md)。

## 目录

```text
启动控制台.command  双击启动控制台（macOS）
console/           控制台（Python 标准库后端 + 原生 JS 前端，无需安装依赖）
skills/            7 个 Skill，每个目录可独立安装
scripts/           check_package.py（包结构检查）、install.sh（安装）
tests/             状态机与评测脚本的端到端测试
docs/              使用说明、设计说明、来源对照、后续路线
```

## 来源与状态

由两份材料合并而来：`agent-product-delivery-skills`（4 个 Skill 的规则与边界）和课程第四周材料（BLUEPRINT 方法论、三本技术手册）。取舍和修订见 [来源对照](docs/sources.md)，设计理由见 [设计说明](docs/design.md)。

**当前状态**：结构检查、脚本测试、控制台测试（含浏览器端到端走完 8 个阶段）已通过；控制台的 Claude Code 执行方式用模拟程序验证过参数与防护，尚未在真实产品上完整跑通一轮。建议先用一个小产品试跑，按 [后续路线](docs/roadmap.md) 根据实际卡点修订。
