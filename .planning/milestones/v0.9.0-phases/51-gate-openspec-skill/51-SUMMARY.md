---
phase: 51-gate-openspec-skill
plan: ALL
subsystem: delivery+workflows+task
tags: [openspec, sdd, gate, fail-closed, follow_openspec, env-injection, system-prompt]

requires:
  - phase: 44-multi-repo-wave-coding
    provides: RepoCodingTask + RepoCodingTaskService + AICodingNode._dispatch_wave + aadvance 传递闭包
  - phase: 48-repo-methodology
    provides: Repository.facets.methodology=="SDD"
  - phase: 49-sdd-spec
    provides: SddSpec / SddSpecStatus.APPROVED
provides:
  - SDD 仓编码前置 gate：未批准 spec fail-closed 拦截，已批准放行，非 SDD 零回归
  - openspec 指引注入链路：dispatch env_FRIDAY_TASK_FOLLOW_OPENSPEC → task system_prompt openspec 段
affects: [52-spec-pr-link]

tech-stack:
  added: []
  patterns:
    - "gate 唯一写入入口 mark_gate_blocked（INV-6）+ 独立可测 gate helper"
    - "PF-06 逐键 env 注入扩展 openspec 布尔信号"
    - "follow_openspec 默认 False 全链路零回归"

key-files:
  created:
    - server/tests/test_coding_openspec_gate.py
    - task/tests/test_openspec_prompt.py
  modified:
    - server/delivery/services/repo_coding_task_service.py
    - server/workflows/nodes/ai/coding.py
    - task/core/config.py
    - task/core/executor.py

key-decisions:
  - "follow_openspec 来源（仓 facets 置位）与 gate 判定落库（mark_gate_blocked）均收口唯一 service"
  - "gate 在 _dispatch_wave 一处生效，首发 + wave 推进两路覆盖；fail-closed + 单仓隔离"
  - "openspec 指引只加 system_prompt 注入点，.claude/skills 复用既有 setting_sources 原生加载"

requirements-completed: [GATE-01, GATE-02]

duration: ~40min
completed: 2026-06-17
---

# Phase 51: 编码前置 gate + openspec skill 编码策略 Summary

**SDD 仓编码前强制 spec 已 approved 才放行（follow_openspec=True 仓校验 SddSpec.status==APPROVED，未批准/校验异常 fail-closed 经 mark_gate_blocked 拦截不 dispatch、单仓隔离不崩 wave、并经 aadvance 传递闭包阻断下游），并通过 dispatch env → task system_prompt 注入 openspec 指引使 approved SDD 仓按 openspec 流程编码；非 SDD 仓全链路零回归**

## Performance

- **Duration:** ~40 min（3 plans / 2 waves）
- **Tasks:** 7（51-01 ×2、51-02 ×3、51-03 ×2，均 TDD 除回归门）
- **Files modified/created:** 8（server 5 + task 3，其中 2 新建测试文件）

## Accomplishments

**GATE-01（编码前置 gate，fail-closed）**
- `create_tasks_for_plan` 首次消费 `follow_openspec`：SDD 仓（`facets.methodology=="SDD"`）置 True、非 SDD False，漂移幂等回填
- `mark_gate_blocked` gate 拦截唯一写入入口（条件 pending→failed + `{reason, spec_status}` 结构化诊断，INV-6）
- `AICodingNode._apply_openspec_gate`：False 放行不查 spec；True+approved 放行；未批准 → `spec_not_approved` 拦截；校验异常 → `gate_error` fail-closed + 单仓 try/except 隔离
- 拦截仓并入 failed 返回 → `aadvance_coding_waves` 传递闭包阻断下游 `upstream_failed`（真实闭包验证）

**GATE-02（openspec 指引注入）**
- server：approved SDD 仓 dispatch metadata 注入 `env_FRIDAY_TASK_FOLLOW_OPENSPEC="true"`（PF-06 逐键范式），非 SDD/legacy 不含该键
- task：`TaskConfig.follow_openspec`（env 映射）+ `_get_system_prompt` 条件追加 `_openspec_guidance` 段（遵循 `openspec/` 已批准 spec、优先查仓库内 openspec skill 按 delta 实现）
- `.claude/skills` 复用既有 `setting_sources=["project"]` 原生加载（不改）

