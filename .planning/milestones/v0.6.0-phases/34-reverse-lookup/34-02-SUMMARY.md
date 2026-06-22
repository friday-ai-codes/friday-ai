---
phase: 34-reverse-lookup
plan: 02
subsystem: knowledge
tags: [reverse-lookup, comment-projection, knowledge-graph, rag, hash-no-version, degradation, inv-3]

# Dependency graph
requires:
  - phase: 28-work-item
    provides: canonical WorkItem 三元组 + WorkItemService
  - phase: 29-comment-events
    provides: WorkItemCommentEvent 事实源 + project_comment_tree/aproject_comment_tree 投影 + CommentEventService 单一写入入口
  - phase: 30-feishu-doc
    provides: feishu_work_item normalizer + ingestion hash-no-version 范式
  - phase: 13-ingestion
    provides: aschedule_ingestion 触发入口（on_commit + 后台 + 异常全吞）
provides:
  - feishu_work_item 投影 content 增 `## 评论` 段（评论入图，复用 project_comment_tree）
  - 评论事件新增 → best-effort 触发 work_item 重投影（评论进入快照）
affects: [35-vision, v0.7-comment-trigger]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "评论入图采用 enrich work_item 投影：评论树文本并入既有 work_item 知识实体（不新增 EntityKind）"
    - "确定性渲染评论段保证评论无变化时 content 逐字一致（hash-no-version）"
    - "评论事件→重投影触发经惰性 import 规避 delivery→knowledge 循环依赖；best-effort 不阻塞落库"

key-files:
  created:
    - server/tests/knowledge/test_feishu_work_item_comments.py
    - server/tests/knowledge/test_comment_reprojection.py
  modified:
    - server/knowledge/sources/feishu_work_item.py
    - server/delivery/services/comment_event_service.py

key-decisions:
  - "评论段追加在 sections 末尾（PRD/技术方案/关联工作项之后），最小化对既有快照 diff"
  - "渲染格式 `- {author}（已删除）: {body}`，子回复缩进两空格；空树不渲染空段"
  - "payload 增 comment_count 元数据（不进 content，不影响 hash-no-version）"
  - "触发仅在 created_count>0 时（幂等重摄不打扰），外层再裹 try/except 防御惰性 import 异常"

patterns-established:
  - "缺料降级缺段不缺实体：无 delivery WorkItem / 无评论 / 投影异常 → 快照缺评论段 + warning，不抛不回滚"

requirements-completed: [RREF-02]

# Metrics
duration: 18min
completed: 2026-06-15
---

# Phase 34 Plan 02: 评论入图（comments into work_item knowledge projection）Summary

**把 Phase 29 `project_comment_tree(work_item)` 投影出的当前评论树文本并入 `feishu_work_item` 知识实体的投影内容（`## 评论` 段），并在评论事件流新增后 best-effort 触发 work_item 重投影——使评论经既有检索召回且天然关联到 WorkItem，不新增 EntityKind、无新 model、无 migration。**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-15
- **Tasks:** 2
- **Files modified:** 4 (2 created tests, 2 modified src)

## Accomplishments

- `feishu_work_item.normalize` 在 sections 拼接末尾追加 `## 评论` 段：经新增私有 helper `_resolve_work_item`（三元组解析 delivery WorkItem，int 失败 → None）+ `aproject_comment_tree`（Phase 29 async 投影）取评论树，经确定性渲染 helper `_render_comment_section` 拍平为 markdown 并入 content。
- 降级纪律：无 delivery WorkItem / 无评论 / 投影异常 → 整段 try/except 吞为 warning `knowledge_normalize_comments_unavailable`，content 不含评论段、事件照常产出（缺段不缺实体），绝不抛、绝不回滚。
- hash-no-version 守护：渲染严格按 `project_comment_tree` 既有排序（不重排），评论无变化时 content 逐字一致 → content_hash 相等 → 不翻版本。
- `CommentEventService.append_events` 末尾 `created_count>0` 时 best-effort 触发 work_item 重投影：构造 `IngestionRequest(source_kind="feishu_work_item", source_id=triple, trigger="comment_event_appended")` 调 `aschedule_ingestion`；惰性 import 规避循环依赖，`created_count==0`（幂等重摄）不触发。
- 8 个守护用例全绿（5 Task1 + 3 Task2），覆盖评论树折叠入 content + 可召回 + 关联 work_item、缺料降级、空树不渲染、hash-no-version 一致性、deleted 占位、触发 + 幂等不重复触发 + 端到端快照含评论文本。

