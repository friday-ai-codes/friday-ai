---
phase: 08-iso
plan: 04
subsystem: chat
tags: [django, adrf, drf, idor, access-control, owner-gate, coding-session, coding-plan, routing-trace, clarification, isolation, 404]

# Dependency graph
requires:
  - phase: 08-iso
    plan: 02
    provides: "ConversationService.aget_for_user / Conversation.created_by — owner gate 收口入口与数据地基"
  - phase: 08-iso
    plan: 03
    provides: "直接会话端点 #1-12 owner gate 模式（aget_for_user / created_by_id 比对，统一 404）"
  - phase: 08-iso
    plan: 01
    provides: "test_conversation_isolation.py RED 脚手架（全 25 路径 cross-user-denied + list-scoping），本 plan 的唯一验收基准"
provides:
  - "关联模型端点 #13-25 全部接线 owner gate via .conversation FK：coding-session #13-19、coding-plan #20-23、routing-trace override #24、clarification answer #25"
  - "之前完全无 owner 校验的 coding-session/plan 端点（#13-23）全部经 created_by_id 比对 → 越权 404 / list → []"
  - "#24/#25 去除 owner 判定中的 superuser bypass（ISO-03），管理员越权 → 404；既有 has_project_access 降为 null-owner/共享行次层"
  - "全阶段隔离套件全绿（25 路径 cross-user-denied + list-scoping + owner-allowed + admin-no-bypass）"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "关联模型 owner gate：select_related('conversation') 后比对 conversation.created_by_id != user.id → 404，置于状态机校验/字段读取之前"
    - "list 型端点 owner-scoped 存在性：ConversationService.aget_for_user(conversation_id, user)，越权/不存在统一返回 []（不列他人）"
    - "owner gate 段 0 处 is_superuser（ISO-03）；既有 has_project_access（403、superuser bypass）保留为 owner gate 之后的 null-owner/共享行次层防御"

key-files:
  created:
    - .planning/phases/08-iso/08-04-SUMMARY.md
  modified:
    - server/chat/views.py

key-decisions:
  - "coding-session/plan detail/action 端点统一用 created_by_id 就地比对（这些 view 已 select_related conversation 供后续逻辑使用），list 型用 aget_for_user owner-scoped 存在性；二者 owner-miss 分别 → 404 / []"
  - "#22 batch-create owner gate 插在既有 has_project_access(MEMBER, superuser bypass→403) 之前作主层 —— owner-miss 先 404（不是 403），保留 has_project_access 为 null-owner 次层"
  - "#24/#25 把旧 has_project_access(superuser bypass) 越权块前置/替换为 created_by_id owner gate（去 bypass，ISO-03）；保留越权审计 log；既有 has_project_access 留作 owner gate 之后的次层防御"

patterns-established:
  - "关联模型经 FK 反查 owner：select_related('conversation') + created_by_id 比对，避免 async 惰性 FK（SynchronousOnlyOperation）"
  - "owner gate 主层 404 + has_project_access 次层 403 的双层门禁分工延续至关联模型端点"

requirements-completed: [ISO-02, ISO-03, ISO-04]

# Metrics
duration: ~20min
completed: 2026-06-09
---

# Phase 8 Plan 04: 关联模型端点 #13-25 owner gate 接线 Summary

**把 RESEARCH 端点清单 C/D 组（关联模型端点 #13-25）经 `.conversation` FK 反查 owner 全部接线 owner gate：coding-session #13-19、coding-plan #20-23、routing-trace override #24、clarification answer #25 越权统一 404、list 型返回 []；其中之前完全无 owner 校验的 #13-23 是本阶段最大横向越权面，#24/#25 去除 superuser bypass（ISO-03），全阶段隔离套件全绿（25 路径全覆盖）。**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 1（server/chat/views.py）

## Accomplishments

- **Task 1 — coding-session #13-19**：#14-19（detail / confirm / commit-confirm / pr-confirm / conflict-check / diff-summary）在 `CodingSession.objects.aget(...)` 处 `select_related("conversation")`，取到后立即比对 `coding_session.conversation.created_by_id != request.user.id` → 404（置于状态机校验/字段读取之前，404 body 与既有「CodingSession not found」一致）；#13 list（`CodingSessionListView.get`）把裸存在性查询换成 `ConversationService.aget_for_user(conversation_id, request.user)`，越权/不存在 → `[]`。
- **Task 2 — coding-plan #20-23**：#21 detail / #23 export 经 `plan.conversation.created_by_id` owner gate → 404（#23 置于读取 project 之前）；#20 list 换 `aget_for_user` → `[]`；#22 batch-create 在既有 `has_project_access(MEMBER, superuser bypass→403)` **之前**插入 owner gate（owner-miss 先 404，非 403），保留 has_project_access 为 null-owner 次层。
- **Task 3 — trace/clarification #24-25**：#24 routing-trace override / #25 clarification answer 把旧 `if not is_superuser: has_project_access(...)` 越权块前置/替换为 `original.conversation.created_by_id != user.id` / `trace.conversation.created_by_id != user.id` → 404 的 owner gate（去除 owner 判定中的 superuser bypass，管理员越权 → 404，ISO-03），owner-miss 在落库/resume 之前 404；保留越权审计 log（`*_denied_cross_user`）；既有 has_project_access 保留为 owner gate 之后的次层防御。
- 全部 owner gate 段无 `is_superuser`（ISO-03）；越权对象级一律 404、list 型一律 []（ISO-04），无新增 403。

