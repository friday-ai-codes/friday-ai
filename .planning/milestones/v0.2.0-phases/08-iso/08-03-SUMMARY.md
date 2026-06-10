---
phase: 08-iso
plan: 03
subsystem: chat
tags: [django, adrf, drf, idor, access-control, owner-gate, sse, conversation, isolation, 404]

# Dependency graph
requires:
  - phase: 08-iso
    plan: 02
    provides: "ConversationService.aget_for_user / list_conversations(user) / create_conversation(...,user) / delete_conversation(id,user) — owner gate 收口入口"
  - phase: 08-iso
    plan: 01
    provides: "test_conversation_isolation.py RED 脚手架（#1-12 cross-user-denied + owner-allowed + admin-no-bypass + stream 前置 404），本 plan 的唯一验收基准"
provides:
  - "直接会话端点 #1-12 全部接线 owner gate：list/create/detail/delete/patch/preflight/runtime/messages-delete/fork/stream/interrupt/export-to-feishu"
  - "SSE stream 在 StreamingHttpResponse 构造前 owner-scoped 404（非流内 error 事件）"
  - "create 写入 created_by=request.user（已认证时）"
  - "owner gate 作主/外层（404、无 superuser bypass）；既有 has_project_access（403、superuser bypass）保留为 null-owner/共享行次层"
