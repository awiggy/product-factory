# 收件箱协议（控制台模式）

在工厂控制台中，AI 以非交互方式运行，不能和用户对话。所有需要用户看到或回答的内容，都写进 `factory/inbox/<阶段id>.json`，然后结束本次运行。控制台会把它变成界面：问题表单、待办操作、验收清单、审批卡。

## 规则

- 每次运行结束前都要写（或覆盖）这个文件，即使只是说明“已完成，等待审批”。
- `round` 每次运行加 1（读取旧文件的 round 后加 1；没有旧文件从 1 开始）。
- 文案用产品语言，写给不懂技术的产品负责人看；术语首次出现时简单解释。
- 不修改 `factory/state.json`，不运行 `factory_gate.py` 的 approve / waive / advance / iterate / blocker / evidence。证据写在本文件的 `evidence` 字段，阻塞写在 `blockers` 字段，由控制台记录。
- 不在本文件或任何文件中写入密钥值。
- 用户上一轮的回答、勾选结果、反馈会出现在本次运行的提示中；已经回答的问题不要再问。

## 格式

```json
{
  "stage": "build",
  "round": 2,
  "status": "needs_input",
  "summary": "用两三句话说明本次做了什么、现在卡在哪。",
  "questions": [
    {
      "id": "q1",
      "text": "主要给谁用？",
      "why": "用户决定后面所有取舍。",
      "type": "text",
      "options": [],
      "example": "需要读英文论文的研究生",
      "required": true
    }
  ],
  "user_actions": [
    {
      "id": "a1",
      "title": "填写模型 Key 和型号",
      "steps": ["在 platform.deepseek.com 创建 API Key，粘贴到下面"],
      "file": ".env",
      "fields": [
        {"key": "LLM_API_KEY", "label": "DeepSeek API Key", "secret": true, "help": "platform.deepseek.com → API Keys"},
        {"key": "LLM_MODEL", "label": "模型", "default": "deepseek-v4-flash", "options": ["deepseek-v4-flash", "deepseek-v4-pro"]},
        {"key": "LLM_PRICE_INPUT_PER_M", "label": "输入单价（美元/百万 token）", "required": false}
      ]
    },
    {
      "id": "a2",
      "title": "注册火山引擎账号",
      "steps": ["打开 console.volcengine.com 注册并完成实名认证"],
      "done_when": "能登录控制台后回来勾选"
    }
  ],
  "checklist": [
    {"id": "c1", "do": "在终端运行 ./start.sh，然后打开 http://localhost:8000", "expect": "看到上传页面"}
  ],
  "evidence": [
    {"level": "mock_passed", "what": "后端单元测试全部通过", "how": "pytest -q", "result": "pass", "where": "factory/stages/handoff.md#验证证据", "env": "本地"}
  ],
  "blockers": ["缺少模型 Key，真实模型测试无法进行"],
  "approval_required": null,
  "approval_summary": {
    "done": "本阶段做成了什么",
    "verified": ["已验证的内容（附证据等级）"],
    "unverified": ["未验证的内容与原因"],
    "new_costs": ["新增费用、外部平台、数据外传；没有就留空数组"],
    "questions": ["需要用户在批准时回答的问题"],
    "next": "批准后下一步做什么"
  },
  "release_request": null
}
```

### 字段说明

| 字段 | 何时填写 |
| --- | --- |
| `status` | `needs_input`：等待用户回答问题或完成操作；`ready_for_review`：本阶段产出已完成，等待验收或审批；`blocked`：遇到无法自行解决的问题；`working`：本次只完成了一部分，可以继续运行 |
| `questions` | 只问会影响范围、架构、费用或隐私的问题，每轮最多 3 个。`type` 为 `text`、`choice`（单选）或 `multi`（多选），选择题要给 `options` |
| `user_actions` | 必须由用户本人完成的操作：注册账号、填写 Key、在控制台点选。写成“照着做”的步骤。**要用户填写配置（Key、型号、地址、单价等）时必须用 `fields`**，见下文 |
| `checklist` | 需要用户亲手验收的阶段（build、frontend、release）在 `ready_for_review` 时提供；每步写“做什么”和“应该看到什么” |
| `evidence` | 本次运行中实际执行过的验证；没运行的写 `unverified`，不要写 `pass`。等级不能超过本阶段要求 |
| `blockers` | 当前仍然存在的阻塞（完整列表，不是增量）；没有就写空数组 |
| `approval_required` | 仅 adaptation 阶段：技术适配声明“需要用户决定的问题”为“无”且没有新增费用/平台/数据外传时写 `false`，否则写 `true` |
| `approval_summary` | `ready_for_review` 时必填，控制台把它显示在审批卡上 |
| `release_request` | 仅 release 阶段，请求部署授权时填写：`{"platform": "", "environment": "", "cost": "", "visibility": "", "data_migration": "", "rollback": ""}` |

## 需要用户填写的配置：`fields`

不要让用户自己去复制、打开、编辑 `.env`。在 `user_actions` 里写 `fields`，控制台会显示输入框，并由控制台把值写进产品文件夹里的配置文件：

| 字段 | 说明 |
| --- | --- |
| `key` | 环境变量名，大写字母、数字、下划线 |
| `label` | 界面上显示的名字 |
| `secret` | 是否保密（Key、Token、密码）。不写时按变量名判断：含 KEY、TOKEN、SECRET、PASSWORD 的视为保密 |
| `required` | 默认 `true`；可选项写 `false` |
| `default` / `options` | 非保密字段的默认值和候选值 |
| `help` | 一句话说明去哪里获取 |
| `file` | 写在动作上，默认 `.env`；只能是产品文件夹内以 `.env` 开头或结尾的文件 |

- 先提交 `.env.example`（只有变量名和示例值），控制台在 `.env` 不存在时以它为底稿。
- 控制台会把 `.env` 加入 `.gitignore`、设为仅本人可读，并在下一次运行时告诉你哪些变量已填写；保密值不会出现在给你的指令里。
- 程序运行时从环境变量或 `.env` 加载即可。**不要读取、打印保密值，也不要把它写进文档、日志、测试输出或收件箱。**
- 只有不能在控制台里完成的操作（注册账号、实名认证、在第三方网站点按钮）才用 `steps` + 勾选“已完成”。

