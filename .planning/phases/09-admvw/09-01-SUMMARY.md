---
phase: 09-admvw
plan: 01
subsystem: testing
tags: [pytest, pytest-asyncio, vitest, vue-test-utils, admin, conversations, isolation, RED, TDD]

# Dependency graph
requires:
  - phase: 08-iso
    provides: "Conversation.created_by owner 维度 + owner-scoped service + test_conversation_isolation.py 回归基线 + conftest JWT/superuser fixtures"
provides:
  - "后端 RED 测试集 server/tests/test_admin_conversations.py（ADMVW-01/02/03 + 非 admin 403 + 匿名拒绝 + 不可续聊 + fork 归属）"
  - "前端 RED spec web/src/pages/admin/__tests__/conversations.spec.ts（requiresAdmin + DataTable owner 渲染 + 只读无写入入口 + fork→/chat?conversation=）"
  - "Phase 8 隔离套件显式纳入回归保障（未改动，39 passed 全绿）"
affects: [09-02, 09-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-first 行为契约：仅 import 既有模型，端点未实现 → 断言预期 404/RED，--co 可收集"
    - "admin gate 语义 403（非 404-everything）：非管理员明确 403，区别于 Phase 8 普通路径越权 404"
    - "前端动态 @vite-ignore import 缺失页面：spec 可加载、用例各自 RED，避免 transform 期整 suite 失败"

key-files:
  created:
    - server/tests/test_admin_conversations.py
    - web/src/pages/admin/__tests__/conversations.spec.ts
  modified: []

key-decisions:
  - "fork 测试先断言 status_code ∈ {200,201}（RED 在此失败），GREEN 后再跑 DB 归属/消息条数断言——避免 RED 期 resp.json() KeyError 掩盖本意"
  - "test_admin_no_stream_route 在 Wave 0 即 PASS（路由不存在 → 404 正是契约），固化「admin 后台无流式续聊通道」且 GREEN 后仍成立"
  - "前端用动态拼接 specifier + @vite-ignore 规避 vite 静态解析缺失模块，使 spec 可加载、4 用例各自 RED（优于整 suite 解析失败）"

patterns-established:
  - "ADMVW RED 契约：admin 跨用户 list/detail 200、非 admin 403、匿名 401/403、写方法 405、fork created_by=admin + status=DRAFT + 复制全部消息 + 源会话不变"
  - "plan-checker #2「不可续聊」双重钉死：admin detail POST → 405（方法层）+ stream 子路径 → 404（路由层）"

requirements-completed: []

# Metrics
duration: 12min
completed: 2026-06-09
---

# Phase 9 Plan 01: 管理员只读会话后台 RED 验证脚手架 Summary

**后端 10 用例 + 前端 4 用例的 RED 测试脚手架，1:1 钉死 ADMVW-01/02/03（admin 看全部 / 非 admin 403 / 匿名拒绝 / 只读 405 / fork 归属 admin + DRAFT + 复制消息）并显式纳入 Phase 8 隔离回归保障**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-09T23:32Z (UTC+8 显示)
- **Completed:** 2026-06-09
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- 后端 `test_admin_conversations.py`：10 用例覆盖 ADMVW-01（list 跨用户 200 / 非 admin 403 / 匿名拒绝 / detail 含 messages）、ADMVW-02（PATCH/DELETE/POST → 405 + stream 子路径 404）、ADMVW-03（fork created_by=admin + 消息复制 + status=DRAFT + 源不变 + 非 admin 403）。
- 前端 `conversations.spec.ts`：4 用例覆盖 requiresAdmin meta、listAdminConversations 渲染含 owner 行、只读无写入入口、fork→`router.push('/chat?conversation=<id>')`（query 键名经 chat store `restoreFromURL` 确认为 `conversation`）。
- Phase 8 隔离套件 `test_conversation_isolation.py` 显式作回归基线，未改动，39 passed 全绿。

## Task Commits

1. **Task 1: 后端 RED 测试集 test_admin_conversations.py** — `a4c5dd43` (test)
2. **Task 2: 前端 RED 组件 spec conversations.spec.ts** — `909236d9` (test)

## Files Created/Modified
- `server/tests/test_admin_conversations.py` - admin 只读后台后端行为契约 RED 断言（ADMVW-01/02/03 + 不可续聊）
- `web/src/pages/admin/__tests__/conversations.spec.ts` - admin 会话页前端契约 RED spec（requiresAdmin / 只读 / fork 跳转）

## Test Status (Expected RED)

| Suite | 结果 | 说明 |
|-------|------|------|
| `pytest tests/test_admin_conversations.py --co -q` | 10 collected | 收集通过（无 import/collection error） |
| `pytest tests/test_admin_conversations.py -q` | 9 failed, 1 passed | **预期 RED**：端点未实现 → 404；`test_admin_no_stream_route` 因路由本就不存在而 PASS（契约即此） |
| `pytest tests/test_conversation_isolation.py -q` | 39 passed | Phase 8 回归基线全绿（未改动） |
| `vitest run .../conversations.spec.ts` | 4 failed | **预期 RED**：`conversations.vue` 未实现 → 动态 import reject |

预期 RED 将在 09-02（后端 admin views/urls/service/serializer）与 09-03（前端 conversations.vue + adminConversations.ts）落地后转 GREEN。

## Decisions Made
- fork 用例先断言状态码再查库，避免 RED 期 `resp.json()` 报错掩盖断言本意（见 frontmatter key-decisions）。
- 前端缺失页面用 `@vite-ignore` 动态 import，spec 可加载且 4 用例各自 RED（acceptance 接受「模块解析失败」，但本形态更利于 GREEN 复用）。

## Deviations from Plan

None - plan executed exactly as written. 计划已显式要求 plan-checker #2 的「不可续聊」断言，本实现以 `test_admin_readonly_no_continue`（POST detail → 405）+ `test_admin_no_stream_route`（stream 子路径 → 404）双重满足。

## Issues Encountered
- 初版前端 spec 用静态/别名动态 import 缺失页面，vite transform 期解析失败导致整 suite 加载失败（0 test）。改为相对路径 + `@vite-ignore` 动态 specifier 后，spec 正常加载、4 用例各自 RED。

## User Setup Required
None - 纯测试脚手架，无外部服务配置。

## Next Phase Readiness
- 09-02（后端）可直接以本测试集为 GREEN 目标：实现 `/api/admin/conversations/`（IsSuperUser + 默认认证，只读 GET + fork POST）、`ConversationService.admin_*`、`AdminConversationListSerializer`。
- 09-03（前端）以 `conversations.spec.ts` 为 GREEN 目标：`adminConversations.ts` + `admin/conversations.vue`（DataTable + 只读 + fork→`/chat?conversation=`）。
- 无阻塞项。

## Self-Check: PASSED

- FOUND: server/tests/test_admin_conversations.py
- FOUND: web/src/pages/admin/__tests__/conversations.spec.ts
- FOUND: .planning/phases/09-admvw/09-01-SUMMARY.md
- FOUND commit: a4c5dd43 (Task 1)
- FOUND commit: 909236d9 (Task 2)

---
*Phase: 09-admvw*
*Completed: 2026-06-09*
