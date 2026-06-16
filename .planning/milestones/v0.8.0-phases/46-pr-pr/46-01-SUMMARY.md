---
phase: 46-pr-pr
plan: 01
subsystem: workflows
tags: [merge-request, target-branch, multi-repo, wave, tdd, fail-soft]

# Dependency graph
requires:
  - phase: 44-wave
    provides: "AICodingNode wave 调度 + _create_mr_for_repo per-repo 收尾（传 repository + base_branch）"
  - phase: 45-artifact
    provides: "多仓 wave 端到端收尾路径（test_coding_wave.py 范式）"
provides:
  - "_create_mr_for_repo 内 per-repo target_branch 解析（repository.default_branch or base_branch or \"main\"）"
  - "PR-01 守护测试：per-repo / 零回归 / fallback / 缺凭证 fail-soft"
affects: [46-02, pr-cross-reference, multi-repo-merge-pr]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MR target_branch 锚定各仓权威 default_branch，base_branch 降为 node 级兜底（对齐 mr_service.create_mr_for_task）"

key-files:
  created:
    - server/tests/workflows/test_coding_pr_target_branch.py
  modified:
    - server/workflows/nodes/ai/coding.py

key-decisions:
  - "target_branch fallback 链严格保序 repository.default_branch or base_branch or \"main\"——勿删 base_branch 兜底、勿调换顺序（零回归命门）"
  - "私有方法直测 _create_mr_for_repo（MagicMock 仓 + AsyncMock client），无需走完整 execute 或真实 DB"

patterns-established:
  - "per-repo MR 目标分支解析：各仓用各仓自己的 Repository.default_branch，绝不假设 master / 不共用第一个仓的值"

requirements-completed: [PR-01]

# Metrics
duration: 5min
completed: 2026-06-16
---

# Phase 46 Plan 01: per-repo MR target_branch 解析 Summary

**多仓 wave 编码收尾时各仓 MR 的 `target_branch` 改为锚定各仓自己的 `Repository.default_branch`（fallback 链 `default_branch or base_branch or "main"`），修复 default_branch 不一致时所有 MR 共用第一个仓 base_branch 打错目标分支的 PR-01 病根。**

## Performance

- **Duration:** ~5 min
- **Completed:** 2026-06-16
- **Tasks:** 2（TDD RED → GREEN）
- **Files modified:** 2

## Accomplishments
- `_create_mr_for_repo` 构造 `MRCreateRequest` 前新增一行 per-repo 解析 `resolved_target = repository.default_branch or base_branch or "main"`，`target_branch=base_branch` → `target_branch=resolved_target`
- 新建守护测试 `test_coding_pr_target_branch.py`：per-repo（A=develop / B=release/x，非 "main"、非第一个仓）、零回归（同 default_branch）、fallback 链（空 default_branch → base_branch → "main"）、缺凭证 fail-soft（token None → error、不调 client、不抛）
- 4/4 target_branch 测全绿；`test_coding_wave.py` 7/7 零回归全绿；ruff line 100 通过

## Task Commits

1. **Task 1: 写 PR-01 守护测试（RED）** - `3d53f4f3` (test) — per-repo / fallback 用例 RED，零回归 / fail-soft 先绿
2. **Task 2: per-repo target_branch 解析（GREEN）** - `94495dea` (fix) — 一行 per-repo 解析使 4 测全绿

_TDD：RED test 提交 → GREEN fix 提交。_

## Files Created/Modified
- `server/tests/workflows/test_coding_pr_target_branch.py` - PR-01 守护测试（直测 `_create_mr_for_repo`，捕获 `MRCreateRequest.target_branch`）
- `server/workflows/nodes/ai/coding.py` - `_create_mr_for_repo` 内 per-repo `target_branch` 解析（修改点行 1706 前 + 请求字段）

## Decisions Made
- 守护测试用 `MagicMock` 仓 + `AsyncMock` client 直测私有方法（参考 `test_batch_pr.py` 范式），仅 `pytest.mark.asyncio` 无需 `django_db`——`_create_mr_for_repo` 在 token / client 打桩后不触 ORM。
- 严格保持 fallback 链 `repository.default_branch or base_branch or "main"` 顺序与三级兜底，保单仓 / 同 default_branch 多仓与 Phase 45 逐字等价。

## Deviations from Plan

None - plan executed exactly as written. 未改 `_finalize_and_notify` 调用处、未改 `_execute_with_branch` node 级 `base_branch`、保留既有缺凭证 / 异常 fail-soft 分支不动（最小 diff）。

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PR-01 修复 + 守护测试就绪；Plan 02（共用 helper 与跨仓 PR 关联 PR-02）可在此基础上推进。
- 真实 git platform 多仓 MR 端到端验收仍需真实 GitLab/GitHub 环境（deferred）。

## Self-Check: PASSED
- FOUND: server/tests/workflows/test_coding_pr_target_branch.py
- FOUND: server/workflows/nodes/ai/coding.py（`resolved_target = repository.default_branch or base_branch or "main"`）
- FOUND commit: 3d53f4f3 (test RED)
- FOUND commit: 94495dea (fix GREEN)

---
*Phase: 46-pr-pr*
*Completed: 2026-06-16*
