---
phase: 63-deploy
plan: 03
subsystem: infra
tags: [idempotency, fencing, gitlab, github, feishu, merge-request, dedup]

# Dependency graph
requires:
  - phase: 59
    provides: WorkItem.feishu_chat_id writeback 字段 + awriteback_feishu_chat_id 入口
  - phase: 46
    provides: AICodingNode._create_mr_for_repo + git platform client 抽象
provides:
  - git 平台 client 新增 find_open_merge_request（GitLab/GitHub 双实现 + base 默认 None）
  - coding _create_mr_for_repo 创建前 existing-MR fence（命中复用不重复开 PR）
  - WorkItemService.aget_feishu_chat_id 读访问器（建群前 fence 查询）
  - CreateGroupChatNode 建群前 feishu_chat_id fence（命中复用既有群）
affects: [idempotency, delivery, workflows, git-platform]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "reuse-first fencing：外部副作用创建前查既有资源，命中复用，无 outbox 表"
    - "fence 查询全 fail-soft：异常/None → 照常创建，绝不阻断主动作（fail-open）"
    - "新增能力用非抽象默认方法（return None）而非 @abstractmethod，避免破坏既有子类实例化"

key-files:
  created:
    - server/tests/workflows/test_coding_mr_dedup.py
  modified:
    - server/services/git_platform/base.py
    - server/services/git_platform/gitlab_client.py
    - server/services/git_platform/github_client.py
    - server/workflows/nodes/ai/coding.py
    - server/delivery/services/work_item_service.py
    - server/workflows/nodes/integrations/feishu_chat.py
    - server/tests/workflows/test_chat_nodes.py
    - server/tests/workflows/test_coding_pr_target_branch.py

key-decisions:
  - "find_open_merge_request 设为 base 带默认 return None 的普通 async 方法，非 @abstractmethod，零回归保既有实例化"
  - "GitLab 用 state=\"opened\"、GitHub 用 state=\"open\" + head=f\"{owner}:{branch}\"（平台差异）"
  - "建群 fence 仅在 project_key + 可解析 work_item_id 齐备时触发；无锚则退化 no-op 照常建群"
  - "work_item 锚解析上移，fence 与 writeback 复用同一组解析值"

patterns-established:
  - "reuse-first fence：create 前 find existing → 命中复用、未命中创建、异常 fail-soft"

requirements-completed: [IDEMP-02]

# Metrics
duration: 12 min
completed: 2026-06-21
---

# Phase 63 Plan 03: 外部副作用 reuse-first fencing Summary

**给 MR/PR 创建与飞书建群上 reuse-first 幂等围栏：创建前查既有 open MR / WorkItem.feishu_chat_id，命中即复用不重复执行，无 outbox 表，全程 fail-soft。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-21T02:09 (UTC+8)
- **Completed:** 2026-06-21
- **Tasks:** 3
- **Files modified:** 8（含 1 新建）

## Accomplishments
- git 平台 client（GitLab/GitHub）新增 `find_open_merge_request(source, target)` 能力，base 提供默认 `return None`（OQ4：原无此方法，零回归扩展）
- `AICodingNode._create_mr_for_repo` 创建前查既有 open MR/PR，命中复用 mr_url/mr_id 不重复开 PR（带 `deduplicated` 标记，保留 description 供 PR-02 cross-ref）
- `WorkItemService.aget_feishu_chat_id` 读访问器（@sync_to_async，仅读不触 mirror），与 `awriteback_feishu_chat_id` 对称
- `CreateGroupChatNode` 建群前查 `WorkItem.feishu_chat_id`，命中复用既有群跳过 `create_chat`
- 守护测试：MR fence reuse/create/fail-soft 三例 + 建群 fence fenced/no-anchor/fail-soft 三例

## Task Commits

1. **Task 1: git 平台 client 新增 find_open_merge_request** - `b5cf8389f` (feat)
2. **Task 2: coding _create_mr_for_repo 创建前 existing-MR fence** - `6115e2507` (feat)
3. **Task 3: 建群前置 feishu_chat_id fence + WorkItemService 读访问器** - `0c141e744` (feat)

