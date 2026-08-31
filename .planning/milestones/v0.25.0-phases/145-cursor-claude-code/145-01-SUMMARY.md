---
phase: 145-cursor-claude-code
plan: "01"
subsystem: testing
tags: [node-test, pytest, ide-hooks, cursor, claude-code, session-capture]
requires:
  - phase: 142-mcp
    provides: report_session_knowledge 请求契约
  - phase: 144-capture
    provides: SessionCapture 回放与仓库召回
provides:
  - Cursor hooks.json 非破坏合并的 Node RED 合同
  - Claude Code 与 Cursor 可见问答配对的 subprocess RED 合同
  - 服务端 IDE 资产和 skills 文档职责守卫
affects: [145-02, 145-03, 145-04, 145-05]
tech-stack:
  added: []
  patterns: [node:test 零依赖合同, 真实 bash wrapper 子进程测试, 文件型 HTTP transport seam]
key-files:
  created:
    - skills/lib/cursor-hooks-merge.test.mjs
    - server/tests/hooks/conftest.py
    - server/tests/hooks/test_session_capture_hooks.py
  modified:
    - skills/package.json
    - server/tests/initiatives/test_ide_hook_assets.py
    - server/tests/mcp_tools/test_skills_snapshot_guard.py
key-decisions:
  - "Wave 0 只建立可收集的 RED 合同，不提前实现 helper、hook 或 installer 行为"
  - "skills 测试仅在子模块提交，父仓不暂存或提交 skills gitlink"
patterns-established:
  - "Hook E2E 通过 XDG_CACHE_HOME 隔离状态，并用 FRIDAY_CAPTURE_HTTP_RECORD/FORCE 控制网络"
  - "会话 Capture 与 report_project_knowledge 项目记忆路径分别断言，避免职责合并"
requirements-completed: [SKILL-01, SKILL-02, SKILL-03, SKILL-04, SKILL-05]
duration: 5min
completed: 2026-08-28
---

# Phase 145 Plan 01: 双宿主采集 Wave 0 Summary

**以 44 项可收集 pytest 合同和 4 项 Node RED 合同冻结 Claude Code/Cursor 配对、clean-tree Capture、无 CoT、fail-soft 与 hooks.json merge 行为**

## Performance

- **Duration:** 5 min
- **Started:** 2026-08-28T13:12:03Z
- **Completed:** 2026-08-28T13:16:58Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- 在 skills 子模块加入零依赖 `node:test` merge 合同，当前因 installer 尚未导出目标函数按预期 RED。
- 建立 10 个真实 bash wrapper 行为测试，覆盖双宿主配对、clean/dirty/no-git、失败保留、敏感信息与 CoT 隔离。
- 扩展 IDE 分发资产与 skills 文档守卫，锁定 Cursor before/after、Claude UPS/Stop 及项目记忆职责边界。

## Task Commits

1. **Task 1: skills merge RED 与 node:test script** - `skills@bb648fa`
2. **Task 2: hook 行为 RED** - `a89bde449`
3. **Task 3: IDE 资产与 skills snapshot 守卫 RED** - `ff44b34ee`
4. **Rule 1 修复: 联合收集 conftest 导入冲突** - `10f339366`

## Files Created/Modified

- `skills/package.json` - 新增内置 Node test script，无依赖变化。
- `skills/lib/cursor-hooks-merge.test.mjs` - 锁定 merge、幂等、路径与非法 JSON 行为。
- `server/tests/hooks/conftest.py` - 提供隔离 cache、临时 git 与 HTTP 记录 fixtures。
- `server/tests/hooks/test_session_capture_hooks.py` - 双宿主 session Capture 行为合同。
- `server/tests/initiatives/test_ide_hook_assets.py` - 双宿主分发资产正负向断言。
- `server/tests/mcp_tools/test_skills_snapshot_guard.py` - Capture/项目记忆文档职责守卫。

## Decisions Made

- 保持 tracer-first：生产行为未实现时允许测试 RED，但所有测试必须可联合收集。
- 子模块 commit `bb648fa` 独立存在；父仓 `skills` gitlink 保持未暂存、未提交，留待 145-05 远端可达门禁。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修复多目录联合收集时的 conftest 名称冲突**
- **Found during:** 整体 verification
- **Issue:** 测试模块直接从 `conftest` 导入常量，联合收集时解析到 `tests/initiatives/conftest.py`。
- **Fix:** 将仅用于泄漏断言的假 token 常量限定在测试模块内。
- **Files modified:** `server/tests/hooks/test_session_capture_hooks.py`
- **Verification:** 目标三组测试联合收集 44 项成功。
- **Committed in:** `10f339366`

**Total deviations:** 1 auto-fixed（Rule 1）
**Impact on plan:** 仅修复测试收集可靠性，无生产代码或范围扩张。

## Issues Encountered

- `gsd-tools` 未安装到 PATH，后续通过仓库内 `.cursor/gsd-core/bin/gsd-tools.cjs` 调用。
- 全量行为测试按 Wave 0 预期 RED：Node 缺 merge 导出，pytest 缺 session Capture 生产接线。

## Known Stubs

None - 本计划仅交付 RED 测试合同，不包含生产 stub。

## User Setup Required

None - 无新增依赖或外部服务配置。

## Next Phase Readiness

- 145-02 可按 hook 行为合同实现共享 helper 与双宿主配对。
- 父仓工作树仅保留预期的 `skills` gitlink 变化，必须继续禁止暂存，直到 145-05 完成远端可达检查。

## Self-Check: PASSED

- 6 个计划文件均存在。
- 子模块 commit `bb648fa` 与父仓 commits `a89bde449`、`ff44b34ee`、`10f339366` 均存在。
- 父仓暂存区不含 `skills` 或 `skills/...`。

---
*Phase: 145-cursor-claude-code*
*Completed: 2026-08-28*
