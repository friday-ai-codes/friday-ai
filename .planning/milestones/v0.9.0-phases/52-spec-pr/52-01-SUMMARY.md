---
phase: 52-spec-pr
plan: 01
subsystem: api
tags: [sdd-spec, pr-link, json-field, fail-soft, inv-6, django, async-orm]

requires:
  - phase: 49-sdd-spec
    provides: SddSpec 脊柱模型 + SddSpecService 写入收口（INV-6）
  - phase: 50-spec-governance
    provides: SddSpecService 状态机流转（mark_implemented approved→implemented）
  - phase: 44-coding-wave
    provides: AICodingNode._finalize_and_notify successful_mrs 收尾链路
provides:
  - SddSpec.implementation_prs JSONField(default=list) + migration 0020
  - SddSpecService.link_implementation_pr 单一写入入口（spec→PR 回填 + approved→implemented）
  - AICodingNode._finalize_and_notify best-effort spec↔PR 回填挂接（fail-soft）
affects: [52-02, 52-03]

tech-stack:
  added: []
  patterns:
    - "spec→PR 写入收口单一 service 入口（INV-6 grep 守护扩展）"
    - "收尾链路 best-effort 增强整段 try/except fail-soft（镜像 cross-ref 范式）"

key-files:
  created:
    - server/delivery/migrations/0020_sddspec_implementation_prs.py
    - server/tests/delivery/test_sdd_spec_pr_link.py
    - server/tests/test_coding_pr_link_failsoft.py
  modified:
    - server/delivery/models/sdd_spec.py
    - server/delivery/services/sdd_spec_service.py
    - server/workflows/nodes/ai/coding.py

key-decisions:
  - "approved→implemented 复用 _LEGAL_TRANSITIONS['mark_implemented'] 源/目标常量作单一真相，不重复硬编码状态表"
  - "pr_url 去重幂等：已含相同 pr_url 不重复追加、不重复触发状态流转"
  - "非 approved spec 宽容：仅记 PR ref + warning，不强转状态、不抛异常"
  - "plan_version_id 取 (plan_data or {}).get('plan_version_id')，与 add_cross_references 同锚"

patterns-established:
  - "spec→PR 回填 fail-soft：link 全段异常吞为 warning sdd_spec_pr_link_failed，绝不阻断 PR 创建/通知"

requirements-completed: [LINK-01]

duration: 12min
completed: 2026-06-17
---

# Phase 52 Plan 01: spec↔PR 关联后端数据底座与回填链路 Summary

**SddSpec.implementation_prs JSON 字段 + SddSpecService.link_implementation_pr 单一写入入口（pr_url 去重幂等 + approved→implemented）+ AICodingNode 收尾 best-effort 回填挂接（fail-soft 零回归）**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-17
- **Tasks:** 3
- **Files modified:** 6（3 created + 3 modified）

## Accomplishments
- `SddSpec.implementation_prs = JSONField(default=list)`（元素 `{pr_url, repository_id, linked_at}`）+ 自动生成 migration 0020（nullable 无回填，既有行天然降级空列表）。
- `SddSpecService.link_implementation_pr(*, plan_version_id, repository_id, pr_url)`：按 `(plan_version_id, repository_id)` `select_for_update` 命中 SddSpec → 去重幂等追加 PR ref；approved → 复用 `mark_implemented` 源/目标常量在同事务条件更新转 implemented；非 approved 宽容记录不强转（warning）；无 spec（非 SDD 仓）→ no-op 零回归；append + 状态流转单一 `transaction.atomic`（INV-6）。
- `AICodingNode._finalize_and_notify` 算出 `successful_mrs` 后逐 MR best-effort 调 `link_implementation_pr`，整段 `try/except` 吞为 warning `sdd_spec_pr_link_failed`，绝不阻断 PR 创建/通知/节点完成；`plan_version_id` 缺失或无 successful_mrs 则跳过整段（零回归）。

## Task Commits

1. **Task 1: SddSpec.implementation_prs 字段 + migration 0020** - `352127eb` (feat)
2. **Task 2: SddSpecService.link_implementation_pr 单一写入入口** - `ffda84a9` (feat, TDD RED→GREEN 单提交)
3. **Task 3: _finalize_and_notify best-effort 回填挂接** - `22a8e318` (feat, TDD RED→GREEN 单提交)

## Files Created/Modified
- `server/delivery/models/sdd_spec.py` - 新增 implementation_prs JSONField
- `server/delivery/migrations/0020_sddspec_implementation_prs.py` - 字段 migration
- `server/delivery/services/sdd_spec_service.py` - link_implementation_pr 单一写入入口
- `server/workflows/nodes/ai/coding.py` - 收尾 best-effort spec↔PR 回填挂接
- `server/tests/delivery/test_sdd_spec_pr_link.py` - 6 类行为守护测试
- `server/tests/test_coding_pr_link_failsoft.py` - fail-soft / 逐 MR 回填 / 零回归 3 类断言

## Decisions Made
- 状态流转复用 `_LEGAL_TRANSITIONS["mark_implemented"]` 常量（单一真相）。
- 非 approved 宽容：保留 PR ref 不强转，记 `sdd_spec_pr_link_non_approved` warning。
- TDD 任务 RED 失败 → GREEN 通过后单次提交（RED/GREEN 同一提交内，因测试与实现强耦合且无中间需要保留的 RED 提交价值）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `uv run pytest` 会落到 pyenv 全局 python（venv 未装 pytest 为模块入口），改用 `uv run python -m pytest` 并固定 `working_directory=server` 跑测试。非代码问题，仅执行环境调用方式。
- `ruff check delivery workflows tests` 报 172 个**既有**告警（与本 plan 无关的历史文件），本 plan 6 个改动文件 `ruff check` 全绿，按 SCOPE BOUNDARY 不修既有告警。

## Next Phase Readiness
- 写入侧完整：Plan 02 可在 detail serializer 暴露 `implementation_prs` + 追溯摘要；Plan 03 前端按契约渲染。
- 真实容器 E2E（真实编码产 PR 回填）→ human_needed deferred。

## Self-Check: PASSED
- FOUND: server/delivery/migrations/0020_sddspec_implementation_prs.py
- FOUND: server/tests/delivery/test_sdd_spec_pr_link.py
- FOUND: server/tests/test_coding_pr_link_failsoft.py
- FOUND commits: 352127eb, ffda84a9, 22a8e318

---
*Phase: 52-spec-pr*
*Completed: 2026-06-17*
