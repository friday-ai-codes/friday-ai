---
phase: 09-admvw
plan: 02
subsystem: backend
tags: [django, adrf, drf, admin, conversations, isolation, IsSuperUser, GREEN, ADMVW]

# Dependency graph
requires:
  - phase: 09-admvw
    plan: 01
    provides: "后端 RED 测试集 test_admin_conversations.py（ADMVW-01/02/03 + 非 admin 403 + 匿名拒绝 + fork 归属）"
  - phase: 08-iso
    provides: "Conversation.created_by owner 维度 + owner-scoped service + test_conversation_isolation.py 回归基线"
provides:
  - "GET /api/admin/conversations/（跨用户只读列表，含 owner + message_count，IsSuperUser）"
  - "GET /api/admin/conversations/<uuid>/（只读详情 + 消息；写方法自动 405）"
  - "POST /api/admin/conversations/<uuid>/fork/（admin fork-to-own → {conversation_id}）"
  - "ConversationService.admin_list_conversations / admin_get_with_messages / admin_fork_to_own"
  - "AdminConversationListSerializer（+owner +message_count）"
affects: [09-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "物理分离 admin 端点：全新 admin_views.py + admin_urls.py，挂载 /api/admin/，零改动 chat/views.py（ISO-03 不回退）"
    - "只读 = 不实现写方法（DRF 自动 405），而非加 read_only 开关"
    - "admin 授权用声明式 IsSuperUser + 默认认证类（不复用 OptionalJWTAuthentication/ChatAuthPermission，拒匿名）"
    - "async 序列化 async-safe：service 层 select_related 预取 + sync_to_async 包 .data（规避 SynchronousOnlyOperation）"

key-files:
  created:
    - server/chat/admin_views.py
    - server/chat/admin_urls.py
  modified:
    - server/chat/conversation_service.py
    - server/chat/serializers.py
    - server/friday/urls.py

key-decisions:
  - "admin fork 显式 created_by=admin + status=DRAFT + 复制全部消息（去掉 created_at__lt 截断），规避 Pitfall 4（pin 冻结）/ Pitfall 5（owner 继承错误）"
  - "fork 副本携带源 provider_credential_id（与普通 fork 一致；status=DRAFT 不冻结，admin 可改）"
  - "admin detail 复用 ConversationDetailSerializer + ConversationMessageSerializer，分别序列化后合并（避开 Django 反向 FK 直接赋值禁令），与既有 ConversationDetailView 同源"
  - "admin_fork_to_own 加结构化审计日志 logger.info(admin_conversation_forked, admin_id, source/forked id, copied_count)（V7）"

patterns-established:
  - "ADMVW 端点契约：list/detail GET-only 200、非 admin 403、匿名 401/403、写方法 405、fork created_by=admin + status=DRAFT + 复制全部消息 + 源不变"

requirements-completed: [ADMVW-01, ADMVW-02, ADMVW-03]

# Metrics
duration: ~10min
completed: 2026-06-09
---

# Phase 9 Plan 02: 管理员只读会话后台后端 Summary

**物理分离、IsSuperUser 守卫的只读会话后台后端：新增 `/api/admin/conversations/` list+detail（GET-only，写方法自动 405）+ admin fork-to-own（深拷贝会话+全部消息，created_by=admin、status=DRAFT），把 09-01 后端 10 个 RED 用例全部转 GREEN，且 Phase 8 隔离套件 39 用例保持全绿、普通 /api/chat/ 路径零改动**

## Performance
- **Duration:** ~10 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files created:** 2 / modified: 3

## Accomplishments
- **ADMVW-01**：`AdminConversationListView`（跨用户列表，无 owner 过滤，含 owner + message_count）+ `AdminConversationDetailView`（只读详情 + messages）。非 admin → 403，匿名 → 401/403（IsSuperUser + 默认认证类，不复用 chat 开放模式认证）。
- **ADMVW-02**：detail view 只定义 `get` → PATCH/DELETE/POST 续聊自动 405；admin 端点无 stream/send 子路由（路由层即无续聊入口 → 404）。
- **ADMVW-03**：`ConversationService.admin_fork_to_own` 深拷贝会话 + 全部消息，`created_by=admin`、`status=DRAFT`，源会话不变，返回 `{conversation_id}`；`AdminConversationForkView` POST → 201。
- service 层 `admin_list_conversations`（select_related + Count annotate）/ `admin_get_with_messages`（无 owner 过滤）落地；`AdminConversationListSerializer` + `_OwnerBriefSerializer` 加 owner/message_count，不污染既有契约。
- 普通 `/api/chat/` 路径（chat/views.py、chat/urls.py）零改动；`conversation_service.py` 无新增 superuser bypass。

## Task Commits
1. **Task 1: service admin_* + AdminConversationListSerializer** — `60a0712e` (feat)
2. **Task 2: admin_views.py（List/Detail/Fork，IsSuperUser）** — `8494f2e1` (feat)
3. **Task 3: admin_urls.py + 顶层挂载 /api/admin/** — `44743ff6` (feat)

## Files Created/Modified
- `server/chat/admin_views.py` (created) — AdminConversationListView / DetailView / ForkView（IsSuperUser，只读 GET + fork POST）
- `server/chat/admin_urls.py` (created) — /conversations/ , /conversations/<uuid>/ , /conversations/<uuid>/fork/ 路由
- `server/chat/conversation_service.py` (modified) — 新增 admin_list_conversations / admin_get_with_messages / admin_fork_to_own
- `server/chat/serializers.py` (modified) — 新增 AdminConversationListSerializer + _OwnerBriefSerializer
- `server/friday/urls.py` (modified) — api_patterns 新增 `path("admin/", include("chat.admin_urls"))`

## Test Status (GREEN)

| Suite | 结果 | 说明 |
|-------|------|------|
| `pytest tests/test_admin_conversations.py tests/test_conversation_isolation.py -q` | **49 passed** | admin 10 用例 GREEN + Phase 8 隔离 39 用例保持全绿 |
| `manage.py makemigrations --check --dry-run chat` | No changes detected | 无模型变更（admin 纯新增 view/url/service/serializer） |
| `rg "is_superuser" chat/views.py` | 仅 pre-existing | 普通端点无新增 bypass（views.py 本期零改动，git diff 空） |
| `rg "is_superuser" chat/conversation_service.py` | NONE | owner-scoped 方法无 superuser bypass（仅新增 admin_* 方法含 admin 语义） |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- admin detail 序列化原计划「将 messages 附到 conversation 后用 ConversationDetailSerializer」，但 Django 禁止对反向 FK（`conversation.messages`）直接赋值。改为分别用 ConversationDetailSerializer（标量字段）+ ConversationMessageSerializer（messages）序列化后合并 dict，与既有 `ConversationDetailView` 同源范式，async-safe（sync_to_async 包裹）。

## User Setup Required
None - 纯后端代码新增，无外部服务配置。

## Next Phase Readiness
- 09-03（前端）可直接对接：`adminConversations.ts`（listAdminConversations / getAdminConversation / forkAdminConversation）+ `admin/conversations.vue`（DataTable + 只读 + fork→`/chat?conversation=<id>`），后端契约已 GREEN。
- 无阻塞项。

## Self-Check: PASSED

- FOUND: server/chat/admin_views.py
- FOUND: server/chat/admin_urls.py
- FOUND commit: 60a0712e (Task 1)
- FOUND commit: 8494f2e1 (Task 2)
- FOUND commit: 44743ff6 (Task 3)

---
*Phase: 09-admvw*
*Completed: 2026-06-09*
