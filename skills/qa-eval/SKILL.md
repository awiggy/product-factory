---
name: qa-eval
description: 把 PRD 验收标准（AC）转成可追踪的测试与 Agent 效果评测：功能、效果质量、安全越权、可靠性与性能用例，区分 mock、真实与人工判定，产出评测计划、用例集（cases.jsonl）与报告，并检查每条 AC 是否被覆盖。用于上线前 QA、回归评测或模型/Prompt 变更后的效果对比；不替代开发阶段的单元测试，也不自行降低验收标准。
---

# QA 与效果评测

回答两个问题：PRD 承诺的每一条是否真的做到了；Agent 的输出质量是否达到用户认可的标准。

> 单独使用（不走工厂流程）时：跳过 `factory/` 路径与 `factory_gate.py`，把同样的内容写进项目已有的文档位置；需要用户确认或授权的地方，仍要在对话中明确取得。

## 输入

`factory/prd.md`（AC 与成功指标）、`factory/blueprint.md`（工具、权限、预算）、`factory/stages/handoff.md` 与 `factory/frontend/ui-acceptance.md`（已有证据）。已有证据可以引用，不重复执行同一检查，但要核对它是否仍对应当前版本。

## 步骤

1. 读 [评测设计](references/eval-design.md)，按 [评测计划模板](assets/eval-plan.md) 写 `factory/eval/plan.md`：每条 AC 对应哪类用例、哪一层验证（mock / 真实 / 人工）、判定方式、样本量与通过阈值。阈值来自 PRD；PRD 没有的，提出建议值并标“待用户确认”，不自己定死。
2. 写 `factory/eval/cases.jsonl`，每行一个用例，字段见 [用例格式](assets/eval-case.schema.json)。必须覆盖：成功路径、非法输入、越权访问（至少两个身份）、供应商超时/失败、重复提交、中断恢复、预算/步数耗尽、内容安全红线（如适用）。
3. 运行 `python3 <本Skill目录>/scripts/eval_cases.py <产品仓库>` 检查格式与 AC 覆盖；有未覆盖的 AC 先补用例。
4. 执行：先跑自动化（mock 与真实），再请用户做人工判定部分。真实调用在阶段预算内进行，记录模型、Prompt 版本、样本与费用。使用模型做自动评分时，必须用人工抽检校准，并在报告里写明一致率。
5. 把结果写回用例的 `result` 与 `evidence`，失败用例标 `severity`（blocker / major / minor）。再运行脚本得到汇总。
6. 用 [报告模板](assets/eval-report.md) 写 `factory/eval/report.md`：AC 覆盖、通过率、效果指标、失败清单与归因、未验证项、建议。blocker 级失败用 `factory_gate.py blocker --add` 记录，修复后回归验证再清除。
7. 每类有效验证用 `factory_gate.py evidence` 记录。QA 通过的条件是：每条 AC 有结果、无 blocker、效果指标达到用户确认的阈值或由用户书面接受偏差。

## 边界

- 不删除或放宽用例来让结果好看；测试本身有错时，修正用例并在报告中说明原因。
- 不在真实环境向真实用户发送消息、付款或写入真实数据；测试数据明确标记并按方案清理。
- 修复缺陷属于开发工作：在当前授权允许时可做小修并回归；涉及架构或需求的问题，记录阻塞并回到对应阶段。
- 评测用例中不放真实用户的个人数据或密钥。