## Files Created/Modified
- `server/services/git_platform/base.py` - 新增 `find_open_merge_request` 默认方法（return None，非抽象）
- `server/services/git_platform/gitlab_client.py` - `mergerequests.list(source/target, state="opened")` 实现，命中复用，异常 fail-soft
- `server/services/git_platform/github_client.py` - `get_pulls(head="owner:source", base=target, state="open")` 实现，命中复用，异常 fail-soft
- `server/workflows/nodes/ai/coding.py` - `_create_mr_for_repo` 创建前 fence，命中复用返回 deduplicated 结果
- `server/delivery/services/work_item_service.py` - 新增 `aget_feishu_chat_id` + `_get_feishu_chat_id_sync`
- `server/workflows/nodes/integrations/feishu_chat.py` - 建群前 fence + work_item 锚解析上移复用
- `server/tests/workflows/test_coding_mr_dedup.py` - 新建，MR fence 守护（reuse/create/fail-soft）
- `server/tests/workflows/test_chat_nodes.py` - 扩展建群 fence 守护（fenced/no-anchor/fail-soft）
- `server/tests/workflows/test_coding_pr_target_branch.py` - `_make_client` 桩 `find_open_merge_request=None`（见 Deviations）

## Decisions Made
- `find_open_merge_request` 用 base 默认 `return None` 而非 `@abstractmethod`：新增抽象方法会让所有既有子类实例化抛 TypeError，破坏既有调用方；默认方法让未覆盖实现自然退化为"查不到 → 照常创建"。
- 平台差异：GitLab `state="opened"`、GitHub `state="open"` + `head=f"{owner}:{branch}"`。
- 建群 fence 仅在 work_item 锚齐备（project_key + 可解析 work_item_id）时触发；无锚退化 no-op，与既有 writeback fail-soft 锚一致。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] test_coding_pr_target_branch.py 的 _make_client 桩 find_open_merge_request=None**
- **Found during:** Task 2（coding MR fence）
- **Issue:** 既有 `test_coding_pr_target_branch.py` 的 `_make_client` 用裸 `AsyncMock()`，其自动桩的 `find_open_merge_request` 返回真值 mock（`.success` 亦真值），被新 fence 误判为命中既有 MR → 跳过 `create_merge_request`，导致 3 个既有 target_branch 断言失败。
- **Fix:** 在该 helper 显式设 `client.find_open_merge_request = AsyncMock(return_value=None)`，使既有用例确定走创建路径。仅改 helper，未动任何断言/用例语义。
- **Files modified:** server/tests/workflows/test_coding_pr_target_branch.py
- **Verification:** `pytest tests/workflows/test_coding_pr_target_branch.py` 4 例全绿
- **Committed in:** `6115e2507`（Task 2 commit）

---

**Total deviations:** 1 auto-fixed（1 blocking）
**Impact on plan:** 修复为 fence 注入直接副作用，属测试桩补全，无生产逻辑变更，无 scope creep。

## Issues Encountered
None — 计划逐任务执行。

## Verification Results
- `pytest tests/durable tests/delivery tests/workflows/{test_coding_mr_dedup,test_chat_nodes,test_coding_pr_target_branch}.py -q` → **536 passed, 1 failed**，唯一失败为 `tests/delivery/test_plan_session_inv6_guard.py::test_inv6_no_bypass_plan_session_write`（已知 pre-existing 失败，与本 plan 无关）。
- `python manage.py check` → **System check identified no issues (0 silenced)**。
- 真实 GitLab/GitHub 重复 MR 抑制 / 真实建群去重 → human_needed（需真实平台 + 飞书应用）。

## Threat Surface Scan
无新增网络端点 / auth 路径 / 文件访问 / schema 变更——纯查询复用既有 client 能力 + 既有 writeback 字段读访问。威胁寄存器 T-63-08/09/10/11 已全部 mitigate（创建前查既有 + fail-soft + token 不入日志）。

## Next Phase Readiness
- IDEMP-02 完成：MR/PR 创建 + 飞书建群上 reuse-first fencing，at-least-once 重投不产生重复外部动作。
- 无 outbox 表，无锚/异常时 fail-soft 退化为现状（零回归）。

## Self-Check: PASSED
- 创建文件存在：`server/tests/workflows/test_coding_mr_dedup.py` FOUND
- 提交存在：`b5cf8389f` / `6115e2507` / `0c141e744` 均在 git log
- grep：`find_open_merge_request` 命中 base/gitlab/github/coding 四文件；`aget_feishu_chat_id` 命中 work_item_service + feishu_chat 两文件

---
*Phase: 63-deploy*
*Completed: 2026-06-21*