## Task Commits

Each task was committed atomically:

1. **Task 1: coding-session #13-19 owner gate via session.conversation** - `1857f8f6` (feat)
2. **Task 2: coding-plan #20-23 owner gate via plan.conversation** - `c96d0170` (feat)
3. **Task 3: trace/clarification #24-25 owner gate（去 superuser bypass）** - `88263c45` (feat)

## Files Created/Modified

- `server/chat/views.py` (modified) — 13 个关联模型端点（#13-25）接线 owner gate：`select_related("conversation")` + `created_by_id` 比对 → 404（detail/action），`aget_for_user` → [](list)；#24/#25 去除 owner 判定 superuser bypass，既有 has_project_access 保留为次层。

## Verification Results

- `pytest tests/test_conversation_isolation.py -q` → **37 passed**（全 25 路径 cross-user-denied + list-scoping(coding-session/coding-plan) + owner-allowed + admin-no-bypass + stream 前置 404 + 404-indistinguishable 全绿）。
- 全套回归 `pytest tests/test_conversation_isolation.py tests/test_conversation_integration.py tests/test_coding_session_service.py tests/test_chat_views.py -q` → **63 passed**（无回归）。
- `pytest tests/test_conversation_facade.py -q` → **10 passed**。
- `python manage.py makemigrations --check --dry-run` → **No changes detected**（退出 0；本 plan 仅改 views.py，无 schema 变更）。
- owner gate 段无 `is_superuser`：#24/#25 的 owner gate 块用 `created_by_id` 比对，`is_superuser` 仅存于保留的次层 has_project_access 分支（符合设计）。

## Current RED/GREEN Status

**新转 GREEN（本 plan 落地，#13-25）：** `test_cross_user_denied[#13..#25]`（coding-session #14-19、coding-plan #21-23、routing-trace #24、clarification #25）+ `test_list_scoping_coding`（#13/#20）。

**持续 GREEN（回归护栏）：** #1-12 全部、open-mode 回归、owner-allowed 主路径、backfill 3 条、admin-no-bypass、stream 前置 404、404-indistinguishable。

**全阶段隔离套件全绿：** 37/37 passed —— Phase 8 全 25 路径 cross-user-denied 达成，无 RED 残留。

## Decisions Made

- **两种 owner gate 风格按取数结构择优**：coding-session/plan 的 detail/action 端点已 `select_related("conversation")` 取关联行供后续逻辑使用，统一用 `created_by_id != user.id` 就地 fetch-then-check（`created_by_id` 不触发 async 惰性 FK）；list 型（#13/#20）用 `aget_for_user` owner-scoped 存在性，越权/不存在 → []。
- **#22 owner gate 主层先于 has_project_access**：owner-miss 必须先 404（不泄漏存在性，避免 403-vs-404 信息泄漏，T-08-13），既有 403 + superuser-bypass 分支保留为 null-owner/共享行次层。
- **#24/#25 去 superuser bypass**：旧实现 `if not is_superuser: has_project_access` 让管理员可越权操作他人会话下的 trace/clarification；本 plan 把 owner gate 前置为主层（`created_by_id` 比对、无 is_superuser），管理员越权同样 404（ISO-03），既有 has_project_access 降为次层不再 bypass owner gate。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Scan

无新增计划外安全面：本 plan 仅在既有 view 内插入 owner gate 接线，未引入新网络端点/认证路径/信任边界。威胁登记表 mitigate 项均已落地：T-08-12（#13-23 IDOR → 404/[]）、T-08-13（#22 403-vs-404 统一 404）、T-08-14（#24/#25 去除管理员 over-reach bypass）、T-08-15（select_related + created_by_id 避免 async 惰性 FK）。

## Known Stubs

None - 无占位/桩代码。Phase 8 全 25 路径 owner gate 全部落地。

## Issues Encountered

- 本 plan 为续接执行：Task 1（`1857f8f6`）/ Task 2（`c96d0170`）在前序会话已原子提交，Task 3 的 views.py 编辑已落工作区但未提交。本次续接先跑隔离套件验证（37 passed）确认 Task 3 实现正确，再原子提交 Task 3（`88263c45`，commit-msg hook 将信息规范化为中文），随后跑全量回归。无代码改动偏差。

## User Setup Required

None - 零新增依赖（纯 view 接线）。

## Next Phase Readiness

- Phase 8（对话/会话用户隔离）4/4 plan 全部完成，ISO-01/02/03/04 全达成；全 25 路径 cross-user-denied + list-scoping 隔离套件全绿。
- Phase 9（管理员会话管理后台，只读）可基于本阶段 owner 维度与隔离语义起步：管理员后台需绕开普通对话 owner 过滤做只读浏览，交互走既有 fork 路径并设 `created_by = 管理员`。

## Self-Check: PASSED

- FOUND: `.planning/phases/08-iso/08-04-SUMMARY.md`
- FOUND: `server/chat/views.py`（#13-25 owner gate 接线，`created_by_id` 比对 / `aget_for_user`）
- FOUND commits: `1857f8f6`, `c96d0170`, `88263c45`
- Verify: 隔离套件 37 passed（全 25 路径）；全量回归 63 passed + facade 10 passed 无回归；makemigrations --check clean；owner gate 段 0 处 is_superuser。

---
*Phase: 08-iso*
*Completed: 2026-06-09*