**零回归守护**
- 非 SDD/legacy 仓不经 gate、不查 SddSpec（grep spy + 行为双证）；task follow_openspec 缺省 → system_prompt 逐字等现状

## Task Commits

1. **51-01 T1: create_tasks_for_plan follow_openspec 置位** - `73fedef1b` (feat)
2. **51-01 T2: mark_gate_blocked 单一写入入口** - `827c30701` (feat)
3. **51-03 T1: TaskConfig.follow_openspec 字段** - `4ba41acdb` (feat)
4. **51-03 T2: _get_system_prompt openspec 段 + MagicMock 修正** - `af96b0129` (feat)
5. **51-02 T1+T2: gate helper + env 注入** - `23c77472b` (feat)
6. **51-02 T3: legacy 零回归门** - `3338bd734` (test)
7. **51-02 docstring INV-6 守护修正** - `14ce3a65a` (fix)

## Testing

- 后端：`test_repo_coding_task_service.py`（follow_openspec SDD/非 SDD/漂移 + mark_gate_blocked 三态）、`test_repo_coding_task_inv6_guard.py`（mark_gate_blocked 经 service 正向断言）、`test_coding_openspec_gate.py`（11 用例：gate 全态 + 下游阻断 + fail-closed 隔离 + legacy 短路 + env 注入）、`test_coding_wave.py`（legacy 非 wave SddSpec spy 零回归）
- task：`test_config.py`（follow_openspec 默认/参数/env）、`test_openspec_prompt.py`（true 含段 / false 逐字等现状）、`test_callback.py`（MagicMock-config 修正）
- 全量回归：server `tests/delivery/ + 编码套件 + wave_progression` **408 passed, 1 xfailed**；task 全套 **185 passed, 3 skipped**
- `ruff check`（改动文件全绿）+ `makemigrations --check` **No changes detected**（follow_openspec v0.8 已存在，无新 migration）

## Decisions Made
- gate helper 内 `afirst` 一次查询同时得 spec 存在性与 status。
- gate_error 与 spec_not_approved 共用 `mark_gate_blocked`，仅 reason/spec_status payload 不同。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] gate helper docstring 触发 SddSpec INV-6 grep 守护误判**
- **Found during:** 51-02 广义回归
- **Issue:** docstring 字面量 ``SddSpec(plan_version_id, repository_id)`` 被 INV-6 实例化正则误判旁路写
- **Fix:** 改全角括号 ``SddSpec``（按 plan_version_id × repository_id），语义不变
- **Committed in:** `14ce3a65a`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact:** 仅注释文本，零行为影响，无 scope creep。

## Issues Encountered

- **既有 task 仓库面 lint/format 漂移（out-of-scope）**：`task` 全仓 `ruff format --check .` 报 14 个无关文件待格式化、`ruff check .` 报 `tests/test_exclusion_prune.py` 一处 I001——均为本 phase 未触及的既有漂移，按 SCOPE BOUNDARY 不修正（本 phase 改动文件本身全绿）。

## Deferred / Human-needed

- 真实 runner + Docker 容器端到端（gate 拦截真实编码 / openspec skill 真实加载 + 真模型遵循 openspec 流程）→ 真实环境人工验收（对齐既有容器 E2E deferred，不纳入自动化）。
- spec↔实现 PR 关联 + 交付验收视图 → Phase 52。

## Next Phase Readiness
- gate + openspec 注入全链路就绪；Phase 52 可在 gate 放行后回填 spec↔PR 关联。

## Self-Check: PASSED

- All created files verified on disk (test_coding_openspec_gate.py, test_openspec_prompt.py, 4 SUMMARY files).
- All 7 task commits verified via `git rev-parse` (73fedef1b, 827c30701, 4ba41acdb, af96b0129, 23c77472b, 3338bd734, 14ce3a65a).

---
*Phase: 51-gate-openspec-skill*
*Completed: 2026-06-17*
