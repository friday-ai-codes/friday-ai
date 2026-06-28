# P3 技术方案：内嵌 AI 会话栏（前端）

**所属里程碑：** 项目作战室 / 工作区大盘（见 `MILESTONE-PROPOSAL.md`）
**Phase：** P3（Wave 2，前端，本期重头）
**产出方式：** Cursor 技术方案（非 GSD）
**定稿：** 2026-06-27 · 状态：Ready to execute（依赖 P1 壳 + P2 后端）

---

## 1. 目标

把 P1 的右侧会话栏壳变成**真实可用的项目 AI 对话**：三组会话切换（项目共享只读 / 我的项目个人 / 我的个人）、共享会话 clone 贡献、消息显示**头像+名字 + 相对时间(+精确 tooltip)**、会话头显示**单会话执行时长**、收起/展开/放大三态、归档/删除/互转（按 P2 权限），且**不污染全局 `chatStore`**。

## 2. 范围

**做：** API/类型补字段、可实例化对话容器（与全局 store 解耦）、会话切换/新建/clone/归档/删除/互转、消息头像名字+时间、执行时长、收展放、i18n、测试。
**不做：** 后端（P2 已出）、星图（P4）、分区编辑（P5）、迭代。
**不破坏：** 全局 `/chat` 页行为。

## 3. 现状基线（已核对）

- 全局聊天是**单实例整页**：`web/src/pages/chat.vue` + `web/src/stores/chat.ts`（`selectedSpaceId`/`currentConversation`/`restoreFromURL` 等全局单例假设）→ 不能直接复用为内嵌实例。
- 现成 API（`web/src/api/chat.ts`）：`listConversations` / `createConversation` / `getConversationDetail` / `getConversationRuntime` / `forkConversationForMessage` / `patchConversation` / `deleteConversation` / `interruptConversation`。
- 现成组件：`ChatMessageArea` / `ChatInput` / `ChatMessageBubble` / `ChatToolCall` / `ConversationBadges` 等。
- P1 已建：`ProjectAssistantRail.vue`（壳，三态 + slot 预留）。
- P2 已出契约：会话含 `visibility`/`created_by`/`duration_ms`，消息含 `user`/`created_at`，fork 支持 `bound_project_id`+`visibility`。

## 4. 任务分解（文件级）

### T1 — API/类型补字段
- `web/src/types/chat.ts`：
  - `Conversation` + `visibility: 'personal'|'shared'`、`bound_project: string|null`、`created_by?: {id,username,display_name,avatar_url?}`、`duration_ms?: number`。
  - `CreateConversationParams` + `bound_project_id?`、`visibility?`。
  - `PatchConversationParams` + `visibility?`、`bound_project_id?`。
  - `ListConversationsParams` + `bound_project?`、`visibility?`。
  - `ForkConversationRequest` + `bound_project_id?`、`visibility?`。
  - message 类型 + `user?` brief + `created_at`。
- `web/src/api/chat.ts`：`listConversations` 透传 `bound_project`/`visibility`；fork 透传目标类型。

### T2 — 可实例化对话会话核心（解耦全局 store）
- 抽出 `web/src/composables/useChatSession.ts`：把"当前会话 + 消息列表 + 发送 + SSE 流 + 中断 + runtime"逻辑从 `chatStore` 提炼成**可多实例 composable**（入参 `{ boundProjectId, defaultVisibility }`）。
- 全局 `chat.vue` **本期不强制迁移**（保持现状），但 composable 设计为二者皆可用（降低重复、为后续统一铺路）。
- 关键：SSE 连接、消息累积、frozen/pin、错误处理与全局互不共享状态。

### T3 — 会话栏主体 `ProjectAssistantRail.vue`（替换占位）
- 三态：collapsed(窄条) / expanded(侧栏) / maximized(全屏 Dialog，复用同一 `useChatSession` 实例，状态不丢)。
- 组成：
  - `ConversationSwitcher.vue`（新）：三分组列表 —— 「项目共享(只读)」/「我的项目个人」/「我的个人」；徽标区分类型；归档项收纳。
  - `ChatMessageArea`（复用）：渲染消息；传入项目实例数据。
  - `ChatInput`（复用）：共享只读会话时禁用并显示 `CloneToContributeBar`（"克隆到我的会话以发言" → 调 fork(bound_project=本项目, visibility=personal) → 切到新副本）。
  - 会话头：类型徽标 + **执行时长**(`duration_ms` 格式化) + 操作菜单（fork/归档/删除/互转）。
- 新建：默认 `visibility=personal` + `bound_project=本项目`；选项可建共享。
- 互转：菜单触发 → `useConfirmDialog` 二次确认（个人→共享提示"历史将对全项目可见"；共享→个人仅创建者可见入口）→ `patchConversation({visibility})`。
- 删除/归档：按 P2 权限，前端按 `created_by`/角色 显隐入口（最终以后端为准）。

### T4 — 消息头像/名字/时间
- 改 `ChatMessageBubble.vue`：user 消息展示 `created_by`/message.user 的**头像(首字母色块，沿用现有 pattern；有 avatar_url 则用图) + 名字**（共享会话多人时尤其需要）。
- 时间：相对时间用 `@vueuse/core` `useTimeAgo`（"x 分钟前"）；hover tooltip 显示精确 `YYYY-MM-DD HH:mm:ss`（reka-ui Tooltip 或 `title` 属性 + 现有 tooltip 组件）。
- 防 CLS：头像声明尺寸；时间区固定宽度。

### T5 — i18n
- `projects.warroom.assistant.*`：三组标题、新建/共享选项、clone 提示、互转确认文案、时长标签、收展放 aria-label、空态。

### T6 — 测试
- `ConversationSwitcher`：三分组归类（按 visibility + bound_project + created_by）正确。
- clone 流：只读共享 → 点击 → fork 调用参数正确 → 切到新副本可输入。
- 只读态：共享非 owner 时输入禁用 + CloneToContributeBar 出现。
- 时间渲染：相对时间 + tooltip 精确值。
- 时长：`duration_ms` 格式化展示。
- 三态切换 + 放大保持会话状态 + reduced-motion。
- 权限显隐：非创建者无删除/共享→个人入口。

## 5. 验收标准
- 页内可与 AI 对话，自动带项目上下文（bound_project）。
- 三组会话清晰可切；共享只读、clone 后可发言。
- 消息显示头像+名字 + 相对时间(+精确 tooltip)；会话头显示执行时长。
- 收起/展开/放大可用；`<lg` 转 Drawer；放大全屏且状态不丢。
- 不污染全局 `/chat`；新增测试通过；typecheck/lint 通过。

## 6. 风险与缓解
- **store 解耦**（最高风险）：`useChatSession` 抽取需覆盖 SSE/frozen/pin/中断；先小步抽取 + 单测，再接 UI。
- **SSE 多实例**：确保项目实例与全局实例连接独立、卸载时清理。
- **权限前后端一致**：前端仅做显隐，越权最终以后端 403/404 为准。

## 7. 衔接
- 上游：P1 壳 + P2 契约。下游：P5 可在会话栏旁联动（非强依赖）。

---
*P3 完成后回填 `MILESTONE-PROPOSAL.md` §11 P3 状态。*
