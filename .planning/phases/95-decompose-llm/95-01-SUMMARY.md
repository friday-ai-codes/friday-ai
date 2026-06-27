---
phase: 95-decompose-llm
plan: 01
subsystem: observability
tags: [call_source, logging-spec, enum, decompose, plan_orchestration]

# Dependency graph
requires:
  - phase: 89-plan-deepen
    provides: CallSource 受控枚举 + LOGGING-SPEC §4.1 call_source 表格（branch_naming 等既有登记）
provides:
  - "CallSource.PLAN_DECOMPOSE = 'plan_decompose' 受控枚举值（helper 95-02 标注 LLM 拆分调用来源）"
  - "LOGGING-SPEC §4.1 plan_decompose 登记行 + plan_clarification 补登"
affects: [95-decompose-llm, observability, plan_orchestration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "新增 LLM 调用点先在 CallSource 枚举铺设受控维度值 + LOGGING-SPEC §4.1 登记，再落 helper（观测底座先行）"

key-files:
  created: []
  modified:
    - server/agents/call_source.py
    - .planning/observability/LOGGING-SPEC.md
    - server/tests/test_model_usage_call_source.py

key-decisions:
  - "枚举成员计数 docstring 一并订正 30 → 32（修复 plan_clarification 此前加入时的漏计）"
  - "顺手补登 plan_clarification（代码枚举已有、spec 此前漏登记），消除 spec ↔ 枚举登记缺口"

patterns-established:
  - "完整性守护测试 _EXPECTED_CALL_SOURCES 随枚举同步更新，多一少一都失败"

requirements-completed: [DECOMP-01]

# Metrics
duration: 6min
completed: 2026-06-28
---

# Phase 95 Plan 01: CallSource PLAN_DECOMPOSE 枚举 + LOGGING-SPEC 登记 Summary

**为 DECOMP-01 LLM 拆分调用铺设观测底座：`CallSource` 受控枚举新增 `PLAN_DECOMPOSE = "plan_decompose"`，LOGGING-SPEC §4.1 登记 `plan_decompose` 并补登历史漏记的 `plan_clarification`**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-27T17:31:00Z
- **Completed:** 2026-06-27T17:35:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `CallSource.PLAN_DECOMPOSE = "plan_decompose"` 受控枚举值落地；`normalize('plan_decompose')` 回显自身，非法值仍回退 `unknown`（基数受控不变）
- 模块/类 docstring 成员计数订正 30 → 32（实测当前 31 + 新增 = 32，修复 plan_clarification 漏计）
- LOGGING-SPEC §4.1 新增 `plan_decompose` 登记行 + 补登 `plan_clarification`，消除 spec ↔ 枚举登记缺口
- 完整性守护测试同步升至 32 值基准，`test_model_usage_call_source.py` 全绿（25 passed）

## Task Commits

Each task was committed atomically:

1. **Task 1: CallSource 新增 PLAN_DECOMPOSE 枚举值** - `e0df4fcb` (feat)
2. **Task 2: LOGGING-SPEC §4.1 登记 plan_decompose + 补 plan_clarification** - `565fd601` (docs)

_Task 1 一并更新 `test_model_usage_call_source.py` 完整性守护（同属枚举契约，随枚举原子提交）。_

## Files Created/Modified
- `server/agents/call_source.py` - 末尾新增 `PLAN_DECOMPOSE` 成员 + 中文注释；模块/类 docstring 计数 30 → 32
- `.planning/observability/LOGGING-SPEC.md` - §4.1 表格 `branch_naming` 行后追加 `plan_clarification` / `plan_decompose` 两行登记
- `server/tests/test_model_usage_call_source.py` - `_EXPECTED_CALL_SOURCES` 增补两值 + 计数断言 30 → 32 + 守护注释更新

## Decisions Made
- **docstring 计数订正 32：** 计划要求实测核对，当前枚举为 31 成员（含 Phase 90 的 `PLAN_CLARIFICATION`），新增后 32，docstring 旧写 30 一并校正。
- **补登 plan_clarification：** 代码枚举 Phase 90 已加入但 LOGGING-SPEC 与守护测试均未同步，属登记缺口，本次随 plan_decompose 一并补齐。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 同步更新 call_source 完整性守护测试**
- **Found during:** Task 1（运行 `relevant pytest（call_source）`）
- **Issue:** `tests/test_model_usage_call_source.py::TestCallSourceEnum::test_enum_has_all_22_values` 守护测试 `_EXPECTED_CALL_SOURCES` 仍为 30 值（缺 `plan_clarification`，Phase 90 加入枚举时漏更）；叠加本次新增 `plan_decompose`，断言失败。该测试是「枚举多一少一都失败」的完整性守护，必须随枚举同步，否则 `相关 pytest（call_source）通过` 不成立。
- **Fix:** 补入 `plan_clarification` / `plan_decompose` 两值、计数断言 30 → 32、更新守护注释
- **Files modified:** server/tests/test_model_usage_call_source.py
- **Verification:** `uv run pytest tests/test_model_usage_call_source.py -q` → 25 passed
- **Committed in:** `e0df4fcb`（Task 1 commit，与枚举契约同源原子提交）

---

**Total deviations:** 1 auto-fixed (1 bug — 守护测试与枚举同步)
**Impact on plan:** 守护测试更新是枚举契约的必然伴随项，无范围蔓延；其余严格按计划执行。

## Issues Encountered
- 初次运行误用 `tests/agents -k call_source`（无匹配用例，全部 deselected）；call_source 专测实为 `tests/test_model_usage_call_source.py`，定位后正常执行。

## User Setup Required
None - 纯仓内枚举 + 文档登记，无外部服务配置，无新迁移，无供应链面。

## Next Phase Readiness
- `CallSource.PLAN_DECOMPOSE` 就绪，95-02 helper 可经 `use_call_source(CallSource.PLAN_DECOMPOSE)` 标注 LLM 拆分调用来源，chokepoint 按维度上报请求/token/TTFT/上游错误码。
- 无阻塞。

## Self-Check: PASSED

- FOUND: server/agents/call_source.py
- FOUND: .planning/observability/LOGGING-SPEC.md
- FOUND: .planning/phases/95-decompose-llm/95-01-SUMMARY.md
- FOUND commit: e0df4fcbc (Task 1)
- FOUND commit: 565fd6013 (Task 2)

---
*Phase: 95-decompose-llm*
*Completed: 2026-06-28*
