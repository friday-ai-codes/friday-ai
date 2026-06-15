---
phase: 29-comment-events
plan: 01
subsystem: database
tags: [django, delivery, comment-event, append-only, models, migration, uuid, pytest-django]

# Dependency graph
requires:
  - phase: 28-workitem-spine
    provides: canonical WorkItem 模型（delivery app + 三元组身份），CommentEvent FK 关联其上
provides:
  - append-only WorkItemCommentEvent 模型（DOMAIN §12.4 逐字段对齐）
  - CommentEventType 枚举（created/replied/edited/deleted/approval）
  - ApprovalSemantic 枚举（none/approve/reject，默认 none）
  - delivery 0002 migration（已 migrate，建出 delivery_work_item_comment_event 表 + (work_item, event_time) 索引）
affects: [29-02 CommentEventService append 入口, 29-03 INV-6 grep 守护, 34 评论入图/反查, v0.7 评论触发方案再生成]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "append-only 事件流模型：编辑/删除作为新事件行，模型层无就地改写方法（CMT-02）"
    - "事件模型范式沿用 status_event：UUID pk、work_item FK CASCADE、event_time/ingested_at、(work_item, event_time) 索引"
    - "edited/deleted 留枚举占位 deferred（飞书 webhook/API 暂无对应信号，CONTEXT Grey Area 3）"

key-files:
  created:
    - server/delivery/models/comment_event.py
    - server/delivery/migrations/0002_workitemcommentevent.py
    - server/tests/delivery/test_comment_event_models.py
  modified:
    - server/delivery/models/__init__.py

key-decisions:
  - "本 plan 只建表 + 枚举，模型层无 create/save 业务逻辑（落库归 29-02 CommentEventService 单一入口，守 INV-6 精神）"
  - "append-only 体现在「编辑/删除作为新事件行」由 service 保证，模型不含就地改写方法（T-29-01 由模型单测守护两行并存）"
  - "edited/deleted 为枚举占位：飞书信号不可得时本 phase 仅实际落 created/replied/approval，留位 deferred"

patterns-established:
  - "comment_event 复用 status_event 的 append-only 事件模型范式（UUID pk + work_item CASCADE + event_time/ingested_at + (work_item, event_time) 索引）"

requirements-completed: [CMT-01, CMT-02]

# Metrics
duration: ~8min
completed: 2026-06-15
---

# Phase 29 Plan 01: WorkItemCommentEvent 数据层 Summary

**新增 append-only `WorkItemCommentEvent` 模型 + 两枚举（CommentEventType / ApprovalSemantic），逐字段对齐 DOMAIN §12.4，0002 迁移已应用建出 `delivery_work_item_comment_event` 表（含 (work_item, event_time) 索引），模型层 5 个单测守护 append-only / 默认值 / CASCADE / 索引全绿。**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-06-15
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- 新建 `server/delivery/models/comment_event.py`：`WorkItemCommentEvent` 逐字段对齐 DOMAIN §12.4（work_item FK CASCADE / feishu_comment_id / thread_parent_id / event_type 五值 / author / body / attachments / approval_semantic 三值默认 none / event_time / ingested_at），含 `(work_item, event_time)` 索引；模型层无 create/save/就地改写业务方法（守 INV-6 精神）。
- 两枚举 `CommentEventType`（created/replied/edited/deleted/approval）+ `ApprovalSemantic`（none/approve/reject），中文 label；edited/deleted docstring 标注 deferred 占位。
- `models/__init__.py` curated re-export 追加三项并加入 `__all__`。
- `0002_workitemcommentevent` 迁移生成并 `migrate`，DB 实际建出 `delivery_work_item_comment_event` 表；`makemigrations --check` 干净。
- 模型单测覆盖：五种 event_type / 三种 approval_semantic 读回 + 默认值（attachments=[]、approval_semantic=none）、append-only 编辑作为新行两行并存（旧行 body 未改写、event_time 可区分）、work_item CASCADE 删除、(work_item, event_time) 索引存在——5 passed，无真实网络。

## Task Commits

1. **Task 1: WorkItemCommentEvent 模型 + 枚举** - `2f7298c7` (feat)
2. **Task 2 [BLOCKING]: 生成并应用 migration + 模型层单测** - `f0586857` (feat)

## Files Created/Modified
- `server/delivery/models/comment_event.py` - `WorkItemCommentEvent` + `CommentEventType` + `ApprovalSemantic`
- `server/delivery/models/__init__.py` - 追加三项 re-export + `__all__`
- `server/delivery/migrations/0002_workitemcommentevent.py` - 建表迁移（含 (work_item, event_time) 索引，依赖 0001_initial）
- `server/tests/delivery/test_comment_event_models.py` - 5 个模型层单测

## Decisions Made
- 本 plan 只建表 + 枚举，模型层不写任何落库业务逻辑——append-only 写入唯一收口归 29-02 `CommentEventService`（守 INV-6 精神）。
- append-only（T-29-01 Repudiation 缓解）由「编辑/删除作为新事件行 + event_time/ingested_at 留痕」体现，模型不含就地改写方法，模型单测守护同一 feishu_comment_id 的 created/edited 两行并存且旧行不被改写。
- edited/deleted 为枚举占位：若飞书 webhook/API 不提供编辑/删除信号，本 phase 仅实际落 created/replied/approval，留位 deferred（CONTEXT Grey Area 3）。

## Deviations from Plan
None - plan executed exactly as written.

（注：自动生成的 `0002_workitemcommentevent.py` 触发 ruff I001 + 格式未规范，已用 `ruff check --fix` + `ruff format` 规范化——属生成产物格式收尾，非计划偏离。）

## Issues Encountered
None.

## Verification Results
- `makemigrations delivery --check --dry-run` → No changes detected（迁移已就绪、干净）。
- `migrate delivery` → `Applying delivery.0002_workitemcommentevent... OK`；DB introspection 确认 `delivery_work_item_comment_event` 表存在。
- `pytest tests/delivery/test_comment_event_models.py -x -q` → **5 passed**；`pytest tests/delivery/ -q` → **45 passed**（无 28 套件回归）。
- `ruff format --check` + `ruff check` 对新增/迁移文件 → all clean。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 表结构 + 枚举就位，29-02 可在其上实现 `CommentEventService` append-only 摄取入口（复用 Phase 27 get_comments/parse_comments + Phase 28 SyncState comments facet）。
- 29-03 INV-6 grep 守护可锚定「评论事件落库只经 service 入口」。
- 下游 Phase 34（评论入图/反查）+ v0.7（approval 事件触发方案再生成）可消费本事件流。

## Self-Check: PASSED
- FOUND: server/delivery/models/comment_event.py
- FOUND: server/delivery/migrations/0002_workitemcommentevent.py
- FOUND: server/tests/delivery/test_comment_event_models.py
- FOUND: commit 2f7298c7
- FOUND: commit f0586857

---
*Phase: 29-comment-events*
*Completed: 2026-06-15*
