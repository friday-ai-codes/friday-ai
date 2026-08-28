---
phase: 142-mcp
plan: "03"
subsystem: mcp
tags: [mcp, typescript, json-schema, session-capture, vitest]

requires:
  - phase: 142-mcp
    plan: "01"
    provides: report_session_knowledge npm 可发现性、schema 与 annotations RED 契约
provides:
  - npm MCP 静态白名单中的第 52 个 report_session_knowledge 工具
  - 与服务端对齐的 12 字段严格输入 schema
  - 非只读、非破坏、可幂等、闭世界的专用工具 annotations
affects: [142-04, report_session_knowledge, npm-mcp]

tech-stack:
  added: []
  patterns:
    - MCP 内部幂等写操作使用独立 annotations，不复用 generator helper
    - 工具描述区分 Capture 持久化与仓库挂钩、价值评估、知识库入图

key-files:
  created:
    - .planning/phases/142-mcp/142-03-SUMMARY.md
  modified:
    - mcp/src/tools.ts

key-decisions:
  - "session_id、token 计数与 client 均保持开放字符串，避免 npm schema 比服务端更严格"
  - "report_session_knowledge 使用独立 annotations，准确表达 first-write-wins 幂等语义"

patterns-established:
  - "会话 Capture 工具只要求 question 与 answer，并拒绝额外请求键"
  - "accepted=true 仅表示 Capture 已持久化，不承诺挂钩、评估或 RAG 入图"

requirements-completed: [MCP-01, MCP-03]

duration: 2min
completed: 2026-08-28
---

# Phase 142 Plan 03: npm MCP 会话回写契约 Summary

**npm MCP 新增可发现的 `report_session_knowledge`，以严格 12 字段 schema 和专用幂等注解公开安全的 Capture 写入语义**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-28T08:44:00Z
- **Completed:** 2026-08-28T08:45:07Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 将 `FRIDAY_TOOLS` 从 51 项扩展为 52 项，新增 `report_session_knowledge` 静态工具定义。
- 输入 schema 精确公开 12 个请求键，仅要求 `question` 与 `answer`，并设置 `additionalProperties=false`。
- 工具描述禁止上传全文 transcript、隐藏思维链与凭证，并明确 `accepted=true` 不代表仓库挂钩、价值评估或知识库/RAG 入图。
- 新增独立 annotations，锁定非只读、非破坏、可幂等且不触达 Friday 外部系统。

## Task Commits

1. **Task 1: 同步发布 npm 工具条目与幂等 annotations** - `313c212`（mcp 子模块 feat）、`75b0307f`（主仓指针 feat）

## Files Created/Modified

- `mcp/src/tools.ts` - 新增会话 Capture 工具定义、严格输入 schema、专用 annotations，并更新真实工具计数。
- `.planning/phases/142-mcp/142-03-SUMMARY.md` - 记录本计划实现、验证与提交信息。

## Decisions Made

- `input_tokens` 与 `output_tokens` 使用字符串 schema，与服务端保留原始计数文本的契约一致。
- `session_id` 不声明 UUID 格式，兼容不同 IDE 宿主的会话标识。
- 不调用 `generator()`，避免其 `idempotentHint=false` 与服务端 first-write-wins 语义冲突。

## Verification

- `cd mcp && npm test -- tests/server.test.ts`：12 项全部通过。
- `git diff -- mcp/package.json mcp/package-lock.json`：为空，未安装或升级依赖。
- IDE lint：`mcp/src/tools.ts` 无诊断。
- TDD RED/GREEN：既有 RED 提交 `74ebd43` 先锁定 3 个失败契约；本计划 GREEN 提交 `313c212` 后全部转绿。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 恢复状态处理器丢失的 frontmatter 字段**
- **Found during:** 计划元数据收口
- **Issue:** free-form `STATE.md` 经状态处理器重写后丢失 `current_phase`、`current_phase_name`、`last_activity_desc` 与 `state_head`，且会话停止点仍指向 Plan 01。
- **Fix:** 恢复原有必需键，并将活动与停止点更新为 Plan 03。
- **Files modified:** `.planning/STATE.md`
- **Verification:** 最终 diff 保留必需字段，Current Position 与会话停止点均反映 Phase 142 Plan 03。

**Total deviations:** 1 auto-fixed（1 bug）
**Impact on plan:** 仅修复 GSD 状态台账完整性，未扩大产品实现范围。

## Issues Encountered

- `gsd-tools` 未安装到 PATH，状态命令使用仓库内 `node .cursor/gsd-core/bin/gsd-tools.cjs` 等价入口。
- 当前主仓存在 Plan 02 并发修改及预先存在的 server、skills、调试文档改动；本计划只暂存 `mcp` 子模块指针与自己的 Summary，未触碰这些文件。

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- npm 客户端面已满足 MCP-01/MCP-03，可由 Plan 04 执行服务端、snapshot 与 npm 三面整体验证。
- 本计划未修改旧 `report_project_knowledge` 或全局 `generator()` 语义。

## Self-Check: PASSED

- `mcp/src/tools.ts` 与本 Summary 均存在。
- 子模块提交 `313c212` 与主仓提交 `75b0307f` 均可在 Git 历史中验证。

---
*Phase: 142-mcp*
*Completed: 2026-08-28*
