---
phase: 142-mcp
plan: "01"
subsystem: testing
tags: [mcp, session-capture, pytest, vitest, contract-testing]

requires:
  - phase: 141-capture
    provides: CaptureService 持久化、脱敏、挂钩与 first-write-wins 幂等语义
provides:
  - report_session_knowledge HTTP 接受、持久化、幂等、脱敏及审计 RED 契约
  - serializer、服务端 snapshot 与 npm properties 三面字段对齐守卫
  - npm 工具可发现性、数量、annotations 与描述语义 RED 契约
affects: [142-02, 142-03, 142-04, report_session_knowledge]

tech-stack:
  added: []
  patterns:
    - Wave 0 tracer-first RED contract
    - 新工具局部三面字段对齐

key-files:
  created:
    - server/tests/mcp_tools/test_report_session_knowledge.py
  modified:
    - server/tests/mcp_tools/test_mcp_package_alignment.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - mcp/tests/server.test.ts

key-decisions:
  - "client 保持开放字符串并只通过既有 ToolCallRecord 审计，不给 SessionCapture 增列"
  - "三面字段守卫只覆盖 report_session_knowledge，不扩大到旧工具历史漂移"
  - "Wave 0 测试保持 RED，生产 serializer、view、URL 与 npm 工具定义留给后续计划"

patterns-established:
  - "accepted=true 必须由真实 capture_id 对应的 SessionCapture 行证明"
  - "仓库或项目挂钩失败只改变 reason，不得拒绝独立 Capture"

requirements-completed: [MCP-01, MCP-02, MCP-03, MCP-04]

duration: 6min
completed: 2026-08-28
---

# Phase 142 Plan 01: MCP 会话回写 RED 契约 Summary

**用 pytest 与 Vitest 建立会话 Capture 接受语义、三面 schema、审计留痕和 npm 可发现性的可执行 RED 契约**

## Performance

- **Duration:** 6 min
- **Started:** 2026-08-28T08:34:18Z
- **Completed:** 2026-08-28T08:40:32Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- 新增 16 个可收集的 HTTP 契约实例，覆盖成功落账、参数/认证拒绝、挂钩失败仍接受、幂等首次写优先、脱敏、审计与 ProjectMemory 隔离。
- 新增只面向 `report_session_knowledge` 的 serializer、snapshot、npm properties 字段级对齐守卫，并独立锁定 12 个请求键与 7 个响应键。
- npm 契约要求工具总数增至 52，锁定新工具可发现性、非只读/非破坏/可幂等/闭世界 annotations 及 Capture 与知识库入库的语义区分。

## Task Commits

1. **Task 1: 建立会话 Capture HTTP 与审计 RED 契约** - `de5b67a4` (test)
2. **Task 2: 建立新工具字段级三面对齐 RED 守卫** - `bbb6d94d` (test)
3. **Task 3: 建立 npm 可发现性与幂等注解 RED 契约** - `74ebd43` (mcp submodule test), `ffd4a895` (superproject pointer)

## Files Created/Modified

- `server/tests/mcp_tools/test_report_session_knowledge.py` - HTTP、持久化、幂等、脱敏、审计与旧工具隔离契约。
- `server/tests/mcp_tools/test_mcp_package_alignment.py` - 新工具局部三面请求键解析与对齐守卫。
- `server/tests/mcp_tools/test_schema_snapshot.py` - 新工具请求/响应键独立字面量期望。
- `mcp/tests/server.test.ts` - npm 可发现性、数量、annotations 与描述语义契约。

## Decisions Made

- `client` 接受未知非空客户端标识，在 `ToolCallRecord.input` 中审计；`SessionCapture` 模型继续无此字段。
- npm properties 解析 helper 只截取目标工具条目，避免把 51 个旧工具的历史字段漂移纳入本阶段门禁。
- 未修改生产 serializer、view、URL、CaptureService、SessionCapture 或旧 `report_project_knowledge` 路径。

## Verification

- `ruff check`：通过，三个服务端测试文件无 lint 错误。
- HTTP 契约：16 项按预期 RED，全部集中失败为 `/api/mcp/tools/report_session_knowledge/` 返回 404。
- schema/alignment 契约：3 项按预期 RED，原因为服务端 snapshot 与 `ReportSessionKnowledgeRequestSerializer` 尚未实现；其余 3 项通过。
- npm 契约：3 项按预期 RED，原因为当前仍是 51 工具且缺少新工具定义/annotations；其余 9 项通过。
- `test_report_project_knowledge.py` 无工作区 diff。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修复状态处理器丢失 frontmatter 字段**
- **Found during:** 计划元数据收口
- **Issue:** free-form `STATE.md` 经状态处理器重写后丢失 `current_phase`、`current_phase_name`、`last_activity_desc` 与 `state_head`。
- **Fix:** 恢复原有必需键，并保留本计划写入的执行状态、指标与决策。
- **Files modified:** `.planning/STATE.md`
- **Verification:** 最终 diff 保留原字段且 Current Position 指向 Phase 142 Plan 01。

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 仅修复 GSD 状态台账完整性，未扩大产品或测试范围。

## Issues Encountered

- `gsd-tools` 未安装到 PATH，按仓库约定改用 `node .cursor/gsd-core/bin/gsd-tools.cjs` 调用。
- `test_schema_snapshot.py` 开始时已有与本计划无关的 `space_id`/`blueprint_project_id` 脏改动；提交时采用局部暂存，仅提交新工具条目并保留原改动。

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02 可按独立 serializer↔snapshot 门禁实现服务端请求契约，再接 URL/view 使 HTTP 测试转绿。
- Plan 03 可新增 npm 工具定义与 annotations，使 Vitest 独立转绿；Plan 04 再统一要求三面全绿。

## Self-Check: PASSED

- 四个计划文件与 SUMMARY 均存在。
- 三个主仓提交及一个 mcp 子模块提交均可在 Git 历史中验证。

---
*Phase: 142-mcp*
*Completed: 2026-08-28*
