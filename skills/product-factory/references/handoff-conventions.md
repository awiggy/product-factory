# 交接与证据约定

## 产品仓库中的 factory/ 目录

```text
factory/
├── state.json            # 唯一机器可读状态，只经 factory_gate.py 修改
├── README.md             # 给人看的说明
├── prd.md                # prd-author
├── blueprint.md          # agent-blueprint
├── adaptation.md         # 技术适配声明（agent-mvp-delivery）
├── stages/
│   ├── plan.md           # 阶段技术开发计划
│   └── handoff.md        # 当前阶段交接记录（多阶段时追加章节，不另建平行文件）
├── frontend/
│   ├── adaptation.md     # 前端适配声明
│   └── ui-acceptance.md
├── eval/
│   ├── plan.md
│   ├── cases.jsonl       # 评测用例，每行一个 JSON
│   └── report.md
├── release/
│   └── record.md
├── feedback.md           # 运营阶段
└── history/vN/           # iterate 时的归档
```

代码、测试、README 仍放在仓库正常位置；factory/ 只放决策与证据，不复制代码。

## 写交接物的规则

- 每份文档开头写：阶段、产品版本、日期、上游依据（如“依据 prd.md v1 / AC-1..AC-8”）。
- 只写下一阶段必要的内容：决定、接口与状态的位置、限制、证据索引。不复制整段对话或手册。
- 事实、假设、待确认分开标注。假设要写“若不成立会影响什么”。
- 引用而不复制：接口定义、数据结构以代码或项目文档为准，交接物链接过去。
- 验收标准沿用 PRD 的 AC 编号，便于 qa-eval 追踪。

## 记录证据

```sh
python3 factory_gate.py evidence <仓库> --level real_passed \
  --what "AC-2 上传 PDF 到生成对照页的真实链路" \
  --how "curl -N /api/v1/papers ...；模型 deepseek-xxx" \
  --result pass --env "本地 + 真实模型" --where "factory/stages/handoff.md#验证证据"
```

- `how` 写实际执行的命令或操作，别人能照着复现。
- 结果只用 pass / fail / unverified / n/a；未运行写 unverified，不写 pass。
- 截图、日志放仓库内不含敏感信息的位置，或只写路径与摘要；不上传真实用户数据。
