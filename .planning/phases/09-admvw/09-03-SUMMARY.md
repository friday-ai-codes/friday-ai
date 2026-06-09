---
phase: 09-admvw
plan: 03
subsystem: frontend
tags: [vue, vitest, admin, conversations, readonly, fork, DataTable, GREEN, ADMVW]

# Dependency graph
requires:
  - phase: 09-admvw
    plan: 01
    provides: "前端 RED spec conversations.spec.ts（requiresAdmin + DataTable owner 渲染 + 只读无写入入口 + fork→/chat?conversation=）"
  - phase: 09-admvw
    plan: 02
    provides: "后端 GET /api/admin/conversations/ list+detail（IsSuperUser，写方法 405）+ POST .../fork/ → {conversation_id}"
provides:
  - "web/src/api/adminConversations.ts（listAdminConversations / getAdminConversation / forkAdminConversation + DTO）"
  - "web/src/components/admin/ReadonlyConversationView.vue（轻量只读消息查看器，hydrateLegacyMessage + getMarkdownRenderer，无写入入口、不耦合 chatStore）"
  - "web/src/pages/admin/conversations.vue（requiresAdmin DataTable + 只读详情对话框 + fork→/chat?conversation=）"
  - "AppSidebar adminNavItems「会话管理」入口（isSystemAdmin 可见）"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "admin api 模块复用 client get/post + 独立 DTO interface（对齐 AdminConversationListSerializer 字段）"
    - "只读查看器与普通 chat 渲染同源（hydrateLegacyMessage→parts + getMarkdownRenderer markdown），但不引入 chatStore/写入控件——物理解耦防误用为写入入口"
    - "行操作列 e.stopPropagation 区分「行点击=只读详情」与「fork 按钮=复制到我的名下」"

key-files:
  created:
    - web/src/api/adminConversations.ts
    - web/src/components/admin/ReadonlyConversationView.vue
    - web/src/pages/admin/conversations.vue
  modified:
    - web/src/components/layout/AppSidebar.vue

key-decisions:
  - "fork 按钮文案用「fork 到我的名下」（同时命中 spec 正则 /fork|复制到我的名下/i），与 toast「已复制到我的名下」一致；按钮文案刻意不含「发送/编辑/删除」以满足只读断言"
  - "只读详情用 Dialog + DialogScrollContent，初始 open=false 不渲染内容（spec 挂载即无 textarea/写入按钮）；行点击才懒加载 getAdminConversation"
  - "ReadonlyConversationView 用 watch(hydrated) 预渲染 text/thinking parts 的 markdown（getMarkdownRenderer 异步单例），tool_use/image 降级为只读 chip，不做流式/工具交互"

patterns-established:
  - "ADMVW 前端契约：requiresAdmin meta + 挂载调 listAdminConversations 渲染含 owner 列、只读无写入入口、fork→router.push(/chat?conversation=<id>)"

requirements-completed: [ADMVW-01, ADMVW-02, ADMVW-03]

# Metrics
duration: ~8min
completed: 2026-06-09
---

# Phase 9 Plan 03: 管理员只读会话后台前端 Summary

**新增 adminConversations api 模块 + 轻量只读消息查看器 ReadonlyConversationView + requiresAdmin 会话管理页（DataTable 列出全部用户会话 / 行点击只读详情对话框 / 「fork 到我的名下」→ /chat?conversation= 续聊）+ AppSidebar 导航入口，把 09-01 前端 4 个 RED spec 全部转 GREEN，typecheck 清白**

## Performance
- **Duration:** ~8 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files created:** 3 / modified: 1

## Accomplishments
- **ADMVW-01**：`adminConversations.ts` 导出 `listAdminConversations`（可选 owner_id/q，URLSearchParams 拼接）/ `getAdminConversation` / `forkAdminConversation` + `AdminConversationListItem`/`AdminConversationDetail`/`AdminForkResult` DTO，路径统一 `/admin/conversations/` 前缀（对齐 09-02）。`conversations.vue` `definePage({ meta: { requiresAdmin: true } })`，onMounted 调 list 渲染含 owner 列（所属用户/标题/状态/消息数/更新时间）的 DataTable。
- **ADMVW-02**：`ReadonlyConversationView.vue` 用 `hydrateLegacyMessage` 归一 parts + `getMarkdownRenderer` 渲染 text/thinking，tool_use/image 降级为只读 chip；**无 `<textarea>`/发送/编辑/删除/导出入口，且不 import chatStore**。详情走 Dialog 只读展示。
- **ADMVW-03**：行操作「fork 到我的名下」→ `forkAdminConversation(id)` → `success('已复制到我的名下')` → `router.push('/chat?conversation=' + conversation_id)`。
- AppSidebar `adminNavItems` 新增 `{ to: '/admin/conversations', label: '会话管理', icon: 'lucide--messages-square' }`（仅 isSystemAdmin 可见），其余导航项零改动。

## Task Commits
1. **Task 1: adminConversations.ts + AppSidebar 导航入口** — `46cab9d7` (feat)
2. **Task 2: ReadonlyConversationView.vue 只读查看器** — `688617b0` (feat)
3. **Task 3: conversations.vue 列表页（DataTable + 只读详情 + fork 跳转）** — `5d02eb43` (feat)

## Files Created/Modified
- `web/src/api/adminConversations.ts` (created) — list/detail/fork api + DTO
- `web/src/components/admin/ReadonlyConversationView.vue` (created) — 轻量只读消息查看器（无写入入口、不耦合 chatStore）
- `web/src/pages/admin/conversations.vue` (created) — requiresAdmin DataTable + 只读详情对话框 + fork 跳转
- `web/src/components/layout/AppSidebar.vue` (modified) — adminNavItems 新增「会话管理」入口

## Test Status (GREEN)

| Suite | 结果 | 说明 |
|-------|------|------|
| `pnpm vitest run src/pages/admin` | **19 passed**（conversations 4 / providers 6 / prompts 9） | 09-01 前端 4 个 RED 用例全转 GREEN（requiresAdmin / owner 渲染 / 只读无写入入口 / fork→/chat?conversation=forked-123），其余 admin 套件未受影响 |
| `pnpm vue-tsc --noEmit -p tsconfig.json` | exit 0 | 类型检查无报错 |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None - 三个任务均一次通过 vitest + typecheck。

## User Setup Required
None - 纯前端新增，无外部服务配置；后端契约 09-02 已 GREEN。

## Next Phase Readiness
- Phase 9 全部 3 plan 完成（RED 脚手架 → 后端 → 前端），ADMVW-01/02/03 端到端落地。
- 人工 VALIDATION（manual）：管理员登录 → 侧栏「会话管理」→ 见他人会话 → 只读详情无输入框 → fork → 跳转 /chat 以 owner 续聊。
- 无阻塞项；可推进 Phase 10。

## Self-Check: PASSED

- FOUND: web/src/api/adminConversations.ts
- FOUND: web/src/components/admin/ReadonlyConversationView.vue
- FOUND: web/src/pages/admin/conversations.vue
- FOUND commit: 46cab9d7 (Task 1)
- FOUND commit: 688617b0 (Task 2)
- FOUND commit: 5d02eb43 (Task 3)

---
*Phase: 09-admvw*
*Completed: 2026-06-09*
