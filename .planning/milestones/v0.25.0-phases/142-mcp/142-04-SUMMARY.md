---
phase: 142-mcp
plan: "04"
subsystem: testing
tags: [mcp, regression, nyquist, session-capture, schema-alignment]

requires:
  - phase: 142-mcp
    plan: "02"
    provides: report_session_knowledge 服务端 serializer/view/url 与 CaptureService 接线
  - phase: 142-mcp
    plan: "03"
    provides: npm 第 52 个工具定义与幂等 annotations
provides:
  - 服务端 serializer、TOOL_SCHEMA_SNAPSHOT 与 npm 三面键相等的最终证据
  - Phase 142 自有 MCP/Capture/Memory/report_project_knowledge 回归与 Nyquist 收口
  - 工作树蓝图脏改动导致的全目录失败作为范围外非阻断基线记录
affects: [verify-work, 143-eval]

tech-stack:
  added: []
  patterns:
    - Nyquist 按 phase-owned 覆盖判定，不以无关脏工作树全套件为否决
    - 范围外失败只记 VALIDATION/SUMMARY，不改脏文件

key-files:
  created:
    - .planning/phases/142-mcp/142-04-SUMMARY.md
  modified:
    - .planning/phases/142-mcp/142-VALIDATION.md

key-decisions:
  - "client 仅作为 redacted ToolCallRecord audit metadata，不扩展 SessionCapture 或 CaptureService"
  - "Nyquist 以 Phase 142 自有 56 pytest + 12 vitest 为准，两条蓝图脏改动失败不阻断"

patterns-established:
  - "跨面 phase gate 先锁三面快速契约，再跑自有 Capture/Memory 回归"
  - "执行不得暂存用户既有 dirty 文件"

requirements-completed: [MCP-01, MCP-02, MCP-03, MCP-04]

duration: 21min
completed: 2026-08-28
---

# Phase 142 Plan 04: 跨面回归与 Nyquist 收口 Summary

**服务端、schema snapshot 与 npm 三面在合并态对齐，Phase 142 自有 MCP/Capture/Memory 回归全绿，两条蓝图脏改动失败记为范围外非阻断基线**

## Performance

- **Duration:** 21 min
- **Started:** 2026-08-28T08:53:11Z
- **Completed:** 2026-08-28T09:13:49Z
- **Tasks:** 2
- **Files modified:** 1（VALIDATION）；SUMMARY 由计划收口提交

## Accomplishments

- 三面请求键相等与 npm 52 工具/annotations 在 30 秒内通过（server 6 + npm 12）。
- 干净库重跑 Phase 142 自有门禁 **56 passed**：session HTTP 16、旧 `report_project_knowledge` 15、Capture persist 14、schema 2、alignment 4、Capture INV-6 3、Memory INV-6 2。
- 静态审计：`ReportSessionKnowledgeView` 只走 `_begin`/`_validate`/`CaptureService.persist`/`_record`；`traces=[]`；`client` 不传入 persist；`SessionCapture`/`CaptureService`/`test_report_project_knowledge.py` 无 diff。
- `142-VALIDATION.md` 置为 `status=validated`、`wave_0_complete=true`、`nyquist_compliant=true`，并显式记录两条外部基线失败。

## Task Commits

1. **Task 1: 锁三面字段相等并登记快速验证** - `d83670e3` (test)
2. **Task 2: 跑完整回归并审计范围与观测** - `4451c14c` (test)

## Files Created/Modified

- `.planning/phases/142-mcp/142-VALIDATION.md` - Wave 0 全绿、Nyquist 收口、范围外失败台账。
- `.planning/phases/142-mcp/142-04-SUMMARY.md` - 本计划执行结果。

## Decisions Made

- 全目录 `tests/mcp_tools/` 的两条失败来自执行前蓝图脏改动，按范围护栏不修复、不暂存；Nyquist 只看 phase-owned 覆盖。
- `client` 继续只出现在 `_record` 的 `input_data` 中，不扩模型列、不改 CaptureService 签名。

## Verification

- Task 1：`test_schema_snapshot.py` + `test_mcp_package_alignment.py` 6 passed；`mcp npm test -- tests/server.test.ts` 12 passed；约 2.9s。
- Task 2 自有门禁（无 `--reuse-db`）：56 passed in 130.22s；`ruff check` All checks passed；protected-file `git diff --exit-code` 为空。
- 全目录扫描（不作为 Nyquist 否决）：361 collected，359 passed，2 failed（见下）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 全目录失败归因后改为 phase-owned 门禁收口**
- **Found during:** Task 2
- **Issue:** `tests/mcp_tools/` 全目录 2 项失败来自用户既有蓝图脏改动；按编排指令不得修改这些文件。`--reuse-db` 重跑还污染了自有用例 teardown。
- **Fix:** 不改脏文件；用干净库重跑 Phase 142 自有测试文件确认 56 passed；在 VALIDATION/SUMMARY 把两条失败记为 unrelated/non-blocking。
- **Files modified:** `.planning/phases/142-mcp/142-VALIDATION.md`
- **Verification:** 56 passed + npm 12 passed；脏文件仍未暂存。
- **Committed in:** `4451c14c`

---

**Total deviations:** 1 auto-fixed (1 blocking/scope)
**Impact on plan:** 未扩大产品范围；Nyquist 依据 phase-owned 证据完成。

## Issues Encountered

- 全目录失败：`test_route_blueprint_repos_dry_run`（`clarify != v2`）、`test_response_assembly_splats_the_extras_so_the_off_state_is_byte_identical`（`technical_plan_service.py` 新增 `blueprint_status`）。已确认与 Phase 142 无关。
- `--reuse-db` 导致 content-type UniqueViolation / deadlock teardown，不是产品回归。干净库重跑自有文件全绿。

## Unrelated Baseline Failures

| Test | Result | Why non-blocking |
|------|--------|------------------|
| `test_stage_runner_tools.py::test_route_blueprint_repos_dry_run` | `router_version` 期望 `v2` 实为 `clarify` | 未提交 process_runtime/blueprint 改动 |
| `test_blueprint_clarification_tools.py::test_response_assembly_splats_the_extras_so_the_off_state_is_byte_identical` | 源码含 `"blueprint_status":` | 未提交 `technical_plan_service.py` |

保留未提交：`server/tests/mcp_tools/test_skills_snapshot_guard.py`、skills、`.planning/debug/multica-friday-agent-e2e.md` 及其他蓝图/调研脏文件。

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MCP-01..04 有自动化证据，可进入 `$gsd-verify-work`。
- Phase 143 评估/入图仍未实现，符合 CONTEXT deferred。
- 工作树蓝图脏改动需由所属工作自行修绿，不阻塞 Phase 142 合同。

## Self-Check: PASSED

- `142-VALIDATION.md` 与 `142-04-SUMMARY.md` 均存在。
- `d83670e3` 与 `4451c14c` 可在 Git 历史中验证。

---
*Phase: 142-mcp*
*Completed: 2026-08-28*
