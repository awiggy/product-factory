# 默认前端栈（Web）

新 Web 项目无约束时直接采用；已有项目沿用合理框架，不为本文件迁移。

## 三层规则

**A 强制（所有项目）**
- TypeScript 严格模式；核心业务类型不用 `any`，外部数据用 `unknown` 接住再收窄或运行时校验。
- 接口调用集中在 API 层，不在页面组件里散落 `fetch`；错误在适配层归一化。
- 后端是任务状态与业务结果的唯一事实来源。
- 加载、空、成功、失败、等待确认、断线恢复都要设计。
- 密钥、服务商凭证、私密系统提示词不进浏览器。
- 核心页面支持合理的桌面与移动布局；核心操作可用键盘完成。
- 重要提交防重复，重要删除需确认。
- 通过代码检查、构建检查和真实浏览器验收；不能只用 mock 数据宣布“前后端完成”。

**B 默认（Web MVP）**
- Node 当前 LTS、npm；Next.js 稳定版（App Router）；React 随 Next 官方支持版本。
- Tailwind CSS + CSS 语义变量（颜色、圆角、间距用语义命名）；图标 Lucide。
- 测试：Vitest + React Testing Library；Playwright 覆盖核心闭环。
- 创建项目时记录实际使用的稳定版本并锁定依赖，不永久锁死某个大版本。

**C 按需**

| 能力 | 方案 | 引入条件 |
| --- | --- | --- |
| 复杂无障碍组件 | Radix UI / shadcn/ui | 对话框、菜单、下拉较多 |
| 服务端数据缓存 | TanStack Query | 多页共享请求、缓存与重试变复杂 |
| 全局客户端状态 | Zustand | 远距离组件共享大量临时状态 |
| 复杂表单 | React Hook Form + Zod | 动态字段、多步骤、复杂校验 |
| 接口代码生成 | OpenAPI Generator 等 | 后端有稳定 OpenAPI 契约 |
| 错误监控 | Sentry 等 | 进入真实用户测试或生产 |

## 推荐目录

```text
frontend/
├── app/            # 路由、布局、错误页；api/ 只放确需的同源代理
├── components/ui/  # 通用组件
├── components/layout/
├── features/<业务>/{api,components,hooks,schemas,types.ts}
├── lib/{api,stream,auth,media}/
├── config/  styles/  tests/  e2e/
```

依赖方向：页面 → 业务组件与 Hook → API/Stream/Auth 适配层 → 后端。通用组件不依赖具体业务。

## 渲染与状态

- Server Component 用于静态内容与首屏数据；表单、流式输出、任务控制用 Client Component，并把客户端边界缩到必要区域。
- 可分享、可恢复的状态（任务 ID、页签、筛选）放 URL；凭证与大对象不放 URL。刷新后按 URL 中的任务 ID 向后端恢复真实状态。
- 浏览器专属信息（屏宽、localStorage）不参与服务端首次渲染，避免 hydration 不一致。
- 状态分四类：URL 状态、服务端状态、页面临时状态、用户偏好。localStorage 不能保存并冒充任务结果。

## 统一任务状态

`idle` `submitting` `queued` `running` `streaming` `waiting_user` `succeeded` `partially_succeeded` `failed` `cancelled` `disconnected` `stale`

后端可以用不同名字，前端在适配层映射。未知状态记录日志并显示安全兜底，不能当成成功或失败。每个状态回答三件事：现在发生了什么、我需要做什么、接下来会怎样。加载、空数据、失败、无权限、不存在分别设计，不在接口返回前显示“暂无数据”。

传输选择：单向进度与文本用 SSE / fetch 流；双向高频才用 WebSocket；后端只支持查询时用有节制的轮询；短请求用普通 HTTP。

## 分阶段

| 阶段 | 内容 |
| --- | --- |
| 0 适配与契约 | 适配声明、页面清单、状态表、接口契约、核心验收路径 |
| 1 可运行骨架 | 工程、布局、设计变量、API 客户端、一个代表页；配好 lint/typecheck/test/build |
| 2 第一条真实闭环 | 真实创建任务、展示队列/运行/成功/失败与一种真实产物；核心 E2E |
| 3 完整 Agent 交互 | 流式或轮询、等待确认、取消、重试、断线与刷新恢复、历史 |
| 4 质量与发布准备 | 响应式、无障碍、多媒体、性能、错误监控、隐私；与真实后端完整联调 |

## 最低自动检查

```bash
npm run lint
npm run typecheck   # 没有该脚本时补 tsc --noEmit
npm run test
npm run build
```

未配置的项补齐合理的最低配置，不写“跳过”。

## 不能宣布完成的情况

lint/类型错误未解释；核心接口仍是 mock；核心页面在目标尺寸不可用；失败会丢失用户输入；重复点击创建多个任务；刷新后运行中任务无法恢复；Console 持续报错；与确认的设计或 PRD 明显不一致。确需带问题交付时列出问题、影响、临时处理与后续计划，由用户明确接受。

## 部署前要点（交给 release 阶段核实）

以下来自课程实战，平台细节以当时官方文档为准：

- Next.js 独立部署时可用 `output: "standalone"`，并把 `.next/static`（以及 `public/`）复制进 standalone 目录，否则线上静态资源 404；启动用 `node server.js`。
- `rewrites` 的目标地址在构建时固化：指向后端的地址变量要在构建时注入，部署后再改运行时变量无效。
- 前端通过同源 `/api/*` 代理到后端，避免 CORS。前后端合并部署还是分开部署由平台与需求决定，不默认拆成两套。
- 使用麦克风、摄像头、剪贴板等能力时，线上必须是 HTTPS。
