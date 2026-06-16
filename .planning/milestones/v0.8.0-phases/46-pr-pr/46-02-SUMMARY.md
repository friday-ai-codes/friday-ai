---
phase: 46-pr-pr
plan: 02
subsystem: workflows
tags: [pull-request, cross-reference, traceability, multi-repo, wave, fail-soft, tdd, async-orm]

# Dependency graph
requires:
  - phase: 44-wave
    provides: "AICodingNode wave 调度 + _finalize_and_notify 唯一收尾收口（done 仓批量建 MR）"
  - phase: 45-artifact
    provides: "多仓 wave 端到端收尾路径 + plan_data 透传链（plan_version_id 可达）"
  - phase: 46-pr-pr (plan 01)
    provides: "_create_mr_for_repo per-repo target_branch 解析（PR-01）"
provides:
  - "可复用 helper workflows/services/pr_cross_reference.py：cross-ref 纯函数段 + async 追溯渲染 + async 回写编排"
  - "_finalize_and_notify 内 ≥2 成功仓 cross-ref 回写（整段 fail-soft）"
  - "_create_mr_for_repo 成功返回追加 description（供回写拼接原 body）"
affects: [pr-cross-reference, multi-repo-merge-pr, chat-coding-cross-ref-followup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "create-all-then-update-each：先批量建 MR、收集成功名单，再逐 PR 回写描述追加兄弟链接 + 追溯段"
    - "async ORM 追溯逐跳：plan_version_id → PlanVersion → TechnicalPlan → WorkItem 全程 *_id 标量 + afirst（规避 SynchronousOnlyOperation）"
    - "cross-ref/追溯 helper 入口无关（自取 Repository），供 wave 收尾复用、chat 入口 follow-up 可复用"

key-files:
  created:
    - server/workflows/services/pr_cross_reference.py
    - server/tests/workflows/test_pr_cross_reference.py
  modified:
    - server/workflows/services/__init__.py
    - server/workflows/nodes/ai/coding.py

key-decisions:
  - "D-09 备选落地：仅 wave 路径用新 helper，CreatePRNode 保持原样不改（英文「## Related PRs」+ 共享 body + 并行 gather），helper docstring 显式标注同源、统一留 backlog（最小 diff / 零回归）"
  - "cross-ref/追溯整段 fail-soft：≥2 守门后 try/except + warning，绝不上抛回灌容器回调 5xx（T-46-04）"
  - "WorkItem 无通用 url 字段——追溯段用飞书三元组 + 标题，仅 prd_url 非空才附链接，不构造臆造 URL（Open Q1/A2）"

patterns-established:
  - "cross-ref 回写 helper 自取 Repository（经 repository_id），入口无关便于多入口复用"
  - "追溯渲染整函数 try/except 兜底 + 逐跳 afirst None 短路，链断省略段不抛"

requirements-completed: [PR-02]

# Metrics
duration: ~14min
completed: 2026-06-16
---

# Phase 46 Plan 02: 多仓融合 PR cross-ref + 跨仓追溯 Summary

**多仓 wave 编码收尾批量建 MR 后，对成功名单（≥2 仓）回写描述追加「## 关联 PR」兄弟仓链接段（排除自身）+「## 关联方案 / 工作项」追溯段（plan_version_id → PlanVersion → TechnicalPlan → WorkItem），提取为可复用 helper `pr_cross_reference.py`，全程 fail-soft。**

## Performance

- **Duration:** ~14 min
- **Completed:** 2026-06-16
- **Tasks:** 2（均 TDD：RED test → GREEN impl）
- **Files modified:** 4（创建 2 / 修改 2）

## Accomplishments
- 新建 helper `workflows/services/pr_cross_reference.py` 三函数：`generate_cross_reference_section`（纯函数，中文「## 关联 PR」、排除自身、单 PR 空段）、`render_traceability_section`（async，逐跳 afirst + `*_id` 标量、链断/异常返回空、整函数 fail-soft）、`add_cross_references`（async，自取 Repository + aresolve_git_token + get_git_platform_client，GitHub `_get_repo().get_pull().edit(body=)` / GitLab `_get_project().mergerequests.get().save()` 经 `asyncio.to_thread`，逐 PR try/except 隔离）
- 经 `workflows/services/__init__.py` barrel 再导出三符号
- `_create_mr_for_repo` 成功分支返回追加 `"description": body`（供回写拼接原 body）
- `_finalize_and_notify` MR 创建循环后接线：`successful_mrs ≥ 2` 守门（D-05）→ `add_cross_references(..., plan_version_id=(plan_data or {}).get("plan_version_id"))`，整段 `try/except` fail-soft（`# noqa: BLE001`，T-46-04）
- 守护测试 13 例（纯函数 2 / 追溯 4 / 回写 4 / 接线集成 3）+ `test_coding_wave.py` 7 例零回归，全绿；helper/coding.py ruff line 100 通过

## Task Commits

1. **Task 1 RED：helper 守护测试** - `53576c06` (test) — 纯函数/追溯/回写用例（模块缺失即 fail）
2. **Task 1 GREEN：helper + barrel** - `d3bc7c87` (feat) — 三函数实现 + barrel 导出，10 测全绿
3. **Task 2 RED：接线集成测试** - `113f5b4d` (test) — ≥2 触发 / 单仓不调 / 回写抛错仍 completed
4. **Task 2 GREEN：_finalize_and_notify 接线** - `5c6515f8` (feat) — description 返回 + ≥2 守门 + 整段 fail-soft

_TDD：每任务 RED test 提交 → GREEN impl 提交。_

## Files Created/Modified
- `server/workflows/services/pr_cross_reference.py` - cross-ref 纯函数段 + async 追溯渲染 + async 回写编排（同源 CreatePRNode，wave 收尾专用）
- `server/tests/workflows/test_pr_cross_reference.py` - PR-02 守护测试（纯函数 + 追溯真实 DB 链 + 回写 mock client + 接线集成）
- `server/workflows/services/__init__.py` - barrel 追加导出 pr_cross_reference 三符号
- `server/workflows/nodes/ai/coding.py` - `_create_mr_for_repo` 成功返回加 `description`；`_finalize_and_notify` MR 循环后 ≥2 守门 cross-ref 回写段（fail-soft）

## Decisions Made
- 采纳 D-09 备选：仅 wave 路径用新 helper，`CreatePRNode` 保持原样不改（重构会改其英文「## Related PRs」文案 + 触发 `test_batch_pr.py` 回归，blast radius 不值当）；helper docstring 显式标注同源、后续统一留 backlog。
- 追溯段 WorkItem 标识用飞书三元组 `{work_item_type}/{work_item_id} {title}`，仅 `prd_url` 非空才附链接（WorkItem 无通用 url 字段，不构造臆造飞书 URL，Open Q1/A2）。
- cross-ref helper 自取 Repository（经 `repository_id`）而非由调用方传仓对象，入口无关便于 chat 路径 follow-up 复用。

## Deviations from Plan

None - plan executed exactly as written. 两任务均按 TDD RED→GREEN 落地；helper 三函数签名/键约定、接线守门与 fail-soft 边界、追溯逐跳与文案均与 PLAN `<action>` 逐条对齐。

## Issues Encountered
- **`test_batch_pr.py` 5 例 PRE-EXISTING 失败（out-of-scope，未修复）**：`AttributeError: module 'workflows.nodes.git.pr' has no attribute 'GitCredential'`（及 `decrypt_value`）。根因 Phase 26 已把 `pr.py` 取 token 统一到 `aresolve_git_token`、移除模块级 `GitCredential`/`decrypt_value` 符号，但 `test_batch_pr.py` 仍 patch 这些已不存在的 target。将本 plan `coding.py` 改动 stash 后这 5 例仍失败 → 与 46-02 无关（46-02 未触 `pr.py`，D-09 明确 CreatePRNode 不改）。已记 `deferred-items.md`，建议后续 quick task 迁移其 mock 范式到 `aresolve_git_token`。
- 测试本身两处 RED→GREEN 修正（非生产 bug）：`MagicMock(name=...)` 是构造保留字须创建后赋值；追溯「无 work_item」断言须改为 `"- 工作项:" not in`（标题含「工作项」字样）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PR-02 cross-ref + 跨仓追溯就绪，Phase 46（PR-01 + PR-02）两 plan 全部收官；helper 入口无关，chat 编码入口 cross-ref 接线为 follow-up（已记 CONTEXT deferred）。
- 真实 GitHub/GitLab 多仓 MR 创建 + 回写端到端验收仍需真实凭证/平台（既有 deferred，本地 mock IO 边界覆盖）。

## Self-Check: PASSED
- FOUND: server/workflows/services/pr_cross_reference.py
- FOUND: server/tests/workflows/test_pr_cross_reference.py
- FOUND: server/workflows/services/__init__.py（barrel 含 pr_cross_reference 三符号）
- FOUND: server/workflows/nodes/ai/coding.py（`add_cross_references` 接线 + `"description": body`）
- FOUND commit: 53576c06 (test RED helper)
- FOUND commit: d3bc7c87 (feat helper + barrel)
- FOUND commit: 113f5b4d (test RED 接线)
- FOUND commit: 5c6515f8 (feat 接线 fail-soft)

---
*Phase: 46-pr-pr*
*Completed: 2026-06-16*
