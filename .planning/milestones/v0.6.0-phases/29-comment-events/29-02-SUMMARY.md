---
phase: 29-comment-events
plan: 02
subsystem: delivery-service
tags: [django, delivery, comment-event, append-only, idempotent, projection, approval, sync-to-async, respx, pytest-django]

# Dependency graph
requires:
  - phase: 29-comment-events (plan 01)
    provides: WorkItemCommentEvent 模型 + CommentEventType/ApprovalSemantic 枚举 + 去重锚字段
  - phase: 28-workitem-spine
    provides: WorkItem 三元组身份 + WorkItemSyncState(facet) + WorkItemService 范式（sync_to_async/_redact_secrets/_safe_error）
  - phase: 27
    provides: services.feishu.get_comments + services.feishu_parsing.parse_comments（不重写解析）
provides:
  - CommentEventService.append_events 评论事件落库唯一写入入口（INV-6 精神，幂等去重）
  - CommentEventService.ingest_comments 拉取式摄取路径（复用 Phase 27，SyncState comments facet，降配不回滚）
  - CommentEventService.append_webhook_comment webhook 接线路径（29-03 调用）
  - classify_approval_semantic 审批语义单一判定来源（approve/reject/none，reject 优先）
  - project_comment_tree / aproject_comment_tree 当前评论树读时投影（线程/编辑/删除/排序）
affects: [29-03 webhook 接线 + INV-6 grep 守护 + 评论树 REST 端点, 32 ING 拉取编排, 34 评论入图/反查, v0.7 approval 触发再生成]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "评论事件落库单一写入收口 append_events（INV-6 精神），ingest/webhook 路径皆收敛于此"
    - "去重锚 (work_item, feishu_comment_id, event_type, event_time) get_or_create 幂等可重入（T-29-03）"
    - "approval 关键词抽成纯函数 classify_approval_semantic 单一来源（与 webhook 共用，reject 优先）"
    - "当前评论树 = 对事件流的读时投影（查询/视图，非事实表），绝不就地改写事件行（CMT-02）"
    - "拉取失败按 facet 记 SyncState(comments)=missing/error，不抛不回滚（WIT-03 范式）"

key-files:
  created:
    - server/delivery/services/comment_event_service.py
    - server/delivery/services/comment_projection.py
    - server/tests/delivery/test_comment_event_service.py
    - server/tests/delivery/test_comment_projection.py
  modified:
    - server/delivery/services/__init__.py

key-decisions:
  - "评论事件落库唯一收口为 append_events；ingest_comments / append_webhook_comment 归一后皆调它（INV-6 精神）"
  - "ingest 复用 get_comments（内部已 parse_comments，不重写）；网络/客户端层异常 → missing/error，err_code≠0/非 JSON 经 get_comments fail-soft 返回 [] → complete-empty"
  - "投影 deleted 节点保留占位（is_deleted=True）维持线程结构，body 保留最新非空供追溯（Claude's Discretion）"
  - "提供 sync project_comment_tree + sync_to_async 包装 aproject_comment_tree，供异步/REST 调用方二选一"

patterns-established:
  - "CommentEventService 独立 service（非并入 WorkItemService），与 WorkItemService 同范式复用 _redact_secrets/_safe_error/_parse_ms 思路"

requirements-completed: [CMT-01, CMT-02]

# Metrics
duration: ~18min
completed: 2026-06-15
---

# Phase 29 Plan 02: 评论事件流 service + projection Summary

**实现评论事件流服务层：`CommentEventService.append_events` 作为评论落库唯一写入收口（去重锚 get_or_create 幂等可重入），`ingest_comments` 复用 Phase 27 get_comments 拉取摄取（缺 project/work_item/回源失败降配 SyncState comments facet，不抛不回滚），`append_webhook_comment` 接线路径，`classify_approval_semantic` 审批语义单一判定（reject 优先），`project_comment_tree` 从事件流读时投影当前评论树（线程层级 + 编辑取最新 + 删除标记 + event_time 排序，绝不改事件行）——33 个守护测试全绿，无回归。**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-15
- **Tasks:** 2
- **Files created/modified:** 5

