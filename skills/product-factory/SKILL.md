---
name: product-factory
description: AI 产品工厂的总入口与阶段编排。在产品仓库中维护 factory/state.json，判断当前阶段（PRD→蓝图→技术适配→MVP→前端→QA→上线→运营迭代），调用对应阶段 Skill，运行闸门检查并停在用户审批点。用于“用工厂流程推进一个产品”“现在到哪一步了”“进入下一阶段”；不替代各阶段 Skill 本身的工作。
---

# AI 产品工厂编排

流程由状态机决定，AI 只在单个阶段内部工作。本 Skill 负责“现在该做哪一步、能不能往下走”，具体产出交给阶段 Skill。

## 阶段与 Skill

| 阶段 | Skill | 交接物（相对产品仓库） | 退出时需要 |
| --- | --- | --- | --- |
| prd | prd-author | factory/prd.md | 用户签字 prd_signoff |
| blueprint | agent-blueprint | factory/blueprint.md | 用户签字 blueprint_signoff |
| adaptation | agent-mvp-delivery | factory/adaptation.md、factory/stages/plan.md | 有偏离或待决问题时 adaptation_confirm |
| build | agent-mvp-delivery | factory/stages/handoff.md | real_passed 证据 + build_acceptance |
| frontend | agent-frontend-delivery | factory/frontend/adaptation.md、ui-acceptance.md | real_passed + frontend_acceptance（无界面产品可跳过并写理由） |
| qa | qa-eval | factory/eval/plan.md、cases.jsonl、report.md | real_passed，阻塞清零 |
| release | agent-release-readiness | factory/release/record.md | 部署前 release_go；结束时 production_verified + launch_acceptance |
| operate | 本 Skill | factory/feedback.md | 持续；用 iterate 开新版本 |

权威定义在 [stages.json](assets/stages.json)；闸门规则与权限档位见 [阶段与闸门](references/stages-and-gates.md)。

## 每次被调用时

1. 找到产品仓库。没有 `factory/state.json` 时，确认产品名后运行 `python3 <本Skill目录>/scripts/factory_gate.py init <仓库> --name <产品名>`；仓库不存在先 `git init`，不覆盖已有文件。
2. 运行 `factory_gate.py status <仓库>`，以输出为准，不凭记忆判断阶段。
3. 加载当前阶段的 Skill，按它的规则工作，权限不超过该阶段档位（P0–P3）。交接物写到约定路径；交接约定见 [交接与证据](references/handoff-conventions.md)。
4. 每完成一项真实验证，立即用 `evidence` 记录实际命令、结果和证据位置；没运行的不记 pass。遇到需要用户决定或外部条件缺失时用 `blocker --add` 记录。
5. 运行 `check`。未通过就处理缺口；同一阻塞修正两次仍不通过，停止并向用户说明原因与所需决定。
6. 闸门只差审批时，向用户发送审批摘要（见下），然后停下等待。不在同一轮里替用户批准。
7. 用户明确批准后，用 `approve --quote "<用户原话>"` 记录（用户也可以自己运行），再 `advance`。一次只推进一个阶段，除非用户要求连续推进且后续阶段无需审批。

## 审批摘要格式

用产品语言写，控制在一屏内：本阶段做成了什么；已验证（附证据等级）与未验证；新增的费用、外部平台、数据外传或范围变化；需要用户回答的问题（对应 stages.json 中的 ask）；用户批准后下一步做什么。

## 硬规则

- 读 Skill 或手册不等于获得授权。付费调用、云资源、公开访问、发送消息、破坏性数据操作都以 state.json 中的审批与授权范围为准；部署前必须 `require --id release_go` 通过。
- 不手工修改 state.json 绕过闸门；需要例外时由用户 `waive`，豁免会出现在报告里，不等于已验证。
- 低等级证据不能写成高等级：mock 通过不是 real_passed，URL 返回 200 不是 production_verified。
- 阶段 Skill 发现上游文档有错（如 PRD 矛盾），记录阻塞并回到对应阶段修订，不在下游悄悄改需求。
- 凭据只经 .env（不提交）或平台密钥管理注入，不在对话、日志、state.json 中出现。

## 控制台模式

由“产品工厂控制台”以非交互方式启动时，你无法和用户对话：按 [收件箱协议](references/inbox-protocol.md) 把问题、待办、验收清单、审批摘要写进 `factory/inbox/<阶段>.json` 后结束运行；不修改 state.json，不运行 factory_gate.py 的写入命令，证据与阻塞写进收件箱，由控制台记录。

## 运营与迭代

上线后进入 operate：把用户反馈、监控异常、效果数据整理进 `factory/feedback.md`（模板见 [运营与迭代](references/operate-and-iterate.md)）。决定做新版本时，用户确认范围后运行 `iterate`：当前 factory 归档到 `factory/history/vN/`，从 prd 阶段的变更模式重新开始。
