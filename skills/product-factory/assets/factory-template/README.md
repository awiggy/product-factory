# factory/：这个产品的工厂记录

这里保存本产品从 PRD 到上线的决策与证据。代码在仓库的正常位置，这里不放代码。

- `state.json`：当前阶段、证据、审批，只通过 `factory_gate.py` 修改。
- 查看进度：`python3 <product-factory Skill 目录>/scripts/factory_gate.py status .`
- 阶段文档：prd.md → blueprint.md → adaptation.md / stages/ → frontend/ → eval/ → release/ → feedback.md
- 历史版本：history/vN/

审批（签字）由产品负责人做：可以自己运行 `approve`，也可以在对话里明确说“批准”，由 AI 带上原话代录。
