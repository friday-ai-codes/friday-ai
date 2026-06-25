# Phase 81: Cursor 回流 + 前端项目工作台 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，elegant defaults）+ 配套 81-UI-SPEC.md（前端设计契约）

<domain>
## Phase Boundary

打通 Cursor↔Friday 双向闭环（分支反查召回 + rules 强制 + 沉淀上报写回），并交付项目工作台前端，让团队在 Friday 上看到/参与项目全部上下文。**本期收口前 4 个 Phase 累计 deferred 的全部前端 UI。**

**In scope（CURSOR-01~03, UI-01~03）:**
- MCP 分支→项目反查 + 召回（复用 Phase 80 context packer，MCP 链写 `RetrievalTrace`）
- Cursor rules 模板（强制先关联本分支项目、召回再编码）
- Cursor 沉淀上报写回 memory/知识（认证 + 归因 + 脱敏 + 质量门槛防噪音）
- 前端项目工作台：列表（筛选 + 创建）+ 详情（概览/成员/工作项/工件在线查看/记忆编辑/关联）+ 工件类型后台管理页 + LLM 记忆提议确认 UI

**Out of scope（v2 PROJX）:**
- Cursor 专用插件 / hook 主动采集（本期走 MCP + git + 上报 API）
- 项目看板可视/燃尽/进度统计（PROJX-05）
- UI 稿多模态召回（PROJX-01）
</domain>

<decisions>
## Implementation Decisions

### Cursor 回流（CURSOR-01~03，后端 + MCP）
- **CURSOR-01 分支反查**：复用 `server/mcp_tools/`，新增 MCP 工具 `lookup_project_by_branch(branch_name)`——从分支名 `feat/xxxx-m{work_item_id}-slug` 抽 `work_item_id`（复用既有分支命名解析），经 `ProjectWorkItemLink`(Phase 78) → `Project` 反查；命中后经 **Phase 80 context packer** 召回需求/工件/记忆上下文。**MCP 链召回写 `RetrievalTrace`**（补齐 Phase 80 标注的 MCP 链）+ 条数/分层耗时/score。多/无命中 fail-soft（返回空或候选列表，不抛）。
- **CURSOR-02 rules 模板**：提供 Cursor rules 模板（`.mdc` 文本，强制"先 `lookup_project_by_branch` 关联项目、召回上下文，再编码"）——随项目下发（API 生成项目专属 rules 文本）或仓库内文档化，plan-phase 定下发方式（默认：项目详情页可复制/下载 + 文档）。
- **CURSOR-03 上报写回**：MCP/API 上报端点（认证走既有 `env_FRIDAY_TASK_USER_TOKEN`/PAT 通道）→ 经身份映射归因（`resolve_feishu_user`/触发用户）→ **脱敏不可绕过**（`redact_*`）→ **质量门槛防噪音**（长度/重复/低信息量过滤，阈值可配）→ 写入项目 memory（经 Phase 80 `MemoryService`，默认入 **draft 待确认**，不直接 active，防污染共享记忆）或知识（`knowledge/ingestion`）。带 `initiated_by_user_id`。

### 前端工作台（UI-01~03，见 81-UI-SPEC.md）
- 复用 `web/src/pages/spaces/`（`index.vue` + `[id].vue`）范式 + 既有 `web/src/api/projects.ts`(Phase 77)、`members.ts`、`knowledge.ts` 等；新增 `artifacts.ts`/`projectMemory.ts`/`mergeRequests.ts`/`artifactTypes.ts` API 模块对接 Phase 79/80 后端。
- 技术栈固定：Vue 3 `<script setup>` + TS + Tailwind 4 + reka-ui + `class-variance-authority` + TanStack Query（server state）+ Pinia（必要时）+ vee-validate + zod（表单）+ vue-i18n（**默认中文**）+ unplugin 自动路由（`web/src/pages/` 文件路由）。图标/组件复用既有设计系统。
- **UI-01 列表**：`/projects` 页——按 Space / 状态(developing/archived/terminated) / 成员筛选 + 搜索 + 创建入口（复用 Phase 77 `CreateProjectModal`）。
- **UI-02 详情工作台**：`/projects/[id]` 多 Tab——概览 / 成员(带身份角色，主R 转移) / 工作项(story·缺陷) / 工件(类型分组 + 在线查看：飞书 doc/表格渲染、外链跳转、md 编辑) / 记忆(时间线 + 编辑 + 修订历史) / 关联(知识·仓库·项目·PR/MR，KnowledgeEdge 关系列表)。
- **UI-03**：记忆编辑 + **LLM 提议确认 UI**（draft 列表：接受入库/拒绝/编辑后入库）；**工件类型后台管理页**（超管，`/admin/artifact-types` 或设置区——新增/禁用/删除，禁用/builtin/有实例约束在 UI 明示）。
- 交互/健壮性遵循团队前端规范：加载稳定（骨架屏）、错误兜底、空态、防抖、i18n 全量中文文案、a11y 基本可达；WebSocket 实时（Phase 77 项目成员/状态推送）前端订阅刷新。

