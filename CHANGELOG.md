# 更新记录

## 0.3.0（2026-10-04）

- 设置页支持多款 AI 命令行工具：自动检测 Claude Code 与 Codex 的安装和登录状态。
- Claude Code 可改用国内或第三方模型（DeepSeek、Kimi、智谱 GLM、MiniMax、自定义 Claude 兼容接口），填 API Key 即可。
- Codex 支持 ChatGPT 账号或 OpenAI API Key，在沙箱中运行，按阶段开关联网。
- API Key 存 macOS 钥匙串，不进项目文件、不回传网页；“保存并测试连接”实际调用一次模型。
- “手动模式”改为高级选项“其他 AI 工具”。
- 运行记录显示 token 用量；第三方模型不再按 Claude 价格估算费用。
- 控制台测试增至 9 项。

## 0.2.0（2026-10-03）

- 新增本地控制台（`console/`，双击 `启动控制台.command` 启动）：生产线视图、问题表单、本人操作待办、逐步验收清单、盖章审批卡、部署授权、质检单、文档查看、运行记录与费用。
- 三种 AI 执行方式：Claude Code 自动执行（按阶段限制权限、预算与时长）、手动复制指令、演示模式。
- 新增收件箱协议（`skills/product-factory/references/inbox-protocol.md`），让非交互运行的 AI 与界面交接。
- 防护：AI 运行后检查并恢复 state.json、撤销 AI 自行写入的审批、证据等级上限、未授权不接受线上证据。
- factory_gate.py 的审批与豁免记录来源（`--via`）。
- 测试：控制台 6 项单元/集成测试；浏览器端到端走完 8 个阶段与迭代。

## 0.1.0（2026-10-03）

- 合并 `agent-product-delivery-skills` 的 4 个 Skill 与课程第四周材料。
- 新增 Skill：product-factory（阶段编排与闸门）、prd-author（PRD 撰写与变更）、qa-eval（测试与效果评测）。
- 新增脚本：factory_gate.py（状态机）、eval_cases.py（用例与 AC 覆盖检查）、check_package.py（包结构检查）、install.sh。
- 新增火山引擎 veFaaS 平台适配器，修订数据持久化、权限与密钥处理方式。
- 端到端测试 6 项通过；尚未在真实产品上试跑。
