---
phase: 145-cursor-claude-code
plan: "05"
subsystem: ide-hooks
tags: [cursor, claude-code, session-capture, git-submodule]
status: complete
distributed_asset_parity: complete
requires:
  - phase: 145-02
    provides: Claude Code Session Capture
  - phase: 145-03
    provides: Cursor Session Capture 与安装器
  - phase: 145-04
    provides: skills 文档与 HTTP fallback 契约
provides:
  - 服务端 Cursor/Claude Code Session Capture 下载资产与远端可达 skills gitlink 收口
affects: [SKILL-03, SKILL-04, SKILL-05]
tech-stack:
  added: []
  patterns: [advertised-ref ancestry gate, fail-soft IDE hooks]
key-files:
  created: []
  modified:
    - server/initiatives/services/ide_hook_assets.py
    - skills
key-decisions:
  - "父仓 gitlink 仅在 skills child SHA 可由远端 advertised heads/tags 到达时提交。"
patterns-established:
  - "控制台下载资产与 skills 分发面按不变量对齐，禁止 runtime import skills/hooks。"
requirements-completed: [SKILL-03, SKILL-04, SKILL-05]
duration: 10min
completed: 2026-08-31
---

# Phase 145 Plan 05: IDE 资产对齐与 skills gitlink Summary

**控制台 Cursor/Claude Capture 下载资产已与实体 skills 事件模型对齐，且父仓 gitlink 指向远端 `refs/heads/main` 可达的 skills SHA。**

## Performance

- **Duration:** 10 min（门禁通过后续跑）
- **Started:** 2026-08-31T06:44:13Z
- **Completed:** 2026-08-31T06:51:00Z
- **Tasks:** 3
- **Files modified:** 2（父仓；不含规划文档）

## Accomplishments

- Cursor 写路径 `hooks.json` v1 注册 `beforeSubmitPrompt` / `afterAgentResponse`，project-memory `stop` 不含 Capture 字段。
- Claude Code 产出实体 `friday-session-capture-user-prompt-submit.sh` 与 `friday-session-capture-stop.sh`，并在 `settings.json` 按真实路径注册；既有 `friday-stop-writeback.sh` 仅 `report_project_knowledge` / `report_project_state`。
- Codex 写路径资产零回归。
- skills 子模块 advertised-tip ancestry 门通过后，父仓一次提交 gitlink + `ide_hook_assets.py`；未把 `skills/hooks` 当普通文件暂存。

## Task Commits

1. **Task 1: 扩展 ide_hook_assets Cursor/Claude Capture 资产** — 与 Task 3 同一次父仓提交（计划要求原子收口）。
2. **Task 2: skills 子 SHA 远端可达发布门** — 操作员推送；执行器未 push。skills HEAD `c3ed7bb40b3774213f121f020e98d029aab10221`。
3. **Task 3: 远端门通过后暂存 gitlink 并完成回归** — `1e06af26c` (`feat(145-05): 对齐 IDE 下载资产并收口 skills gitlink`)

**Plan metadata:** 见本文件随后的 docs 提交。

## Gate Evidence

- 检查时间：`2026-08-31T06:44:13Z`（复核）与提交前再次 `fetch` + `ls-remote`。
- child SHA：`c3ed7bb40b3774213f121f020e98d029aab10221`
- 远端 advertised tip：`c3ed7bb40b3774213f121f020e98d029aab10221` (`refs/heads/main`)
- 方法：`git -C skills fetch origin --prune --tags`，读取全部 `ls-remote --heads --tags origin`（忽略 peeled `^{}`），`merge-base --is-ancestor "$child_sha" "$tip_sha"`。
- 结果：PASS（child 即 `origin/main` tip，祖先关系成立）。
- 父仓 gitlink：`5b08670e0` → `c3ed7bb40`
- 推送：未执行父仓 push；未再次 push skills。

## Verify Suite

- advertised-tip ancestry：PASS
- `tests/initiatives/test_ide_hook_assets.py`：27 passed（Task 1 门禁）
- Task 3 pytest 联合：82 passed（hooks、ide assets、snapshot guard、report_session_knowledge、report_project_knowledge、schema snapshot、12 键 alignment）
- `skills` `node --test lib/*.test.mjs`：6 passed
- `mcp` `npm test -- tests/server.test.ts`：14 passed
- 12 键：`test_report_session_knowledge_request_keys_aligned` passed，无漂移。

## Files Created/Modified

- `server/initiatives/services/ide_hook_assets.py` — Cursor before/after Capture 脚本、Claude UPS/Stop 实体 Capture、隔离的 project-memory stop。
- `skills` — gitlink 指向远端可达 SHA `c3ed7bb`。

## Decisions Made

- 父仓 gitlink 仅在 skills child SHA 可由远端 advertised heads/tags 到达时提交。
- 服务端资产内嵌 Capture 脚本，不 runtime import `skills/hooks`。

## Deviations from Plan

None - plan executed as written after the human skills-push gate.

Task 1 未单独提交：按 Task 3「一次 commit 同时包含 gitlink 与 ide_hook_assets.py」收口。

---

**Total deviations:** 0 auto-fixed
**Impact on plan:** 无范围蔓延。

## Issues Encountered

- 续跑时 zsh `for tip in $tips` 未按行拆分，导致联合命令里 ancestry 循环误报 object name；改用已通过的 bash 复核 + 分步跑测试，未改业务代码。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `distributed_asset_parity=complete`，SKILL-03/04/05 可宣称完成。
- ROADMAP Phase 145 成功标准 1–5 的资产/文档/gitlink 面已收口；真实 IDE 点一次安装仍为可选事后 smoke。
- MCP-04 `report_project_knowledge` 本计划回归 15 项通过。

## Self-Check: PASSED

- FOUND: `.planning/phases/145-cursor-claude-code/145-05-SUMMARY.md`
- FOUND: `server/initiatives/services/ide_hook_assets.py`
- FOUND: commit `1e06af26c`

---
*Phase: 145-cursor-claude-code*
*Completed: 2026-08-31*
