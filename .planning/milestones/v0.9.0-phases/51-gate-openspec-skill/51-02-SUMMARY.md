---
phase: 51-gate-openspec-skill
plan: 02
subsystem: workflows
tags: [openspec, sdd, gate, ai-coding, dispatch, env-injection, fail-closed]

requires:
  - phase: 51-01
    provides: follow_openspec 置位 + mark_gate_blocked 单一写入入口
  - phase: 49-sdd-spec
    provides: SddSpec / SddSpecStatus.APPROVED 模型
  - phase: 44-multi-repo-wave-coding
    provides: AICodingNode._dispatch_wave / aadvance_coding_waves 传递闭包
provides:
  - _dispatch_wave 前置 openspec gate（fail-closed + 单仓隔离）
  - env_FRIDAY_TASK_FOLLOW_OPENSPEC dispatch metadata 注入（仅 approved SDD 仓）
affects: [52-spec-pr-link]

tech-stack:
  added: []
  patterns:
    - "独立可测 gate helper _apply_openspec_gate 返回 (passed_repo_ids, gate_blocked_failed)"
    - "PF-06 逐键 env 注入（openspec_env 与 git_env/anthropic_env 同范式）"
    - "单仓 try/except fail-closed 隔离，异常绝不冒泡崩 wave"

key-files:
  created:
    - server/tests/test_coding_openspec_gate.py
  modified:
    - server/workflows/nodes/ai/coding.py
    - server/tests/test_coding_wave.py

key-decisions:
  - "gate 在 _dispatch_wave 顶部一处生效，首发 + wave 推进两路覆盖"
  - "follow_openspec=False 仓完全不触发 SddSpec 查询（grep + 行为双证零回归）"
  - "afirst 一次查询同时得 exists + status（spec_status 取 status 或 missing）"

patterns-established:
  - "gate 拦截仓并入 failed 返回 → 经 aadvance 传递闭包阻断下游 upstream_failed"

requirements-completed: [GATE-01, GATE-02]

duration: ~20min
completed: 2026-06-17
---

# Phase 51 Plan 02: 编码前置 gate + env 注入 Summary

**AICodingNode._dispatch_wave 加 fail-closed openspec gate（follow_openspec=True 仓强制 SddSpec.status==APPROVED 才放行，未批准/异常经 mark_gate_blocked 拦截不 dispatch，单仓异常隔离不崩 wave）+ approved SDD 仓 dispatch metadata 注入 env_FRIDAY_TASK_FOLLOW_OPENSPEC=true**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 (T1/T2 TDD + T3 回归门)
- **Files modified:** 3

## Accomplishments
- `_apply_openspec_gate` helper：follow_openspec=False 放行不查 spec；True+approved 放行；未批准（无 spec/draft/in_review/implemented）拦截 `reason=spec_not_approved`
- gate 校验异常 → fail-closed `reason=gate_error` + 单仓 try/except 隔离，其余仓正常 dispatch
- gate 拦截仓并入 `_dispatch_wave` failed 返回；经真实 `aadvance_coding_waves` 验证下游被传递闭包阻断（`upstream_failed`）
- `_run_repo_coding` 加 `follow_openspec` 参数，approved SDD 仓 metadata 注入 `env_FRIDAY_TASK_FOLLOW_OPENSPEC=true`，非 SDD/legacy 不含该键
- legacy 非 wave 模式（tasks_by_repo=None）短路：spy 断言不触发 SddSpec 查询

## Task Commits

1. **Task 1+2: gate helper + env 注入** - `23c77472b` (feat, TDD)
2. **Task 3: legacy 零回归门** - `3338bd734` (test)
3. **docstring INV-6 守护修正** - `14ce3a65a` (fix, 见 Deviations)

## Files Created/Modified
- `server/workflows/nodes/ai/coding.py` - `_apply_openspec_gate` + `_run_repo_coding` openspec_env 注入
- `server/tests/test_coding_openspec_gate.py` - gate 全态 + 下游阻断 + fail-closed 隔离 + env 注入守护（11 用例）
- `server/tests/test_coding_wave.py` - legacy 非 wave 零回归 SddSpec 查询 spy

## Decisions Made
- gate helper 内 `afirst` 一次查询同时得 spec 存在性与 status，省一次 aexists。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] gate helper docstring 触发 SddSpec INV-6 grep 守护误判**
- **Found during:** Task 1（广义回归运行 test_sdd_spec_inv6_guard）
- **Issue:** docstring 字面量 ``SddSpec(plan_version_id, repository_id)`` 被 INV-6 实例化正则 `\bSddSpec(?!...)\s*\(` 误判为旁路写实例化
- **Fix:** 改写为 ``SddSpec``（按 plan_version_id × repository_id）全角括号，语义不变、不触正则
- **Files modified:** server/workflows/nodes/ai/coding.py
- **Verification:** `test_sdd_spec_inv6_guard.py` + gate 套件全绿
- **Committed in:** `14ce3a65a`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 仅注释文本，零行为影响，无 scope creep。

## Issues Encountered
None（除上述守护误判，已修正）。

## Next Phase Readiness
- gate + env 注入服务端半完成；容器侧由 51-03 消费 env。
- 真实容器 E2E（gate 拦截真实编码 / openspec skill 真实加载）属 human_needed deferred。

---
*Phase: 51-gate-openspec-skill*
*Completed: 2026-06-17*
