---
phase: 260817-xb9-readable-repo-research-detail
plan: 01
subsystem: ui
tags: [blueprint, repo-research, i18n, event-payload, process-runtime]

requires:

  - phase: 112-repo-research
    provides: blueprint.repo_research.* 事件与进度文案骨架
provides:

  - started/completed/failed 可读 payload（repository_name / research_reason / fitness_verdict / attempt）
  - 过程明细字段排序（人话优先、*_id 殿后）与枚举中文化

affects: [blueprint-stage-stepper, activity-timeline]

tech-stack:
  added: []
  patterns:

    - last_output.repository_name 派发写入、回调只读回填（不采信容器上报）
    - completed 同时写 fitness_verdict + verdict 兼容键
    - describeEventPayload 标量字段 priority 排序

key-files:
  created: []
  modified:

    - server/services/process_runtime/blueprint_research_adapter.py
    - server/subagent/api/callbacks.py
    - server/delivery/services/event_taxonomy.py
    - web/src/locales/zh-CN.json
    - web/src/utils/blueprintActivity.ts
    - web/src/components/blueprint/BlueprintStageStepper.vue

key-decisions:

  - "落库事件 JSON 不保证键序；人话优先排序由前端 describeEventPayload 负责"
  - "research_reason 仅取 evidence.reasoning 标量（≤120），不塞 matched_node_paths"

patterns-established:

  - "展示用仓库名经 last_output 回填，权威关联仍靠 repository_id"
  - "进度标题插值前 humanizePayloadEnums，明细字段走 i18n fieldValue"

requirements-completed: [UX-RESEARCH-DETAIL-01, UX-RESEARCH-DETAIL-02, UX-RESEARCH-DETAIL-03]

duration: 11min
completed: 2026-08-17
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Phase 260817-xb9 Plan 01: readable-repo-research-detail Summary

**蓝图「仓库调研」过程明细三事件对齐可读 payload，并完成前端标签/枚举/字段排序与存量 Generic 回退**

## Performance

- **Duration:** 11 min
- **Started:** 2026-08-17T16:03:33Z
- **Completed:** 2026-08-17T16:14:34Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- started 带 `repository_name` + `research_reason`（placement_* 翻人话，≤120）；`last_output` 回填 name
- completed 写 `fitness_verdict` 并保留 `verdict`；failed 写 `repository_name` + `attempt`
- 前端：标签中文化、置信度/适配枚举人话化、人话键优先 UUID 殿后；缺 name 仍走 Generic

## Task Commits

1. **Task 1 (RED):** `b4600f6f` — test(260817-xb9): 补充仓库调研事件可读性断言
2. **Task 1 (GREEN):** `1589ad9a` — feat(260817-xb9): 对齐仓库调研三事件可读 payload
3. **Task 2:** `d462232b` — feat(260817-xb9): 前端过程明细人话化与字段排序

_Note: docs/SUMMARY 由 orchestrator Step 8 提交；本执行器未提交 .planning 产物。_

## Files Created/Modified

- `server/services/process_runtime/blueprint_research_adapter.py` — `_format_research_reason`、started/failed payload、last_output.name
- `server/subagent/api/callbacks.py` — completed/failed 可读字段
- `server/delivery/services/event_taxonomy.py` — payload 契约注释对齐
- `server/tests/services/process_runtime/test_blueprint_research_stage.py` — started / reason 断言
- `server/tests/subagent/test_blueprint_research_callback.py` — completed/failed 断言
- `web/src/locales/zh-CN.json` — routed_confidence / research_reason / 置信度文案
- `web/src/utils/blueprintActivity.ts` — 字段排序 + humanize 辅助
- `web/src/components/blueprint/BlueprintStageStepper.vue` — fieldValue / eventLabel 人话化
- 前端三份测试补齐有/无 name、排序、枚举与回退

## Decisions Made

- 落库后事件 payload 键序不可靠 → 不在后端测试断言键序，由前端 `describeEventPayload` 排序
- `research_reason` 只派生自 `evidence.reasoning` 标量，禁止路径列表入事件（T-xb9-01）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 放宽 started 落库键序断言**

- **Found during:** Task 1 (GREEN)
- **Issue:** 事件经 DB/JSON 落库后键序变为 `task_id`/`repository_id` 在前，键序断言失败；字段值本身正确
- **Fix:** 改为断言键存在；排序交给前端
- **Files modified:** `server/tests/services/process_runtime/test_blueprint_research_stage.py`
- **Verification:** pytest 相关用例全绿
- **Committed in:** `1589ad9a`

**2. [Rule 3 - Blocking] 计划路径测试文件已存在，直接扩展**

- **Found during:** Task 1
- **Issue:** 编排提示「test_blueprint_research_stage.py 可能不存在」
- **Fix:** 核实存在后就近追加用例（未新建平行文件）
- **Files modified:** 同上
- **Verification:** 文件存在且用例通过
- **Committed in:** `b4600f6f` / `1589ad9a`

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking path check)
**Impact on plan:** 无范围蔓延；可读性目标全部达成。

## Issues Encountered

- 工作树含无关 WIP（callbacks / zh-CN）：提交前对共享文件用 HEAD 干净基线改动再回填 WIP，避免误带他人改动

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 新会话「仓库调研」明细应显示仓名与理由；老会话缺字段仍 Generic
- 可进入人工抽查或 `/gsd-verify-work`

## Self-Check: PASSED

- FOUND: `server/services/process_runtime/blueprint_research_adapter.py`（含 `research_reason`）
- FOUND: `web/src/utils/blueprintActivity.ts`（含字段排序）
- FOUND: commits `b4600f6f`, `1589ad9a`, `d462232b`

---
*Phase: 260817-xb9-readable-repo-research-detail*
*Completed: 2026-08-17*