## Accomplishments

### Task 1 — append 单一入口 + 幂等去重 + approval 判定
- 新建 `comment_event_service.py`：`CommentEventService` async-first，ORM 经 `sync_to_async`（沿用 work_item_service 范式）。
- `classify_approval_semantic(text)` 纯函数：把 webhook `_handle_workitem_comment` 关键词识别抽成单一判定来源（approval=通过/批准/approved/lgtm/ok/👍，rejection=驳回/拒绝/rejected/需要修改/不通过/👎），**同时命中 reject 优先**，空/None → none。
- `append_events(work_item, comments, source)`：**评论事件落库唯一写入收口**。event_type 推导（approval_semantic≠none → approval；有 thread_parent → replied；否则 created），去重锚 `(work_item, feishu_comment_id, event_type, event_time)` 经 `get_or_create` 幂等；缺 feishu_comment_id 跳过 + warning；attachments 缺省 `[]` 不臆造。
- `ingest_comments(identity, source)`：拉取路径复用 Phase 27 `get_comments`（**不重写解析**）；缺 project → comments facet=missing(error=project_unconfigured)；回源异常 → `_safe_error` 脱敏 + facet=missing/error，**不回滚 WorkItem**（WIT-03）；缺 canonical work_item → 跳过 append + warning；成功（含空列表）→ facet=complete。
- `append_webhook_comment(...)`：单条 webhook 评论归一成 append_events dict 调用；缺 work_item → warning 返回 0（不建 WorkItem）。
- 凭证脱敏复用 work_item_service `_redact_secrets`/`_ERROR_SNIPPET_LIMIT`（单一来源，T-29-05）；comment body 属业务内容不脱敏。
- `services/__init__.py` re-export `CommentEventService` / `classify_approval_semantic`，更新 `__all__`。

### Task 2 — 当前评论树读时投影
- 新建 `comment_projection.py`：`project_comment_tree(work_item) -> list[dict]`，从事件流**读时计算**当前评论树（查询/视图，非事实表，绝不写库/改事件行，CMT-02）。
- 折叠规则：按 event_time 升序（None 末尾，稳定保 ingested 序）→ 按 feishu_comment_id 归并 → body 取最新（含 edited 取最新 body）、event_type/event_time 取最新、approval_semantic 取最新非 none、deleted 标 `is_deleted=True` 保留占位；按 thread_parent_id 组装线程层级（父不在集合内提升为根）；同层递归按 event_time 升序。
- 节点 dict 形状：`feishu_comment_id / author / body / event_type / approval_semantic / is_deleted / event_time / thread_parent_id / children`。
- 提供 `aproject_comment_tree = sync_to_async(project_comment_tree)` 供异步/REST 调用方使用；`__init__.py` re-export 两者。

## Task Commits

1. **Task 1: append 单一入口 + 幂等去重 + approval 判定** - `28aa254a` (feat)
2. **Task 2: project_comment_tree 读时投影** - `b83b3b75` (feat)

## Files Created/Modified
- `server/delivery/services/comment_event_service.py` - `CommentEventService` + `classify_approval_semantic`
- `server/delivery/services/comment_projection.py` - `project_comment_tree` + `aproject_comment_tree`
- `server/delivery/services/__init__.py` - 追加 4 项 re-export + `__all__`
- `server/tests/delivery/test_comment_event_service.py` - 25 个服务守护测试（approval 分类/event_type/幂等/ingest 降配/webhook）
- `server/tests/delivery/test_comment_projection.py` - 8 个投影守护测试（线程/编辑/删除/排序/只读）

