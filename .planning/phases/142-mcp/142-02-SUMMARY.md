---
phase: 142-mcp
plan: "02"
subsystem: api
tags: [mcp, django, session-capture, audit, drf]

requires:
  - phase: 142-01
    provides: report_session_knowledge 的 HTTP、schema 与审计 RED 契约
  - phase: 141-capture
    provides: CaptureService 唯一 writer、脱敏、挂钩与 first-write-wins 幂等语义
provides:
  - report_session_knowledge 的 Django 请求 serializer 与服务端 schema snapshot
  - 复用 McpToolView 生命周期和 CaptureService 的已认证 HTTP 写入入口
  - 挂钩失败仍返回 accepted=true 与真实 capture_id 的稳定响应契约
affects: [142-04, report_session_knowledge, session-capture]

tech-stack:
  added: []
  patterns:
    - McpToolView 认证与脱敏审计外壳
    - CaptureService 作为 SessionCapture 唯一 writer

key-files:
  created: []
  modified:
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py

key-decisions:
  - "client 作为开放请求元数据进入既有脱敏审计，但不传给 CaptureService 或扩展 SessionCapture"
  - "accepted=true 只在 CaptureService.persist 成功返回后构造，仓库或项目挂钩结果仅体现在 reason 与实际 FK"

patterns-established:
  - "新会话回写入口严格复用 _begin、_validate、_record，不直写指标、Ledger 或 SessionCapture"
  - "report_project_knowledge 的项目门闩、质量门与历史响应语义保持隔离"

requirements-completed: [MCP-01, MCP-02, MCP-03, MCP-04]

duration: 5min
completed: 2026-08-28
---

# Phase 142 Plan 02: MCP 会话回写服务端契约 Summary

**Django MCP 入口通过 CaptureService 持久化会话问答，并以可审计的 200 响应稳定表达挂钩结果与幂等命中**

## Performance

- **Duration:** 5 min
- **Started:** 2026-08-28T08:44:01Z
- **Completed:** 2026-08-28T08:49:13Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 新增 12 字段请求 serializer 与 7 字段响应 snapshot，问答为唯一必填字段，`client` 和 token 元数据保持开放字符串。
- 新增 `/api/mcp/tools/report_session_knowledge/`，显式透传触发用户并只调用 `CaptureService.persist` 写入 Capture。
- 成功路径复用 `McpToolView._record` 写入脱敏调用审计与统一指标；仓库或项目挂钩失败不改变 `accepted=true`。

## Task Commits

1. **Task 1: 定义请求 serializer 与服务端 schema snapshot** - `935fb744` (feat)
2. **Task 2: 接线 McpToolView、CaptureService 与 URL** - `c5c9b024` (feat)

## Files Created/Modified

- `server/mcp_tools/serializers.py` - 定义请求字段并冻结服务端工具 schema。
- `server/mcp_tools/views.py` - 实现唯一 writer 接线、响应映射与脱敏审计生命周期。
- `server/mcp_tools/urls.py` - 注册会话知识回写 POST 路由。

## Decisions Made

- `client` 只保留在 `_record` 的完整 `input_data` 中，不给现有模型增加字段，也不改变 `CaptureService` 公共签名。
- `reason`、`idempotent_hit` 和 Capture 实际外键均原样映射；只有 persist 成功后才返回 `accepted=true`。
- 不复制旧 `report_project_knowledge` 的项目解析门闩、质量门、Memory 写入或 `accepted=false` fail-soft 语义。

## Verification

- `ruff check`：计划拥有的 serializer、view、URL 与 HTTP 契约测试文件全部通过。
- serializer/snapshot 契约：2 项通过。
- HTTP、路由名集与 INV-6 回归：20 项通过。
- `SessionCapture` 模型、`CaptureService`、旧 `report_project_knowledge` 测试及 Plan 03 npm 文件均无本计划 diff。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 恢复状态处理器丢失的 frontmatter 字段**
- **Found during:** 计划元数据收口
- **Issue:** free-form `STATE.md` 经状态处理器重写后丢失 `current_phase`、`current_phase_name`、`last_activity_desc` 与 `state_head`。
- **Fix:** 恢复四个既有必需键，并保留 Plan 03 较新的 session/activity 信息。
- **Files modified:** `.planning/STATE.md`
- **Verification:** 最终 diff 保留既有字段且 Current Position 为 Phase 142 Plan 3 of 4 complete。

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 仅修复 GSD 状态台账完整性，未扩大产品实现范围。

## Issues Encountered

- 首次数据库回归与并行 pytest 同时创建/删除 `test_friday`，产生数据库占用错误；改用 `--reuse-db` 后目标 20 项全部通过，无代码断言失败。
- `serializers.py` 存在并行工作预留的 `space_id`/`blueprint_project_id` 脏改动；Task 1 采用局部暂存，仅提交本计划 serializer 与 snapshot 条目。

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03 已并行完成 npm 工具定义，Plan 04 可执行服务端、snapshot 与 npm 三面总回归。
- 没有遗留产品阻塞；既有无关工作区改动保持未提交状态。

## Self-Check: PASSED

- 三个生产文件和本 Summary 均存在。
- `935fb744` 与 `c5c9b024` 可在 Git 历史中验证。

---
*Phase: 142-mcp*
*Completed: 2026-08-28*
