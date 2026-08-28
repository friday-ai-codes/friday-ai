---
phase: 144-capture
plan: "05"
subsystem: api
tags: [mcp, session-capture, authorization, anti-enumeration, nyquist]
requires:
  - phase: 144-04
    provides: 53 工具服务端与 npm 契约及会话知识检索
provides:
  - 创建者与挂钩可见性交集的 SessionCapture 只读授权
  - MCP get_session_capture 中性 404 与字段白名单回放
  - 54 工具服务端、URL 与 npm 跨面对齐契约
  - Phase 144 Nyquist 验证签署
affects: [session-capture-replay, mcp-package, phase-144-verification]
tech-stack:
  added: []
  patterns: [创建者且挂钩 scope 仍可见, 统一 404 防枚举, SessionCapture 唯一正文来源]
key-files:
  created:
    - server/initiatives/services/capture_access.py
    - server/tests/initiatives/test_capture_access.py
  modified:
    - server/initiatives/services/__init__.py
    - server/mcp_tools/views.py
    - server/mcp_tools/serializers.py
    - server/mcp_tools/urls.py
    - mcp/src/tools.ts
    - mcp/tests/server.test.ts
    - server/tests/mcp_tools/test_get_session_capture.py
    - server/tests/mcp_tools/test_get_session_capture_schema_pending.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - server/tests/mcp_tools/test_mcp_package_alignment.py
    - .planning/phases/144-capture/144-VALIDATION.md
key-decisions:
  - "普通用户只有同时满足 Capture 创建者和全部非空挂钩 scope 仍可见时才能回放。"
  - "不存在与未授权统一返回 not_found/资源不存在/404，成功响应只显式返回 SessionCapture 白名单。"
  - "client 固定省略，回放正文不查询 ToolCallRecord、RetrievalTrace 或其它 Ledger 数据。"
patterns-established:
  - "Capture 回放授权集中在 initiatives.services.capture_access.aget_readable_capture。"
  - "只读 MCP 工具同步冻结 serializer、snapshot、URL、npm schema 与 query annotations。"
requirements-completed: [RECALL-03]
duration: 14min
completed: 2026-08-28
---

# Phase 144 Plan 05: Capture 只读回放与 54 工具收口 Summary

**创建者与挂钩可见性交集授权的 SessionCapture 原文回放，以统一 404 防枚举并冻结 54 工具跨面契约**

## Performance

- **Duration:** 14 分钟
- **Started:** 2026-08-28T12:16:56Z
- **Completed:** 2026-08-28T12:30:44Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- 新增 `aget_readable_capture`，普通用户必须为创建者且所有非空 repository/project 挂钩仍可见，超级用户可读。
- 新增 MCP `get_session_capture`，不存在与未授权返回完全一致的中性 404，成功响应固定省略 `client` 与内部评估字段。
- 回放正文只读取 `SessionCapture`，不查询 Interaction Ledger，不投递评估/摄取任务，不推进状态或 attempts。
- 服务端 serializer/snapshot/URL 与 npm `FRIDAY_TOOLS`、query annotations 对齐到恰好 54 个工具。
- Phase 144 最终 Nyquist 门禁 163 项 server 测试、14 项 npm 测试及 ruff 全绿。

## Task Commits

1. **Task 1 RED：锁定 Capture 回放授权契约** - `55140595e`（test）
2. **Task 1 GREEN：实现 Capture 只读回放授权** - `525e197c4`（feat）
3. **Task 2 RED：锁定 MCP Capture 回放契约** - `3ef99de5b`（test）
4. **Task 2 GREEN：提供 MCP Capture 只读回放** - `fd1e18ec5`（feat）

子模块提交：

- `63cdd8b`：npm 54 工具与只读 annotations RED 契约。
- `c611f17`：npm `get_session_capture` 工具实现。

## Files Created/Modified

- `server/initiatives/services/capture_access.py` - 创建者与挂钩 scope 只读授权。
- `server/initiatives/services/__init__.py` - 显式导出授权 helper。
- `server/mcp_tools/views.py` - Capture 白名单回放与统一 404。
- `server/mcp_tools/serializers.py` - UUID 请求 serializer 与工具快照。
- `server/mcp_tools/urls.py` - `get_session_capture` MCP 路由。
- `mcp/src/tools.ts` - 第 54 个工具与只读 query annotations。
- `mcp/tests/server.test.ts` - 54 工具、发现性与 annotations 守卫。
- `server/tests/initiatives/test_capture_access.py` - service 授权、只读与 Ledger 隔离契约。
- `server/tests/mcp_tools/test_get_session_capture.py` - HTTP allowlist、防枚举、scope 与状态不变契约。
- `server/tests/mcp_tools/test_get_session_capture_schema_pending.py` - 独立 get schema 契约转绿。
- `server/tests/mcp_tools/test_schema_snapshot.py` - 完整 54 工具快照。
- `server/tests/mcp_tools/test_mcp_package_alignment.py` - get serializer/snapshot/npm 三面对齐。
- `.planning/phases/144-capture/144-VALIDATION.md` - Phase 144 Nyquist 结果与签署。

## Decisions Made

- repository 与 project 挂钩分别通过现有 access scope resolver 收口；任一不可见即拒绝，不做 OR 放宽。
- 未授权不写工具调用 Ledger，直接与缺失记录返回同一 `not_found` 404；授权成功仍沿用 MCP 基类记录调用指标，正文来源保持仅 `SessionCapture`。
- `client` 不存在于 `SessionCapture`，因此响应固定省略，不返回 `null`、不猜测、不从 Ledger 补齐。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正授权测试的仓库挂钩前置条件**
- **Found during:** Task 1（只读授权）
- **Issue:** 初始测试仅建立 SpaceMembership，但 Capture 写侧还要求项目成员权限，导致测试 Capture 正确落为 `repo_unauthorized` 且无 repository FK。
- **Fix:** 测试通过 `ProjectService` 建立同空间项目与创建者成员关系，再同时挂钩 repository/project，确保验证目标是读侧 scope 翻转。
- **Files modified:** `server/tests/initiatives/test_capture_access.py`
- **Verification:** 6 项授权测试全部通过。
- **Committed in:** `525e197c4`

---

**Total deviations:** 1 auto-fixed（1 个 Rule 1）
**Impact on plan:** 仅修正测试前置条件，未放宽生产授权或改变 Capture 唯一 writer。

## Issues Encountered

- Friday 对 `main` 分支仍召回到无关项目；本次未采信该上下文，也未向该项目回写知识或 API 状态。
- pytest 多次在销毁测试库时报告仍有一个既有连接，断言均通过；最终 full suite 正常退出为 0。

## User Setup Required

无需外部配置。

## Verification

- `server` Phase 144 full suite：163 passed。
- `mcp`：14 passed。
- `ruff`：所有本计划改动 Python 文件通过。
- IDE diagnostics：无新增错误。

## Known Stubs

无。

## Next Phase Readiness

- RECALL-03 已完成，Phase 144 的 RECALL-01~04 与 OBS-03 均具备自动化契约。
- `.planning/phases/144-capture/144-VALIDATION.md` 已设置 `status: validated`、`nyquist_compliant: true` 与 `wave_0_complete: true`。
- 无阻塞项。

## Self-Check: PASSED

- Summary 与 Validation 文件存在。
- `55140595e`、`525e197c4`、`3ef99de5b`、`fd1e18ec5` 四个主仓任务提交均可定位。
- npm 子模块 RED/GREEN 提交已由主仓指针提交引用。

---
*Phase: 144-capture*
*Completed: 2026-08-28*