## Decisions Made
- **CommentEventService 独立 service**（非并入 WorkItemService）：评论事件与 WorkItem mirror 写入关注点不同，独立 service 更清晰；复用 work_item_service 的 `_redact_secrets`/`_safe_error`/`_parse_ms` 思路（import 单一来源脱敏，T-29-05）。
- **ingest 失败判定边界**：`get_comments` 对非 JSON / err_code≠0 已 fail-soft 返回 `[]`（视作 complete-empty，Phase 27 契约），`ingest_comments` 只把**网络/客户端层异常**（如 ConnectError）降配为 missing/error。测试以 `respx side_effect=ConnectError` 验证降配路径。
- **deleted 节点保留占位**（is_deleted=True）维持线程结构而非剔除（per CONTEXT Claude's Discretion）；body 保留最新非空供追溯。
- **投影 async 二选一**：同时提供同步 `project_comment_tree`（纯查询）+ `aproject_comment_tree`（sync_to_async 包装），调用方按场景选用，docstring 注明。

## Deviations from Plan
None - plan executed exactly as written.

（注：新增 4 文件触发 ruff format 规范化（行宽/换行），已 `ruff format` + `ruff check --fix` 收尾——属格式收尾，非计划偏离。）

## Issues Encountered
None.

## Verification Results
- `pytest tests/delivery/test_comment_event_service.py -x -q` → **25 passed**。
- `pytest tests/delivery/test_comment_projection.py -x -q` → **8 passed**。
- `pytest tests/delivery/ -q` → **78 passed**（无 28 / 29-01 套件回归；全程 respx mock get_comments + pytest-socket 零真实网络）。
- `ruff format --check delivery/services/ <两测试文件>` + `ruff check delivery/ tests/delivery/` → all checks passed。
- 未改 knowledge app（INV-3）；未新增第三方依赖。

## Threat Mitigations Verified
- **T-29-03（DoS 重复摄取）**：去重锚 get_or_create 幂等，`test_append_events_idempotent_dedup` 守护（同批两次新建 2 → 0）。
- **T-29-04（Tampering append-only 收口）**：评论落库仅经 `append_events`，ingest/webhook 路径皆收敛于此（旁路写表 grep 守护留待 29-03）。
- **T-29-05（信息泄露 SyncState.error）**：回源失败经 `_safe_error`（复用 `_redact_secrets`）脱敏，`test_ingest_comments_fetch_failure_*` 断言凭证不入 error。
- **T-29-06（DoS 回源失败掀翻 WorkItem）**：`ingest_comments` try/except + facet=missing/error 不抛不回滚，`test_ingest_comments_fetch_failure_facet_missing_no_rollback` 守护 WorkItem 行保留。

## Known Stubs
None - 服务层与投影均已接通真实数据流（ingest 复用 Phase 27 get_comments；webhook 接线点本 plan 提供入口，实际 webhook 调用在 29-03 接入）。

## User Setup Required
None - no external service configuration required（真实飞书评论端点正确性 PF-11 仍依赖真实凭证 human-UAT，per CONTEXT）。

## Next Phase Readiness
- 29-03 可调 `append_webhook_comment` 在 `_handle_workitem_comment` 追加后台 append、用 `project_comment_tree` 实现评论树 REST 只读端点、并加 INV-6 grep 守护（评论落库只经 service 入口）。
- Phase 32 ING 可调 `ingest_comments` 按 work item 拉评论入库。
- approval 事件边界（approval_semantic）已就位，供 v0.7 评论触发方案再生成消费。

## Self-Check: PASSED
- FOUND: server/delivery/services/comment_event_service.py
- FOUND: server/delivery/services/comment_projection.py
- FOUND: server/tests/delivery/test_comment_event_service.py
- FOUND: server/tests/delivery/test_comment_projection.py
- FOUND: commit 28aa254a
- FOUND: commit b83b3b75

---
*Phase: 29-comment-events*
*Completed: 2026-06-15*
