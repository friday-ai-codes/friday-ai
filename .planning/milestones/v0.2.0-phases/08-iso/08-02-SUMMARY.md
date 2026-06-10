---
phase: 08-iso
plan: 02
subsystem: chat
tags: [django, migration, fk, backfill, async-orm, adrf, owner-scoping, isolation, idor]

# Dependency graph
requires:
  - phase: 08-iso
    plan: 01
    provides: "test_conversation_isolation.py RED 脚手架（created_by 落库/回填 + owner gate 用例），本 plan 的唯一验收基准"
provides:
  - "Conversation.created_by 可空 FK（指向 accounts.User，on_delete=SET_NULL）"
  - "chat/0018 AddField 迁移 + chat/0019 RunPython 历史回填（最早 superuser，可逆，无 superuser 留 null）"
  - "ConversationService.aget_for_user：按 id 取会话的唯一 owner gate 收口入口"
  - "ConversationService.list_conversations/create_conversation/delete_conversation 的 user-aware owner 版本（无 superuser bypass）"
affects: [08-03, 08-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "owner gate = queryset filter（created_by=user）只在 getattr(user,'is_authenticated',False) 为真时叠加；未认证维持开放（隔离以「有用户身份」为前提）"
    - "两步迁移：AddField(0018) 与 RunPython 回填(0019) 分离，回填可逆、无 superuser 早返回不阻塞部署"
    - "async FK 不惰性访问 .created_by，统一用 queryset filter / created_by 写入避免 SynchronousOnlyOperation（Pitfall 4）"

key-files:
  created:
    - server/chat/migrations/0018_conversation_created_by.py
    - server/chat/migrations/0019_backfill_conversation_created_by.py
  modified:
    - server/chat/models.py
    - server/chat/conversation_service.py

key-decisions:
  - "回填排序键 order_by('created_at','id')（accounts.User 实有 created_at，与 accounts/0005 一致；非 date_joined）"
  - "0019 依赖 accounts/0006_add_single_superuser_constraint，保证 User 表与单 superuser 约束就绪"
  - "owner gate 无 is_superuser 分支：源码中 0 处 is_superuser（grep 守卫通过），管理员不 bypass（ISO-03）"
  - "service 签名仅追加 user=None 关键字默认参数，向后兼容既有 views.py 调用（本 plan 不接线端点）"

requirements-completed: [ISO-01]  # created_by 落库 + 历史回填（数据地基）。ISO-02/03/04 owner gate 数据/service 侧已就绪，端点接线待 08-03/08-04 标记完成

# Metrics
duration: ~12min
completed: 2026-06-09
---

# Phase 8 Plan 02: 数据地基 + ConversationService owner-scoped 取数 Summary

**给 Conversation 增加可空 FK `created_by`（0018 AddField + 0019 可逆 RunPython 回填给最早 superuser），并在 ConversationService 引入唯一 owner gate 入口 `aget_for_user` 及 user-aware 的 list/create/delete，无 superuser bypass——把隔离规则收口到 service 单一真源。**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 4（2 created, 2 modified）

## Accomplishments

- **Task 1 — created_by FK + 0018 迁移**：`Conversation` 增加 `created_by = FK(accounts.User, null=True, blank=True, on_delete=SET_NULL, related_name="conversations")`；`makemigrations` 生成 `0018_conversation_created_by`（AddField，含 swappable AUTH_USER_MODEL 依赖）；`makemigrations --check --dry-run` 干净（No changes detected）。
- **Task 2 — 0019 RunPython 回填（可逆）**：forwards 把 `created_by__isnull=True` 的会话（含软删行）回填给 `order_by("created_at","id").first()` 的 superuser，无 superuser 早返回留 null；backwards 全表置 None。`migrate chat` 成功、`migrate chat 0018` 可回滚、再 `migrate chat` 重应用均 OK。3 个 `test_backfill_*` 用例转 GREEN。
- **Task 3 — service owner-scoped 取数**：新增 `aget_for_user(id, user)`（owner gate 唯一收口，越权/不存在统一抛 `Conversation.DoesNotExist`）；`list_conversations(user=None)` / `create_conversation(..., user=None)` / `delete_conversation(id, user=None)` 全部 owner-aware。owner 过滤仅对已认证用户生效，未认证维持开放。源码 0 处 `is_superuser`（grep 守卫通过）。

## Task Commits

1. **Task 1: created_by FK + AddField 0018** - `60b21de8` (feat)
2. **Task 2: RunPython 回填 0019（可逆）** - `40626196` (feat)
3. **Task 3: ConversationService owner-scoped 取数** - `0b885ddb` (feat)

## Files Created/Modified

- `server/chat/models.py` (modified) — `Conversation` 增加 `created_by` 可空 FK（SET_NULL，related_name="conversations"）。
- `server/chat/migrations/0018_conversation_created_by.py` (created) — AddField 迁移，依赖 0017_message_parts + swappable AUTH_USER_MODEL。
- `server/chat/migrations/0019_backfill_conversation_created_by.py` (created) — RunPython(forwards, backwards) 历史回填；依赖 0018 + accounts/0006。
- `server/chat/conversation_service.py` (modified) — 新增 `aget_for_user`；`list/create/delete_conversation` 追加 `user` 参数与 owner 过滤/写入。

## Verification Results

- `makemigrations --check --dry-run` → **No changes detected**（退出 0）。
- `migrate chat` → 0018 / 0019 均 OK；`migrate chat 0018`（回滚 0019）OK；再 `migrate chat` 重应用 OK（可逆验证）。
- `pytest tests/test_conversation_isolation.py -k backfill` → **3 passed**。
- `pytest tests/test_conversation_isolation.py`（全集）→ **13 passed / 24 failed**（Wave 0 基线 10 passed → +3 backfill GREEN）。剩余 24 failed **全部为端点级用例**（`test_create_sets_owner` / `test_list_only_owner` / `test_admin_no_bypass` / 全部 `test_cross_user_denied` / stream / 404-indistinguishable / list-scoping）——按设计待 08-03/08-04 接线 views.py 后转 GREEN，本 plan 不改 views.py。
- `pytest tests/test_conversation_integration.py` → **2 passed**（service 签名仅追加关键字默认参数，既有调用零回归）。
- `grep is_superuser server/chat/conversation_service.py` → **0 匹配**（owner gate 无特权 bypass，ISO-03）。

## Current RED/GREEN Status

**新转 GREEN（3，本 plan 落地）：** `test_backfill_assigns_earliest_superuser` / `test_backfill_no_superuser_leaves_null` / `test_backfill_reversible`。

**仍 RED（24，待 08-03/08-04 端点接线，符合预期）：** `test_create_sets_owner`、`test_list_only_owner`、`test_admin_no_bypass`、`test_cross_user_denied[#3..#23]`、`test_stream_cross_user_404`、`test_404_indistinguishable`、`test_list_scoping_coding`。这些用例经由 HTTP 端点验证，需 views.py 把请求 user 注入 service（Wave 3/4）后才会转 GREEN——service 侧能力已就绪。

**持续 GREEN（回归护栏）：** open-mode 回归、owner-allowed 6 条主路径、Wave 0 即 404 的 #11/#24/#25。

## Decisions Made

- **回填排序键 `order_by("created_at","id")`**：`accounts.User` 实有 `created_at`（无 `date_joined`），与 `accounts/0005` 既有回填一致（RESEARCH A2）。
- **0019 依赖 `accounts/0006`**：确保 User 表与「最多一个 superuser」partial unique index 就绪；系统中「最早」即「唯一」superuser。
- **owner gate 仅对已认证用户生效**：`getattr(user, "is_authenticated", False)` 为真才叠加 `created_by=user` 过滤；隔离以「有可信用户身份」为前提，开放/匿名模式不强加过滤（与 08-01 open-mode 回归护栏一致）。
- **service 签名向后兼容**：`user` 一律 `=None` 关键字默认参数，既有 views.py 调用无需改动即可继续工作，端点接线留待 08-03/08-04。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Scan

无新增计划外安全面：本 plan 仅新增 model 字段 / 迁移 / service 方法，未引入新网络端点、认证路径或信任边界变更。威胁登记表 T-08-03/04/05/06 的 mitigate 项均已落地（owner gate 无 superuser 分支、统一 DoesNotExist、可逆回填 + 无 superuser 早返回、queryset filter 避免惰性 FK）。

## Known Stubs

None - 无占位/桩代码。owner gate 能力已完整实现并由 service 暴露；端点接线（views.py）是 08-03/08-04 的明确范围，非本 plan 的桩。

## User Setup Required

None - 零新增依赖（纯 Django model / migration / service）。生产升级时 0018/0019 随 `migrate` 自动应用；历史会话归属最早 superuser，无 superuser 实例留 null 不阻塞。

## Next Phase Readiness

- 08-03/08-04 接线 views.py：把 `request.user` 透传给 `ConversationService.aget_for_user` / `list_conversations(user=...)` / `create_conversation(..., user=...)` / `delete_conversation(id, user=...)`，并对 coding-session / coding-plan / trace / clarification 端点经 `aget_for_user` 收口取关联会话，使 `test_cross_user_denied` 全 25 路径 + list-scoping + stream 前置 404 转 GREEN。
- 端点统一把 `Conversation.DoesNotExist` 映射为 HTTP 404（ISO-04 不泄漏存在性，与 `test_404_indistinguishable` 对齐）。

## Self-Check: PASSED

- FOUND: `server/chat/migrations/0018_conversation_created_by.py`
- FOUND: `server/chat/migrations/0019_backfill_conversation_created_by.py`
- FOUND: `server/chat/conversation_service.py::aget_for_user`
- FOUND commits: `60b21de8`, `40626196`, `0b885ddb`
- Verify: `makemigrations --check` clean；backfill 3 passed；integration 2 passed；`is_superuser` 0 匹配。

---
*Phase: 08-iso*
*Completed: 2026-06-09*