affects: [08-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "owner gate 主层模式：aget_for_user（detail/runtime/patch/stream/interrupt）或 created_by_id 比对（已 select_related 取得的 conversation：preflight/messages-delete/fork/export），统一 owner-miss → 404"
    - "owner gate 永远先于既有 has_project_access 执行（preflight 防 provider payload 泄漏、Pitfall 5 SSE 流前 404）"
    - "owner gate 段 0 处 is_superuser（ISO-03）；既有 is_superuser 仅存于保留的次层 has_project_access 分支"

key-files:
  created:
    - .planning/phases/08-iso/08-03-SUMMARY.md
  modified:
    - server/chat/views.py

key-decisions:
  - "preflight/messages-delete/fork/export 用 created_by_id != user.id 的 fetch-then-check（这些 view 已 select_related 取 conversation 供后续使用），detail/runtime/patch/stream/interrupt 用 aget_for_user owner-scoped queryset —— 两种风格按既有取数结构择优，均统一 404"
  - "owner gate 插在既有 has_project_access 之前作主层；既有 403/superuser-bypass 分支原样保留为次层（null-owner/共享行防御），不删除不改 403 语义"
  - "interrupt 在 runner.interrupt()/barrier 取消前加 owner-scoped 存在性校验（T-08-11），保留「无活跃对话」原有 404 分支"

patterns-established:
  - "SSE 流前 404：ChatStreamView.post 在 StreamingHttpResponse 构造前 aget_for_user，越权返干净 HTTP 404 而非 text/event-stream 内 error"
  - "owner gate 主层 + has_project_access 次层 的双层门禁分工（owner 先 404，跨项目再 403）"

requirements-completed: [ISO-02, ISO-03, ISO-04]

# Metrics
duration: ~18min
completed: 2026-06-09
---

# Phase 8 Plan 03: 直接会话端点 #1-12 owner gate 接线 Summary

**把 RESEARCH 端点清单 A 组（直接会话端点 #1-12，含 SSE #10′）全部路由到 Wave 2 的 owner gate：list 仅自己的、create 写 created_by、detail/delete/patch/preflight/runtime/messages-delete/fork/stream/interrupt/export 越权统一 404（无 superuser bypass），SSE 在流打开前返回干净 HTTP 404。**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 1（server/chat/views.py）

## Accomplishments

- **Task 1 — CRUD #1-5**：`ConversationListView.get` 改 `list_conversations(request.user)`（#1 仅列自己）；`ConversationListView.post` 传 `user=request.user`（#2 写 created_by，ISO-01）；`ConversationDetailView.get` 在取数/序列化前先 `aget_for_user` 门禁（#3）；`delete` 走 `delete_conversation(id, request.user)`（#4）；`patch` 把裸 `Conversation.objects.aget` 换 `aget_for_user`（#5）。
- **Task 2 — 只读/清理 #6-9**：preflight（#6）owner gate 置于 select_related 之后、has_project_access 与 aresolve_or_error 之前 → 404，杜绝 provider payload 泄漏（T-08-08）；runtime（#7）换 `aget_for_user`；messages-delete（#8）/ fork（#9）owner gate 置于存在性之后、has_project_access 之前 → 404。既有 403/superuser-bypass 分支保留为次层。
- **Task 3 — 流式/操作 #10-12**：stream（#10）在 `StreamingHttpResponse` 构造前 `aget_for_user` → 干净 HTTP 404（Pitfall 5）；interrupt（#11）在 runner.interrupt()/barrier 取消前加 owner-scoped 存在性校验 → 404（T-08-11），保留「无活跃对话」404；export-to-feishu（#12）取 conversation 后、读 project/messages 前加 owner gate → 404。
- 全部 owner gate 段无 `is_superuser`（ISO-03）；越权一律 404（ISO-04），无新增 403。

## Task Commits

Each task was committed atomically:

1. **Task 1: CRUD #1-5 owner gate** - `722b4b68` (feat)
2. **Task 2: read/cleanup #6-9 owner gate（主层先于 has_project_access）** - `1c179edd` (feat)
3. **Task 3: stream/interrupt/export #10-12 owner gate + SSE 流前 404** - `b953bbb9` (feat)

## Files Created/Modified

- `server/chat/views.py` (modified) — 12 个直接会话端点接线 owner gate；新增 owner-miss → 404 分支（aget_for_user / created_by_id 比对），既有 has_project_access 次层保留。

## Verification Results

- `pytest tests/test_conversation_isolation.py tests/test_conversation_integration.py -q` → **29 passed / 10 failed**。10 failed 全部为 #13-25 组（coding-session #14-19、coding-plan #21-23、list-scoping #13/#20），**按设计待 08-04 接线后转 GREEN**，本 plan 范围外。
- #1-12 全部 GREEN：`test_create_sets_owner` / `test_list_only_owner` / `test_admin_no_bypass` / `test_cross_user_denied[#3..#12]` / `test_stream_cross_user_404` / `test_404_indistinguishable` / `test_open_mode_unaffected`。
- owner-allowed 6 条护栏（detail/runtime/patch/delete/stream/fork）保持 GREEN（gate 未误伤 owner）。
- `pytest tests/test_conversation_integration.py tests/test_conversation_facade.py -q` → **12 passed**（无回归）。
- owner gate 段无 `is_superuser`（仅保留的次层 has_project_access 含 is_superuser，符合设计）。

## Current RED/GREEN Status

**新转 GREEN（本 plan 落地，#1-12）：** `test_create_sets_owner`、`test_list_only_owner`、`test_admin_no_bypass`、`test_cross_user_denied[#3 detail / #4 delete / #5 patch / #6 preflight / #7 runtime / #8 messages-delete / #9 fork / #10 stream / #12 export]`、`test_stream_cross_user_404`、`test_404_indistinguishable`。（#11 interrupt 在无活跃 run 下 Wave 0 即 404，本 plan 补了真实 owner gate 使其在有活跃 run 下也 404。）

**仍 RED（待 08-04 接线 #13-25，符合预期）：** `test_cross_user_denied[#14..#23]`（coding-session/coding-plan 关联端点）+ `test_list_scoping_coding`（#13/#20）。这些经 `.conversation` FK 反查 owner，08-04 落地后转 GREEN。

**持续 GREEN（回归护栏）：** open-mode 回归、owner-allowed 6 条、backfill 3 条、#24/#25（既有 has_project_access 跨用户 404）。

## Decisions Made

- **两种 owner gate 风格按取数结构择优**：detail/runtime/patch/stream/interrupt 走 `aget_for_user`（owner-scoped queryset，对象不为非 owner 物化）；preflight/messages-delete/fork/export 已 select_related 取 conversation 供后续逻辑使用，改用 `created_by_id != user.id` 的就地 fetch-then-check（Pattern 4，`created_by_id` 不触发 async 惰性 FK），二者统一 owner-miss → 404。
- **owner gate 主层、has_project_access 次层**：owner gate 插在既有 has_project_access 之前并先返回 404；既有 403 + superuser-bypass 分支原样保留为 null-owner/共享行次层防御，不改其语义（与 RESEARCH Anti-Pattern 一致）。
- **interrupt 补真实 owner gate**：08-01 已记录「无活跃 run 时 #11 即 404 无法区分 gate 是否生效」，本 plan 在 runner.interrupt()/barrier 取消前加 owner-scoped 存在性校验，使有活跃 run 下越权同样 404（T-08-11）。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Scan

无新增计划外安全面：本 plan 仅在既有 view 内插入 owner gate 接线，未引入新网络端点/认证路径/信任边界。威胁登记表 mitigate 项均已落地：T-08-07（#1-12 IDOR → 404）、T-08-08（preflight owner gate 先于 provider payload）、T-08-09（SSE 流前 404）、T-08-10（owner gate 无 is_superuser）、T-08-11（interrupt owner-scoped 校验）。

## Known Stubs

None - 无占位/桩代码。#13-25 端点未接线属 08-04 明确范围（非本 plan 桩），本 plan 范围内（#1-12）owner gate 全部落地。

## Issues Encountered

- `pytest -k "list or create or detail or delete or patch or admin"` 关键字过滤会顺带匹配 #8（含 "delete"）/#14/#21（含 "detail"）/list_scoping（含 "list"）等非本任务用例，造成「失败」误读；改用显式 node id 校验本任务用例确认全 GREEN。无代码影响。

## User Setup Required

None - 零新增依赖（纯 view 接线）。

## Next Phase Readiness

- 08-04 接线 #13-25 关联端点：CodingSession/CodingPlan/RoutingTrace/IntentTrace 经 `.conversation` FK 反查 owner（`select_related("conversation")` 后 `created_by_id` 比对或 `aget_for_user(conv.id, user)`），使 `test_cross_user_denied[#14..#23]` + `test_list_scoping_coding` 转 GREEN，同时保持 owner-allowed / open-mode 护栏 GREEN。
- #24/#25（routing-trace override / clarification answer）当前经既有 has_project_access 已 404；08-04 需把 owner gate 改为主层（去除对 superuser bypass 的依赖，保证 ISO-03）。

## Self-Check: PASSED

- FOUND: `.planning/phases/08-iso/08-03-SUMMARY.md`
- FOUND: `server/chat/views.py`（含 12 处 owner gate 接线，`aget_for_user` / `created_by_id` 比对）
- FOUND commits: `722b4b68`, `1c179edd`, `b953bbb9`
- Verify: #1-12 isolation 用例 + stream 前置 404 + 404-indistinguishable GREEN；integration + facade 12 passed 无回归；owner gate 段 0 处 is_superuser。

---
*Phase: 08-iso*
*Completed: 2026-06-09*
