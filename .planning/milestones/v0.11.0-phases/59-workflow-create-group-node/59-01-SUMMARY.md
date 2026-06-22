---
phase: 59-workflow-create-group-node
plan: 01
subsystem: integrations
tags: [feishu, im, create_chat, httpx, writeback, work_item, inv6]

# Dependency graph
requires:
  - phase: 28-work-item-spine
    provides: WorkItem canonical 模型 + WorkItemService 单一写入入口（INV-6）
  - phase: 58-cardkit
    provides: FeishuIMClient/Service 手写 httpx 范式（token/tenacity/code!=0）
provides:
  - "FeishuIMClient.create_chat（POST /im/v1/chats 建群即拉人单步，返回含 chat_id 的 data）"
  - "FeishuIMService.create_chat（同构委托）"
  - "WorkItemService.awriteback_feishu_chat_id（feishu_chat_id writeback 单一入口，INV-6/P-5）"
affects: [59-workflow-create-group-node Wave 2, feishu_chat, CreateGroupChatNode]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "建群即拉人单步 create_chat：手写 httpx 复用 get_tenant_access_token，body 仅放非空字段，对齐 add_bot_to_chat（仅 raise RateLimitError 不加 @retry）"
    - "writeback 单一入口 awriteback_feishu_chat_id：三元组定位 + save(update_fields) 只写 feishu_chat_id/updated_at，绝不进 mirror（P-5）"
    - "INV-6 grep 守护扩展 feishu_chat_id：旁路写禁止 + writer-actually-writes 正向有效性"

key-files:
  created:
    - server/tests/delivery/test_work_item_writeback.py
  modified:
    - server/services/feishu_im.py
    - server/delivery/services/work_item_service.py
    - server/tests/services/test_feishu_im.py
    - server/tests/delivery/test_inv6_guard.py

key-decisions:
  - "create_chat 不加 @retry 装饰器（NOTE-1，对齐 add_bot_to_chat），避免 rate-limit 单测真实 sleep"
  - "set_bot_manager 仅在 owner_id 非空且 set_bot_manager=True 时随 query 下发 set_bot_manager=true"
  - "awriteback WorkItem 不存在返回 False 不抛（fail-soft 由调用方判定）；DB 异常不吞（调用方 fail-soft 捕获）"
  - "INV-6 feishu_chat_id 守护复用 _is_scanned_for_inv6 剪枝（排除 tests/migrations/models 与唯一 writer）"

patterns-established:
  - "writeback 字段写入路径独立于 mirror sync——绝不进 _MIRROR_FIELDS / _refresh_mirror（否则被 sync 覆盖回空）"

requirements-completed: [GROUP-01]

# Metrics
duration: 4 min
completed: 2026-06-17
---

# Phase 59 Plan 01: 建群封装 + writeback 入口 Summary

**FeishuIMClient/Service.create_chat 单步建群即拉人（POST /im/v1/chats）+ WorkItemService.awriteback_feishu_chat_id（feishu_chat_id writeback 单一入口，INV-6/P-5 不污染 mirror）**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-17T13:13:50Z
- **Completed:** 2026-06-17T13:18:13Z
- **Tasks:** 2
- **Files modified:** 4 (+1 created)

## Accomplishments
- `FeishuIMClient.create_chat`：一次 `POST /im/v1/chats` 完成建群 + 拉人（`user_id_list`≤50 + `bot_id_list`≤5），query `user_id_type` 默认 open_id，body 仅放非空字段；手写 httpx 复用 `get_tenant_access_token`，对齐 `add_bot_to_chat`（仅 raise `RateLimitError`，不加 `@retry`）；`code!=0 → FeishuIMError`、`99991400 → RateLimitError`、成功取 `data`（含 chat_id）。
- `FeishuIMService.create_chat`：同构透传委托。
- `WorkItemService.awriteback_feishu_chat_id`：三元组定位 WorkItem + `save(update_fields=["feishu_chat_id","updated_at"])`，不存在返回 `False`；`@sync_to_async` 包同步块；`feishu_chat_id` 绝不进 `_MIRROR_FIELDS` / `_refresh_mirror`（P-5）。
- 测试：扩展 `test_feishu_im.py` 6 例 create_chat httpx 形状单测；新建 `test_work_item_writeback.py` 3 例（写入 + 不污染 mirror + 不存在返回 False）；扩展 `test_inv6_guard.py` 2 例 feishu_chat_id grep 守护。

## Task Commits

1. **Task 1: create_chat（Client + Service 委托）+ httpx 形状单测** - `3003bb73e` (feat)
2. **Task 2: awriteback_feishu_chat_id + DB 单测 + INV-6 grep 守护** - `e331402a9` (feat)

## Files Created/Modified
- `server/services/feishu_im.py` - 新增 `FeishuIMClient.create_chat` + `FeishuIMService.create_chat` 委托（+105 行，纯新增）
- `server/delivery/services/work_item_service.py` - 新增 `awriteback_feishu_chat_id` + `_writeback_feishu_chat_id_sync`（+66 行，纯新增）
- `server/tests/services/test_feishu_im.py` - +6 例 create_chat 形状单测
- `server/tests/delivery/test_work_item_writeback.py` - 新建，3 例 writeback DB 测
- `server/tests/delivery/test_inv6_guard.py` - +2 例 feishu_chat_id 写入守护

## Decisions Made
- create_chat 不加 `@retry`（NOTE-1）——对齐 `add_bot_to_chat`，避免 rate-limit 单测真实 sleep。
- `set_bot_manager` 仅当 `owner_id` 非空且 `set_bot_manager=True` 时随 query 下发。
- awriteback WorkItem 不存在返回 False 不抛（fail-soft 留给调用方），DB 异常不吞。
- INV-6 feishu_chat_id 守护正则 `\.feishu_chat_id\s*=\s*[^=]`（排除比较运算），复用既有 `_is_scanned_for_inv6` 剪枝。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 1 封装层 + writeback 入口齐备：`FeishuIMService.create_chat` + `WorkItemService.awriteback_feishu_chat_id` 已就绪。
- Ready for 59-02（Wave 2）：在 `server/workflows/nodes/integrations/feishu_chat.py` 新增 `CreateGroupChatNode` 接线消费 create_chat 建群 + 可选 writeback。
- 零回归：`add_bot_to_chat`/`ensure_bot_in_chat`/`get_chat_members`/`_refresh_mirror`/`_MIRROR_FIELDS`/`upsert` 逐字不变（diff 纯新增）。

## Self-Check: PASSED
- create_chat httpx 形状单测通过（端点 `/im/v1/chats` / params user_id_type / body 仅非空字段 / code!=0→FeishuIMError / 99991400→RateLimitError / 取 chat_id）。
- awriteback_feishu_chat_id 单测通过（写入 + 不污染 mirror title + WorkItem 不存在返回 False）。
- INV-6 grep 守护通过（feishu_chat_id 仅 work_item_service.py 写 + writer-actually-writes）。
- 既有方法符号 git diff 纯新增（feishu_im.py 105 insertions / work_item_service.py 66 insertions，0 deletions）。
- `cd server && uv run pytest tests/services/test_feishu_im.py tests/delivery/ -q` → **411 passed**（零回归）。

---
*Phase: 59-workflow-create-group-node*
*Completed: 2026-06-17*