## Task Commits

1. **Task 1: feishu_work_item 投影并入当前评论树段（TDD）** - `a0f13418` (feat)
2. **Task 2: 评论事件→work_item 重投影触发 + 检索召回端到端守护** - `bac5ec11` (feat)

## Files Created/Modified

- `server/knowledge/sources/feishu_work_item.py` - 新增 `_resolve_work_item` / `_render_comment_section` / `_count_comment_nodes` helper；normalize 追加评论段（降级 try/except）+ payload `comment_count`。
- `server/delivery/services/comment_event_service.py` - `append_events` 末尾触发重投影；新增 `_schedule_work_item_reprojection`（惰性 import + best-effort + warning 降级）。
- `server/tests/knowledge/test_feishu_work_item_comments.py` - 5 个评论入图守护用例。
- `server/tests/knowledge/test_comment_reprojection.py` - 3 个触发 + 幂等 + 端到端召回守护用例。

## Decisions Made

- 评论段追加在既有 sections 末尾（不改既有段顺序），最小化对既有 work_item 快照的 diff，且 `feishu_document.py` 复用 `feishu_work_item.normalize` 不破裂（INV-3）。
- `deleted` 节点以 `（已删除）` 占位保留并维持线程结构（body 取 `project_comment_tree` 折叠出的最新值）。
- 触发点放在 async `append_events`（非 sync `_append_events_sync`），因 `aschedule_ingestion` 是 async + `transaction.on_commit`；`created_count>0` 门控避免幂等重摄无谓重投影（T-34B-02 mitigate）。

## Deviations from Plan

None - plan executed exactly as written.

（Task 1 为 tdd 任务，遵循本仓库既有惯例 test 与 impl 同一原子提交。）

## Threat Mitigations Verified

- **T-34B-02 (DoS, mitigate):** 仅 `created_count>0` 触发；`aschedule_ingestion` on_commit + 后台 + 异常全吞，hash 相等不翻版本（专测 `test_idempotent_append_no_retrigger` + `test_content_deterministic_across_normalize`）。
- **T-34B-03 (Tampering, mitigate):** 评论入图为读时投影（`project_comment_tree` 不写事件行），事实源仍是 append-only `WorkItemCommentEvent`。
- **T-34B-04 (Availability/降级, mitigate):** 无 WorkItem/无评论/投影异常 → 缺段 + warning，不抛不回滚（专测 `test_no_work_item_no_comment_section` + `test_work_item_without_comments_no_section`）。

## Verification Results

- `tests/knowledge/test_feishu_work_item_comments.py tests/knowledge/test_comment_reprojection.py` — 8 passed。
- 回归 `tests/delivery tests/knowledge` — 506 passed, 1 deselected；唯一失败为预存且与本 plan 无关的 `tests/knowledge/test_triggers.py::test_coding_chat_pr_created_branch_delivers_once`（按指示忽略）。
- `ruff check knowledge/sources/feishu_work_item.py delivery/services/comment_event_service.py` — All checks passed（仅对所改文件）。
- grep 守护 `grep -cE 'class EntityKind|= "comment"' knowledge/models.py` == 1（仅 EntityKind class，无 comment 枚举，locked 集合保持）。

## Known Stubs

None.

## Self-Check: PASSED

- 创建文件均存在（2 test files）+ 修改文件已落 commit。
- 提交 `a0f13418` / `bac5ec11` 均在 git log。
- 8 新测试全绿；回归仅预存无关失败；ruff 对所改文件全过；grep 守护 == 1（无新 EntityKind）。

---
*Phase: 34-reverse-lookup*
*Completed: 2026-06-15*