### 观测与异步
- MCP 反查召回写 `RetrievalTrace` + 上报条数/分层耗时/score；上报写回为外部触发带 `initiated_by_user_id` + 脱敏 + 质量门槛；新增 LLM（若上报二次提炼）赋 `call_source`。
- 后端 async ORM 走 `sync_to_async`；前端经统一 `api/client.ts`（cookie-JWT refresh）。

### 前端测试与门禁
- 关键组件/页面 vitest（happy-dom）+ 守护测试（i18n 真实 zh-CN messages 断言关键文案、权限态、空/错/载态）；`pnpm vue-tsc --noEmit` 绿；不破坏既有 ~130 前端测试基线。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 后端：Phase 77~80 全部 service/API（`ProjectService`/`ArtifactService`/`MemoryService`/`MergeRequestService`/context packer/`resolve_feishu_user`/KnowledgeEdge 查询/`create_project` 节点）+ `server/mcp_tools/`（Cursor 回流地基 + `env_FRIDAY_TASK_USER_TOKEN`）。
- 前端：`web/src/pages/spaces/`（列表 + 详情范式）、`web/src/api/projects.ts`(Phase 77) + `members.ts`/`knowledge.ts`/`chat.ts`、`web/src/api/client.ts`（typed fetch + JWT refresh）、`web/src/components/`（reka-ui 组件 + `CreateProjectModal` Phase 77）、`web/src/stores/`、i18n `zh-CN.json`。

### Established Patterns
- 文件路由（unplugin-vue-router），`~/` 别名 → `web/src/`；barrel `api/index.ts`。
- TanStack Query useQuery/useMutation + 条件 refetchInterval 轮询范式；useConfirmDialog 危险操作二次确认；守护测试以真实 zh-CN messages 锁文案。
- MCP 工具注册范式（`mcp_tools/`）；分支命名 `feat/xxxx-m{work_item_id}-slug` 解析既有。

### Integration Points
- 工作台前端 ← Phase 77~80 REST API（projects/members/artifacts/memory/mr/links/recall）+ WS 实时。
- MCP 反查 ← branch → work_item_id → ProjectWorkItemLink → Project → context packer。
- 上报写回 → MemoryService(draft) / knowledge ingestion（认证 + 归因 + 脱敏 + 质量门槛）。
</code_context>

<specifics>
## Specific Ideas

- Cursor 上报默认入 memory **draft 待人工确认**（不直接 active），与 MEM-04 一致防共享记忆污染。
- rules 模板默认项目详情页可复制/下载 + 文档化（双轨），不强绑单一下发机制。
- 工件在线查看：飞书 doc/表格走 Phase 79 后端渲染 API；UI 稿仅元数据 + 外链跳转（不嵌图形正文）。
- 前端不重复造组件，最大化复用 spaces 页与既有设计系统；详情页 Tab 懒加载降首屏负担。
- 质量门槛阈值可配（系统设置），防 Cursor 上报噪音。
</specifics>

<deferred>
## Deferred Ideas

- Cursor 专用插件/hook 主动采集 → v2（PROJX-04）。
- 项目看板可视/燃尽/进度统计 → v2（PROJX-05）。
- UI 稿多模态/figma API 正文召回 → v2（PROJX-01）。
- 真实 Cursor 端 MCP 反查 + 上报端到端、真实飞书凭证在线查看 → 里程碑级人工验收。
</deferred>
